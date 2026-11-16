"""Durable ownership for EWO export side effects; no credentials or tokens stored."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


class ExportJobConflict(ValueError):
    """Missing ownership, stale lease, or an unavailable state transition."""


#: 活跃状态：仍可能推进，或需要人工核查；同键（scope+purpose+selection）不允许并存。
ACTIVE_STATES = frozenset({
    'queued', 'listing', 'generating', 'generation_unknown',
    'generated', 'downloading', 'projecting', 'writing',
})

#: 旧版本代码认识且**允许重试**的状态；回滚静默化后不得残留这些名字的活跃行。
LEGACY_RETRYABLE_STATES = frozenset({'interrupted', 'failed'})

_ACTIVE_SQL = "('queued','listing','generating','generation_unknown','generated','downloading','projecting','writing')"


def _reference(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', value):
        raise ValueError('Invalid source item reference')
    return value.upper()


def _now(value):
    return time.time() if value is None else float(value)


class EWOExportJobs:
    def __init__(self, path):
        self.path = Path(path)
        with self._transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS ewo_export_jobs (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, selection_hash TEXT NOT NULL,
                item_ids TEXT NOT NULL, state TEXT NOT NULL,
                file_id TEXT, snapshot_ref TEXT, lease_token TEXT, lease_until REAL,
                created REAL NOT NULL, updated REAL NOT NULL
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ewo_export_data (
                job_id TEXT PRIMARY KEY, context TEXT NOT NULL, snapshot TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ewo_export_failures (
                job_id TEXT PRIMARY KEY, stage TEXT NOT NULL
            )''')
            self._migrate_columns(conn)
            self._migrate_active_index(conn)

    @staticmethod
    def _migrate_columns(conn):
        """Additive columns only; existing rows keep working (purpose defaults to enrichment)."""
        additions = {
            'cancel_requested': 'INTEGER NOT NULL DEFAULT 0',
            'purpose': "TEXT NOT NULL DEFAULT 'enrichment'",
            'error_code': 'TEXT',
            'artifact_path': 'TEXT',
            'artifact_sha256': 'TEXT',
            'row_count': 'INTEGER',
        }
        existing = {row[1] for row in conn.execute('PRAGMA table_info(ewo_export_jobs)')}
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE ewo_export_jobs ADD COLUMN {name} {ddl}')

    @staticmethod
    def _migrate_active_index(conn):
        """Rebuild the partial unique index over (scope, purpose, selection_hash).

        SQLite cannot alter an index predicate, so the index is dropped and recreated.
        Duplicate active rows under the new key would make the unique index fail; they
        are pre-checked and reported instead of being silently merged or deleted.
        """
        current = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ewo_export_jobs_active'"
        ).fetchone()
        if current is not None and 'purpose' in (current['sql'] or '') and 'projecting' in (
            current['sql'] or ''
        ):
            return
        duplicates = conn.execute(
            f'''SELECT scope, purpose, selection_hash, COUNT(*) AS n
                FROM ewo_export_jobs WHERE state IN {_ACTIVE_SQL}
                GROUP BY scope, purpose, selection_hash HAVING n > 1'''
        ).fetchall()
        if duplicates:
            raise ExportJobConflict(
                'Export job duplicates block the active-index migration '
                f'({len(duplicates)} key(s)); resolve them manually before upgrading'
            )
        conn.execute('DROP INDEX IF EXISTS ewo_export_jobs_active')
        conn.execute(
            f'''CREATE UNIQUE INDEX ewo_export_jobs_active
                ON ewo_export_jobs(scope, purpose, selection_hash)
                WHERE state IN {_ACTIVE_SQL}'''
        )

    @contextmanager
    def _transaction(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create(self, scope, item_ids, *, purpose='enrichment', context=None, now=None):
        if not isinstance(scope, str) or not scope.strip() or len(scope) > 256:
            raise ValueError('Invalid source scope')
        if not isinstance(purpose, str) or not re.fullmatch(r'[a-z_]{1,64}', purpose):
            raise ValueError('Invalid export purpose')
        if not isinstance(item_ids, (list, tuple)) or not 1 <= len(item_ids) <= 5000:
            raise ValueError('Invalid selection size')
        ids = sorted(_reference(value) for value in item_ids)
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate source item reference')
        encoded = json.dumps(ids, separators=(',', ':'))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        timestamp = _now(now)
        with self._transaction() as conn:
            # 幂等键按 (scope, purpose, selection) 隔离：只读面板与 CSV 导出即使选中
            # 同一批 EWO，也必须是两个独立任务，不能互相认领。
            row = conn.execute(
                f'''SELECT * FROM ewo_export_jobs WHERE scope=? AND purpose=?
                    AND selection_hash=? AND state IN {_ACTIVE_SQL}''',
                (scope, purpose, digest),
            ).fetchone()
            if row is None:
                job_id = uuid.uuid4().hex
                conn.execute('''INSERT INTO ewo_export_jobs
                    (id,scope,purpose,selection_hash,item_ids,state,created,updated)
                    VALUES (?,?,?,?,?,'queued',?,?)''',
                             (job_id, scope, purpose, digest, encoded, timestamp, timestamp))
                conn.execute('INSERT INTO ewo_export_data(job_id,context) VALUES (?,?)',
                             (job_id, json.dumps(context or {}, ensure_ascii=False, allow_nan=False)))
                row = conn.execute('SELECT * FROM ewo_export_jobs WHERE id=?', (job_id,)).fetchone()
                fresh = dict(row)
                # 调用方据此决定是否启动执行器：命中已有活跃任务时不得再 spawn，
                # 否则同一选择会有两条线程竞争同一次非幂等的服务端生成。
                # 注意不能叫 created——那是表里的时间戳列。
                fresh['is_new'] = True
                return fresh
            return dict(row)

    def data(self, job_id, scope):
        with self._transaction() as conn:
            self._row(conn, job_id, scope)
            row = conn.execute('SELECT * FROM ewo_export_data WHERE job_id=?', (job_id,)).fetchone()
            if row is None:
                raise ExportJobConflict('Export context unavailable')
            return json.loads(row['context']), json.loads(row['snapshot']) if row['snapshot'] else None

    def update_context(self, job_id, scope, context, *, now=None):
        """替换导出上下文（只存选择集等元数据，不存业务行内容）。"""
        encoded = json.dumps(context, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > 8 * 1024 * 1024:
            raise ValueError('Export context too large')
        with self._transaction() as conn:
            self._row(conn, job_id, scope)
            cursor = conn.execute(
                'UPDATE ewo_export_data SET context=? WHERE job_id=?', (encoded, job_id)
            )
            if cursor.rowcount != 1:
                raise ExportJobConflict('Export context unavailable')

    def read(self, job_id, scope):
        with self._transaction() as conn:
            job = dict(self._row(conn, job_id, scope))
            row = conn.execute('SELECT * FROM ewo_export_data WHERE job_id=?', (job_id,)).fetchone()
            if row is None:
                raise ExportJobConflict('Export context unavailable')
            error = conn.execute('SELECT stage FROM ewo_export_failures WHERE job_id=?', (job_id,)).fetchone()
            return (job, json.loads(row['context']), json.loads(row['snapshot']) if row['snapshot'] else None,
                    error['stage'] if error else None)

    def latest(self, scope, query_signature, *, purpose='enrichment'):
        with self._transaction() as conn:
            rows = conn.execute('''SELECT j.id,d.context FROM ewo_export_jobs j
                JOIN ewo_export_data d ON d.job_id=j.id
                WHERE j.scope=? AND j.purpose=? ORDER BY j.created DESC''',
                                (scope, purpose))
            for row in rows:
                if json.loads(row['context']).get('query_signature') == query_signature:
                    return row['id']
        raise ExportJobConflict('Export job unavailable')

    def complete(self, job_id, scope, lease_token, snapshot, *, now=None):
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > 64 * 1024 * 1024:
            raise ValueError('Export snapshot too large')
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if (row['state'] != 'downloading' or row['lease_token'] != lease_token
                    or row['lease_until'] is None or row['lease_until'] <= timestamp):
                raise ExportJobConflict('Export ownership lost')
            updated = conn.execute('UPDATE ewo_export_data SET snapshot=? WHERE job_id=?', (encoded, job_id))
            if updated.rowcount != 1:
                raise ExportJobConflict('Export context unavailable')
            conn.execute('''UPDATE ewo_export_jobs SET state='parsed',snapshot_ref=?,
                lease_token=NULL,lease_until=NULL,updated=? WHERE id=?''', (job_id, timestamp, job_id))
            conn.execute('DELETE FROM ewo_export_failures WHERE job_id=?', (job_id,))

    @staticmethod
    def _row(conn, job_id, scope):
        row = conn.execute('SELECT * FROM ewo_export_jobs WHERE id=? AND scope=?', (job_id, scope)).fetchone()
        if row is None:
            raise ExportJobConflict('Export job unavailable')
        return row

    def get(self, job_id, scope):
        with self._transaction() as conn:
            return dict(self._row(conn, job_id, scope))

    def claim(self, job_id, scope, *, now=None, lease_seconds=600):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid lease duration')
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if row['cancel_requested']:
                # 取消请求已受理：把任务冻结到不可重试的终态，而不是永久占用 active 键。
                conn.execute(
                    '''UPDATE ewo_export_jobs SET state='cancelled',lease_token=NULL,
                       lease_until=NULL,updated=? WHERE id=?''',
                    (timestamp, job_id),
                )
            elif row['state'] not in ('queued', 'generated'):
                raise ExportJobConflict('Export job cannot be claimed')
            else:
                state = 'generating' if row['state'] == 'queued' else 'downloading'
                conn.execute(
                    'UPDATE ewo_export_jobs SET state=?,lease_token=?,lease_until=?,updated=? WHERE id=?',
                    (state, uuid.uuid4().hex, timestamp + lease_seconds, timestamp, job_id),
                )
                return dict(self._row(conn, job_id, scope))
        # 事务已提交（cancelled 落库）后再抛，调用方得到明确信号且库状态一致。
        raise ExportJobConflict('Export job cancel requested')

    def _finish(self, job_id, scope, lease_token, expected, target, field, value, now):
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if (row['state'] != expected or row['lease_token'] != lease_token
                    or row['lease_until'] is None or row['lease_until'] <= timestamp):
                raise ExportJobConflict('Export ownership lost')
            # Field names only come from the fixed methods below.
            conn.execute(f'''UPDATE ewo_export_jobs SET state=?,{field}=?,lease_token=NULL,
                lease_until=NULL,updated=? WHERE id=?''', (target, value, timestamp, job_id))
            return dict(self._row(conn, job_id, scope))

    def generated(self, job_id, scope, lease_token, file_id, *, now=None):
        """generating → generated；若期间收到取消请求则直接落 cancelled（保留 file_id）。

        取消不得把任务留在 active 状态：否则它会永久占用唯一键，且回滚静默化只能把它
        交给旧代码继续下载（下载失败后旧重试会重新生成）。
        """
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if (row['state'] != 'generating' or row['lease_token'] != lease_token
                    or row['lease_until'] is None or row['lease_until'] <= timestamp):
                raise ExportJobConflict('Export ownership lost')
            target = 'cancelled' if row['cancel_requested'] else 'generated'
            # generated 是「文件已生成、下载尚未完成」的短暂可续状态：保留一个短租约，
            # 让任务中心在下载线程接手前仍把它视为在途，避免把“已生成”误报成“已完成”。
            # 进程若在此窗口退出，租约自然过期，任务回落为可续下载而不是永久 running。
            lease_until = timestamp + 60 if target == 'generated' else None
            conn.execute(
                '''UPDATE ewo_export_jobs SET state=?,file_id=?,lease_token=NULL,
                   lease_until=?,updated=? WHERE id=?''',
                (target, _reference(file_id), lease_until, timestamp, job_id),
            )
            return dict(self._row(conn, job_id, scope))

    def parsed(self, job_id, scope, lease_token, snapshot_ref, *, now=None):
        if not isinstance(snapshot_ref, str) or not snapshot_ref or len(snapshot_ref) > 256:
            raise ValueError('Invalid snapshot reference')
        return self._finish(job_id, scope, lease_token, 'downloading', 'parsed',
                            'snapshot_ref', snapshot_ref, now)

    def start_listing(self, job_id, scope, *, lease_seconds=1800, now=None):
        """queued → listing：只读的列表预检阶段，可自由重试。"""
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if row['state'] != 'queued' or row['cancel_requested']:
                raise ExportJobConflict('Export job cannot start listing')
            conn.execute(
                '''UPDATE ewo_export_jobs SET state='listing',lease_token=?,lease_until=?,updated=?
                   WHERE id=?''',
                (uuid.uuid4().hex, timestamp + lease_seconds, timestamp, job_id),
            )
            return dict(self._row(conn, job_id, scope))

    def begin_generation(self, job_id, scope, lease_token, *, lease_seconds=900, now=None):
        """listing → generating：必须先提交本状态，再调用服务端生成。

        这是“绝不重发”的顺序契约：进程若在生成调用中途退出，库里已经是
        generating，recover 会把它转成 generation_unknown，而不是允许重试。
        """
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid lease duration')
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if (row['state'] != 'listing' or row['lease_token'] != lease_token
                    or row['lease_until'] is None or row['lease_until'] <= timestamp):
                raise ExportJobConflict('Export ownership lost')
            conn.execute(
                '''UPDATE ewo_export_jobs SET state='generating',lease_until=?,updated=?
                   WHERE id=?''',
                (timestamp + lease_seconds, timestamp, job_id),
            )
            return dict(self._row(conn, job_id, scope))

    def complete_export(
        self,
        job_id,
        scope,
        lease_token,
        *,
        artifact_path=None,
        artifact_sha256=None,
        row_count=None,
        now=None,
    ):
        """downloading → exported；只记录产物元数据，业务数据不落库。"""
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if (row['state'] != 'downloading' or row['lease_token'] != lease_token
                    or row['lease_until'] is None or row['lease_until'] <= timestamp):
                raise ExportJobConflict('Export ownership lost')
            conn.execute(
                '''UPDATE ewo_export_jobs SET state='exported',artifact_path=?,artifact_sha256=?,
                   row_count=?,lease_token=NULL,lease_until=NULL,updated=? WHERE id=?''',
                (artifact_path, artifact_sha256, row_count, timestamp, job_id),
            )
            conn.execute('DELETE FROM ewo_export_failures WHERE job_id=?', (job_id,))
            return dict(self._row(conn, job_id, scope))

    def fail_export(self, job_id, scope, lease_token, *, stage, code, now=None):
        """listing/downloading/projecting/writing → export_failed。

        ``generating`` 阶段的失败绝不能走这里：那条路径必须是 generation_unknown，
        否则“生成结果未知”会被降级成可重试的失败。
        """
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if row['lease_token'] != lease_token:
                raise ExportJobConflict('Export ownership lost')
            if row['state'] not in ('listing', 'downloading', 'projecting', 'writing'):
                raise ExportJobConflict('Export job cannot fail from this state')
            conn.execute(
                '''UPDATE ewo_export_jobs SET state='export_failed',error_code=?,lease_token=NULL,
                   lease_until=NULL,updated=? WHERE id=?''',
                (code, timestamp, job_id),
            )
            conn.execute(
                'INSERT OR REPLACE INTO ewo_export_failures(job_id,stage) VALUES (?,?)',
                (job_id, stage),
            )
            return dict(self._row(conn, job_id, scope))

    def interrupted(self, job_id, scope, lease_token, *, now=None):
        timestamp = _now(now)
        with self._transaction() as conn:
            row = self._row(conn, job_id, scope)
            if row['lease_token'] != lease_token or row['state'] not in ('generating', 'downloading'):
                raise ExportJobConflict('Export ownership lost')
            target = 'generation_unknown' if row['state'] == 'generating' else 'generated'
            stage = 'generation' if row['state'] == 'generating' else 'download-or-parse'
            conn.execute('INSERT OR REPLACE INTO ewo_export_failures(job_id,stage) VALUES (?,?)', (job_id, stage))
            conn.execute('''UPDATE ewo_export_jobs SET state=?,lease_token=NULL,lease_until=NULL,updated=? WHERE id=?''',
                         (target, timestamp, job_id))

    def recover(self, *, purpose=None, now=None):
        """Recover expired leases without ever re-issuing a generation.

        generating → generation_unknown (outcome unprovable), listing → export_failed
        (nothing was sent upstream), downloading/projecting/writing → generated
        (the file reference is persisted, so the download can be resumed).

        ``purpose`` 限制作用范围：只读增强导表只能收敛自己的任务，绝不能把另一个
        子系统正在运行的导出任务改成 generation_unknown。
        """
        timestamp = _now(now)
        purpose_sql = ' AND purpose=?' if purpose else ''
        params: list[object] = [timestamp, timestamp]
        if purpose:
            params.append(purpose)
        with self._transaction() as conn:
            cursor = conn.execute(f'''UPDATE ewo_export_jobs SET
                state=CASE
                    WHEN state='generating' THEN 'generation_unknown'
                    WHEN state='listing' THEN 'export_failed'
                    ELSE 'generated' END,
                error_code=CASE WHEN state='listing' THEN 'E_LIST_TIMEOUT' ELSE error_code END,
                lease_token=NULL,lease_until=NULL,updated=?
                WHERE state IN ('generating','downloading','listing','projecting','writing')
                  AND lease_until IS NOT NULL AND lease_until<=?{purpose_sql}''', params)
            return cursor.rowcount

    def recover_startup(self, *, now=None):
        """进程启动时收敛上一个进程遗留的在途任务（daemon 线程已随进程死亡）。

        与 ``recover`` 的区别：不要求租约过期。桌面应用单实例运行，启动即证明旧线程
        已不存在；未收敛会让同一选择永久命中“活跃但无人推进”的任务。
        多实例共享同一作业库时不应调用本方法（会误杀另一实例的活跃任务）。
        """
        timestamp = _now(now)
        with self._transaction() as conn:
            cursor = conn.execute(
                '''UPDATE ewo_export_jobs SET
                state=CASE
                    WHEN cancel_requested=1 THEN 'cancelled'
                    WHEN state='listing' THEN 'export_failed'
                    WHEN state='generating' THEN 'generation_unknown'
                    ELSE 'generated' END,
                error_code=CASE
                    WHEN cancel_requested=0 AND state='listing' THEN 'E_LIST_TIMEOUT'
                    ELSE error_code END,
                lease_token=NULL,lease_until=NULL,updated=?
                WHERE state IN ('listing','generating','downloading','projecting','writing')''',
                (timestamp,),
            )
            return cursor.rowcount

    def list_jobs(self, limit=50):
        with self._transaction() as conn:
            rows = conn.execute(
                'SELECT * FROM ewo_export_jobs ORDER BY created DESC LIMIT ?',
                (max(1, min(limit, 200)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_job(self, job_id: str) -> dict | None:
        with self._transaction() as conn:
            row = conn.execute(
                'SELECT * FROM ewo_export_jobs WHERE id=?', (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def count_active_jobs(self, *, purpose=None) -> int:
        """活跃任务数；``purpose`` 用于给单个子系统设并发上限（默认全部）。"""
        purpose_sql = ' AND purpose=?' if purpose else ''
        params: tuple[object, ...] = (purpose,) if purpose else ()
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM ewo_export_jobs WHERE state IN {_ACTIVE_SQL}{purpose_sql}",
                params,
            ).fetchone()
            return int(row[0]) if row else 0

    #: `decide_retry` 的三类决策；调用方据此分流，禁止自行推断可重试性。
    RETRY_NEW_JOB = 'new_job'
    RETRY_RESUME_DOWNLOAD = 'resume_download'
    RETRY_FORBIDDEN = 'forbidden'

    def decide_retry(self, job_id, scope=None):
        """Return the only safe retry decision for a job (business red line).

        - ``generation_unknown``: the server may already have produced the export;
          retrying would re-issue a non-idempotent generation. Never allowed.
        - ``generated`` / ``downloading``: the file reference exists; resume download.
        - ``interrupted`` / ``failed``: only resume when a file reference was persisted;
          otherwise the generation outcome is unprovable, so a new job must be
          requested explicitly by the user (never auto-reissued).
        - ``cancelled``: the user cancelled; never re-issue automatically.
        - ``export_failed``: only a failure before generation (stage=listing) is retryable.
        """
        with self._transaction() as conn:
            if scope:
                row = self._row(conn, job_id, scope)
            else:
                row = conn.execute(
                    'SELECT * FROM ewo_export_jobs WHERE id=?', (job_id,)
                ).fetchone()
                if row is None:
                    raise ExportJobConflict('Export job unavailable')
            failure = conn.execute(
                'SELECT stage FROM ewo_export_failures WHERE job_id=?', (job_id,)
            ).fetchone()
        state = row['state']
        stage = failure['stage'] if failure else None
        if state == 'generation_unknown':
            return self.RETRY_FORBIDDEN
        if state in ('generated', 'downloading'):
            return self.RETRY_RESUME_DOWNLOAD
        if state in ('interrupted', 'failed'):
            return (
                self.RETRY_RESUME_DOWNLOAD if row['file_id'] else self.RETRY_FORBIDDEN
            )
        if state == 'export_failed':
            return self.RETRY_NEW_JOB if stage == 'listing' else self.RETRY_FORBIDDEN
        return self.RETRY_FORBIDDEN

    def cancel(self, job_id, scope=None, *, now=None):
        """Request cancellation without ever returning a job to a retryable state.

        ``queued``: nothing was sent upstream, so the job can go to ``cancelled``.
        ``generating`` / ``downloading``: the request may already be in flight; only a
        ``cancel_requested`` flag is set and the worker decides the outcome
        (``generation_unknown`` / ``generated``), so a later retry can never re-issue it.
        """
        timestamp = _now(now)
        with self._transaction() as conn:
            clause = "WHERE id=?"
            params = [job_id]
            if scope:
                clause += " AND scope=?"
                params.append(scope)
            row = conn.execute(f'SELECT * FROM ewo_export_jobs {clause}', params).fetchone()
            if row is None:
                return False
            if row['state'] == 'queued':
                conn.execute(
                    '''UPDATE ewo_export_jobs SET state='cancelled',cancel_requested=1,
                       lease_token=NULL,lease_until=NULL,updated=? WHERE id=?''',
                    (timestamp, job_id),
                )
                return True
            if row['state'] in ('generating', 'downloading'):
                conn.execute(
                    'UPDATE ewo_export_jobs SET cancel_requested=1,updated=? WHERE id=?',
                    (timestamp, job_id),
                )
                return True
            return False

    def quiesce(self, *, for_rollback=False, now=None):
        """回滚静默化：部署旧版本前把在途任务冻结到旧代码不会重发的状态。

        默认模式（新代码内部排空使用）：
        - generating → generation_unknown；queued/listing → cancelled；
        - downloading/projecting/writing → generated（保留下载可续）。

        ``for_rollback=True``（部署旧版本前必须使用）更严格：
        - 仍有未过期租约时直接拒绝（先停 worker）；
        - generated 也转 generation_unknown（旧代码续下载失败会变 failed，旧重试随后重建 = 重发）；
        - downloading/projecting/writing 转 generation_unknown（同上，不给旧代码下载机会）；
        - interrupted/failed 一律转 abandoned（旧重试接受这两个名字，等于允许重发）。
        """
        timestamp = _now(now)
        with self._transaction() as conn:
            counts = {}
            if for_rollback:
                live = conn.execute(
                    f'''SELECT COUNT(*) FROM ewo_export_jobs
                        WHERE state IN {_ACTIVE_SQL}
                          AND lease_until IS NOT NULL AND lease_until > ?''',
                    (timestamp,),
                ).fetchone()[0]
                if live:
                    raise ExportJobConflict(
                        f'{int(live)} job(s) still hold a live lease; stop workers/quiesce again later'
                    )
                cursor = conn.execute(
                    '''UPDATE ewo_export_jobs SET state='generation_unknown',
                       lease_token=NULL,lease_until=NULL,updated=?
                       WHERE state IN ('generating','generated','downloading',
                                       'projecting','writing')''',
                    (timestamp,),
                )
                counts['to_generation_unknown'] = cursor.rowcount
                cursor = conn.execute(
                    '''UPDATE ewo_export_jobs SET state='cancelled',cancel_requested=1,
                       lease_token=NULL,lease_until=NULL,updated=?
                       WHERE state IN ('queued','listing')''',
                    (timestamp,),
                )
                counts['to_cancelled'] = cursor.rowcount
                cursor = conn.execute(
                    '''UPDATE ewo_export_jobs SET state='abandoned',
                       lease_token=NULL,lease_until=NULL,updated=?
                       WHERE state IN ('interrupted','failed')''',
                    (timestamp,),
                )
                counts['legacy_retryable_to_abandoned'] = cursor.rowcount
            else:
                cursor = conn.execute(
                    '''UPDATE ewo_export_jobs SET state='generation_unknown',
                       lease_token=NULL,lease_until=NULL,updated=? WHERE state='generating' ''',
                    (timestamp,),
                )
                counts['generating'] = cursor.rowcount
                cursor = conn.execute(
                    '''UPDATE ewo_export_jobs SET state='cancelled',cancel_requested=1,
                       lease_token=NULL,lease_until=NULL,updated=?
                       WHERE state IN ('queued','listing')''',
                    (timestamp,),
                )
                counts['queued_or_listing'] = cursor.rowcount
                cursor = conn.execute(
                    '''UPDATE ewo_export_jobs SET state='generated',
                       lease_token=NULL,lease_until=NULL,updated=?
                       WHERE state IN ('downloading','projecting','writing')''',
                    (timestamp,),
                )
                counts['downloading_projecting_writing'] = cursor.rowcount
            remaining = conn.execute(
                f"SELECT COUNT(*) FROM ewo_export_jobs WHERE state IN {_ACTIVE_SQL}"
            ).fetchone()[0]
            counts['remaining_active'] = int(remaining)
            return counts
