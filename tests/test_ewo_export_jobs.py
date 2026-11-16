"""Behavioral contract for durable EWO generation ownership."""
import sqlite3

import pytest

from core.ewo_export_jobs import EWOExportJobs, ExportJobConflict


def test_generation_claim_is_exclusive_and_unknown_is_not_retryable(tmp_path):
    path = tmp_path / 'jobs.db'
    a, b = EWOExportJobs(path), EWOExportJobs(path)
    job = a.create('scope-a', ['A' * 32], now=10)
    claimed = a.claim(job['id'], 'scope-a', now=11, lease_seconds=10)
    with pytest.raises(ExportJobConflict):
        b.claim(job['id'], 'scope-a', now=12)
    assert b.recover(now=22) == 1
    assert a.get(job['id'], 'scope-a')['state'] == 'generation_unknown'
    with pytest.raises(ExportJobConflict):
        a.claim(job['id'], 'scope-a', now=23)
    with pytest.raises(ExportJobConflict):
        a.generated(job['id'], 'scope-a', claimed['lease_token'], 'B' * 32, now=23)


def test_file_reference_recovery_never_regenerates(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=10)
    run = a.claim(job['id'], 'scope-a', now=11)
    a.generated(job['id'], 'scope-a', run['lease_token'], 'B' * 32, now=12)
    download = a.claim(job['id'], 'scope-a', now=13, lease_seconds=10)
    assert download['state'] == 'downloading'
    assert download['file_id'] == 'B' * 32
    a.recover(now=24)
    assert a.get(job['id'], 'scope-a')['state'] == 'generated'
    assert a.claim(job['id'], 'scope-a', now=25)['state'] == 'downloading'


def test_scope_and_lease_are_required_for_completion(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=10)
    with pytest.raises(ExportJobConflict):
        a.get(job['id'], 'scope-b')
    run = a.claim(job['id'], 'scope-a', now=11)
    with pytest.raises(ExportJobConflict):
        a.generated(job['id'], 'scope-a', 'wrong', 'B' * 32, now=12)
    a.generated(job['id'], 'scope-a', run['lease_token'], 'B' * 32, now=12)
    download = a.claim(job['id'], 'scope-a', now=13)
    a.parsed(job['id'], 'scope-a', download['lease_token'], 'snapshot-1', now=14)
    assert a.get(job['id'], 'scope-a')['snapshot_ref'] == 'snapshot-1'
    with pytest.raises(ExportJobConflict):
        a.claim(job['id'], 'scope-a', now=15)


def test_active_input_deduplicates_and_records_no_auth_material(tmp_path):
    path = tmp_path / 'jobs.db'
    a = EWOExportJobs(path)
    first = a.create('scope-a', ['A' * 32, 'B' * 32], now=10)
    second = a.create('scope-a', ['B' * 32, 'A' * 32], now=11)
    assert first['id'] == second['id']
    assert a.create('scope-b', ['A' * 32, 'B' * 32], now=12)['id'] != first['id']
    with sqlite3.connect(path) as c:
        columns = [row[1] for row in c.execute('PRAGMA table_info(ewo_export_jobs)')]
    assert not {'password', 'cookie', 'download_token', 'headers'} & set(columns)


@pytest.mark.parametrize('ids', [[], ['bad'], ['A' * 32, 'A' * 32], ['A' * 32] * 5001])
def test_rejects_invalid_selection(tmp_path, ids):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    with pytest.raises(ValueError):
        a.create('scope-a', ids)


# ── 取消红线：任何取消都不得把任务送回“可重试/可重新生成”的状态 ──────────────

def test_cancelling_queued_job_is_terminal_not_retryable(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=10)
    assert a.cancel(job['id'], 'scope-a', now=11) is True
    row = a.get(job['id'], 'scope-a')
    assert row['state'] == 'cancelled'
    assert row['cancel_requested'] == 1
    assert a.decide_retry(job['id']) == a.RETRY_FORBIDDEN
    with pytest.raises(ExportJobConflict):
        a.claim(job['id'], 'scope-a', now=12)
    # 二次取消不再受理
    assert a.cancel(job['id'], 'scope-a', now=13) is False


def test_cancelling_generating_job_never_returns_a_retryable_state(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=10)
    run = a.claim(job['id'], 'scope-a', now=11, lease_seconds=10)
    assert a.cancel(job['id'], 'scope-a', now=12) is True
    row = a.get(job['id'], 'scope-a')
    assert row['state'] == 'generating'
    assert row['cancel_requested'] == 1
    assert a.decide_retry(job['id']) == a.RETRY_FORBIDDEN
    # 生成结果返回时才发现已请求取消：直接落 cancelled（保留 file_id），不得进入 active。
    finished = a.generated(job['id'], 'scope-a', run['lease_token'], 'B' * 32, now=13)
    assert finished['state'] == 'cancelled'
    assert finished['file_id'] == 'B' * 32
    assert a.decide_retry(job['id']) == a.RETRY_FORBIDDEN
    with pytest.raises(ExportJobConflict):
        a.claim(job['id'], 'scope-a', now=14)
    # 取消终态不占用 active 键：同一选择可以重新发起（由用户显式新建）。
    replacement = a.create('scope-a', ['A' * 32], now=15)
    assert replacement['id'] != job['id']
    assert replacement['state'] == 'queued'


def test_decide_retry_never_reissues_an_unprovable_generation(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    # generation_unknown → forbidden
    unknown = a.create('s1', ['A' * 32], now=1)
    run = a.claim(unknown['id'], 's1', now=2)
    a.interrupted(unknown['id'], 's1', run['lease_token'], now=3)
    assert a.get(unknown['id'], 's1')['state'] == 'generation_unknown'
    assert a.decide_retry(unknown['id']) == a.RETRY_FORBIDDEN
    # generated（file_id 已持久化）→ 只允许续下载
    generated = a.create('s2', ['B' * 32], now=10)
    run = a.claim(generated['id'], 's2', now=11)
    a.generated(generated['id'], 's2', run['lease_token'], 'C' * 32, now=12)
    assert a.decide_retry(generated['id']) == a.RETRY_RESUME_DOWNLOAD
    # 历史 interrupted 且无 file_id → forbidden（无法证明是否已生成）
    legacy = a.create('s3', ['D' * 32], now=20)
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='interrupted' WHERE id=?", (legacy['id'],))
    assert a.decide_retry(legacy['id']) == a.RETRY_FORBIDDEN
    # 历史 interrupted 但有 file_id → 续下载
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='interrupted',file_id=? WHERE id=?",
                  ('E' * 32, legacy['id']))
    assert a.decide_retry(legacy['id']) == a.RETRY_RESUME_DOWNLOAD
    # 旧 failed 状态同样按红线处理
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='failed',file_id=NULL WHERE id=?", (legacy['id'],))
    assert a.decide_retry(legacy['id']) == a.RETRY_FORBIDDEN


def test_export_failed_before_generation_may_be_retried(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    job = a.create('scope-a', ['A' * 32], now=1)
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='export_failed' WHERE id=?", (job['id'],))
        c.execute("INSERT OR REPLACE INTO ewo_export_failures(job_id,stage) VALUES (?,?)",
                  (job['id'], 'listing'))
    assert a.decide_retry(job['id']) == a.RETRY_NEW_JOB
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_failures SET stage='projecting' WHERE job_id=?", (job['id'],))
    assert a.decide_retry(job['id']) == a.RETRY_FORBIDDEN


def test_cancel_requested_column_is_added_to_existing_database(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE ewo_export_jobs (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, selection_hash TEXT NOT NULL,
            item_ids TEXT NOT NULL, state TEXT NOT NULL,
            file_id TEXT, snapshot_ref TEXT, lease_token TEXT, lease_until REAL,
            created REAL NOT NULL, updated REAL NOT NULL
        )''')
        c.execute("INSERT INTO ewo_export_jobs VALUES ('legacy-id','s','h','[\"A\"]','parsed',"
                  "NULL,'snap',NULL,NULL,1,1)")
    EWOExportJobs(path)
    with sqlite3.connect(path) as c:
        columns = {row[1] for row in c.execute('PRAGMA table_info(ewo_export_jobs)')}
        row = c.execute("SELECT state,cancel_requested FROM ewo_export_jobs").fetchone()
    assert 'cancel_requested' in columns
    assert row == ('parsed', 0)


# ── 批次 3：purpose 隔离、active 索引重建、recover/quiesce 静默化 ──────────────

def test_purpose_isolates_idempotency(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    enrichment = a.create('scope-a', ['A' * 32], now=10)
    export = a.create('scope-a', ['A' * 32], purpose='csv_export', now=11)
    assert enrichment['id'] != export['id']
    assert enrichment['purpose'] == 'enrichment'
    assert export['purpose'] == 'csv_export'
    # 同 purpose 同选择仍然幂等
    again = a.create('scope-a', ['A' * 32], purpose='csv_export', now=12)
    assert again['id'] == export['id']
    with pytest.raises(ValueError):
        a.create('scope-a', ['A' * 32], purpose='Bad Purpose!')


def test_migration_rebuilds_active_index_over_new_states_and_purpose(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE ewo_export_jobs (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, selection_hash TEXT NOT NULL,
            item_ids TEXT NOT NULL, state TEXT NOT NULL,
            file_id TEXT, snapshot_ref TEXT, lease_token TEXT, lease_until REAL,
            created REAL NOT NULL, updated REAL NOT NULL
        )''')
        c.execute("CREATE UNIQUE INDEX ewo_export_jobs_active ON ewo_export_jobs(scope, selection_hash) "
                  "WHERE state IN ('queued','generating','generation_unknown','generated','downloading')")
        c.execute("INSERT INTO ewo_export_jobs VALUES ('legacy-id','s','h','[\"A\"]','parsed',"
                  "NULL,NULL,NULL,NULL,1,1)")
    EWOExportJobs(path)
    with sqlite3.connect(path) as c:
        index_sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ewo_export_jobs_active'"
        ).fetchone()[0]
        purpose = c.execute("SELECT purpose FROM ewo_export_jobs WHERE id='legacy-id'").fetchone()[0]
    assert 'purpose' in index_sql
    assert 'projecting' in index_sql and 'writing' in index_sql
    assert purpose == 'enrichment'
    # 迁移幂等：再次打开不应重建或报错。
    EWOExportJobs(path)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT COUNT(*) FROM ewo_export_jobs").fetchone()[0] == 1


def test_duplicate_active_rows_block_the_migration_without_partial_schema(tmp_path):
    path = tmp_path / 'dup.db'
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE ewo_export_jobs (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, selection_hash TEXT NOT NULL,
            item_ids TEXT NOT NULL, state TEXT NOT NULL,
            file_id TEXT, snapshot_ref TEXT, lease_token TEXT, lease_until REAL,
            created REAL NOT NULL, updated REAL NOT NULL
        )''')
        for job_id in ('one', 'two'):
            c.execute("INSERT INTO ewo_export_jobs VALUES (?,?,?,?,?,NULL,NULL,NULL,NULL,1,1)",
                      (job_id, 's', 'h', '["A"]', 'queued'))
    with pytest.raises(ExportJobConflict):
        EWOExportJobs(path)
    with sqlite3.connect(path) as c:
        columns = {row[1] for row in c.execute('PRAGMA table_info(ewo_export_jobs)')}
        rows = c.execute("SELECT COUNT(*) FROM ewo_export_jobs").fetchone()[0]
    assert 'purpose' not in columns  # 迁移失败必须整体回滚，不留半套 schema
    assert rows == 2  # 重复行不被静默合并或删除


def test_recover_freezes_listing_and_resumes_downloading(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    listing = a.create('s1', ['A' * 32], now=1)
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='listing',lease_token='t',lease_until=5 WHERE id=?",
                  (listing['id'],))
    awaiting = a.create('s2', ['B' * 32], now=1)
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='listing',lease_token=NULL,lease_until=NULL WHERE id=?",
                  (awaiting['id'],))
    write = a.create('s3', ['C' * 32], now=1)
    with sqlite3.connect(tmp_path / 'jobs.db') as c:
        c.execute("UPDATE ewo_export_jobs SET state='writing',lease_token='t',lease_until=5 WHERE id=?",
                  (write['id'],))
    assert a.recover(now=10) == 2
    assert a.get(listing['id'], 's1')['state'] == 'export_failed'
    assert a.get(listing['id'], 's1')['error_code'] == 'E_LIST_TIMEOUT'
    assert a.get(awaiting['id'], 's2')['state'] == 'listing'  # 没有租约的行不被误伤
    assert a.get(write['id'], 's3')['state'] == 'generated'


def test_quiesce_freezes_every_in_flight_state_before_rollback(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    ids = {}
    for index, key in enumerate(('generating', 'downloading', 'queued', 'listing', 'writing')):
        row = a.create(f's-{key}', [f'{index + 1:032X}'], now=1)
        ids[key] = row['id']
        with sqlite3.connect(tmp_path / 'jobs.db') as c:
            c.execute("UPDATE ewo_export_jobs SET state=? WHERE id=?", (key, row['id']))
    counts = a.quiesce(now=100)
    assert counts['generating'] == 1
    assert counts['queued_or_listing'] == 2
    assert counts['downloading_projecting_writing'] == 2
    assert a.get(ids['generating'], 's-generating')['state'] == 'generation_unknown'
    assert a.get(ids['downloading'], 's-downloading')['state'] == 'generated'
    assert a.get(ids['queued'], 's-queued')['state'] == 'cancelled'
    assert a.get(ids['listing'], 's-listing')['state'] == 'cancelled'
    assert a.get(ids['writing'], 's-writing')['state'] == 'generated'
    # 占键的只剩 generation_unknown(1) 与 generated(2)：两者在旧代码里都只能人工核查或续下载。
    assert counts['remaining_active'] == 3


def test_quiesced_database_cannot_be_reissued_by_legacy_rules(tmp_path):
    """回滚兼容（P0-3）：旧版本的取消/重试/恢复条件在静默化后不再命中任何行。"""
    a = EWOExportJobs(tmp_path / 'jobs.db')
    jobs = {}
    for index, state in enumerate(
        ('generating', 'downloading', 'interrupted', 'failed', 'queued', 'generated')
    ):
        job = a.create(f's-{state}', [f'{index + 1:032X}'], now=1)
        jobs[state] = job['id']
        with sqlite3.connect(tmp_path / 'jobs.db') as conn:
            conn.execute('UPDATE ewo_export_jobs SET state=? WHERE id=?', (state, job['id']))
            if state in ('generating', 'downloading'):
                conn.execute('UPDATE ewo_export_jobs SET lease_until=2 WHERE id=?', (job['id'],))
    changed = a.quiesce(for_rollback=True, now=100)
    assert changed['to_generation_unknown'] == 3
    assert changed['to_cancelled'] == 1
    assert changed['legacy_retryable_to_abandoned'] == 2
    with sqlite3.connect(tmp_path / 'jobs.db') as conn:
        legacy_retry = conn.execute(
            "SELECT COUNT(*) FROM ewo_export_jobs WHERE state IN ('interrupted','failed')"
        ).fetchone()[0]
        legacy_cancel = conn.execute(
            "SELECT COUNT(*) FROM ewo_export_jobs WHERE state IN ('queued','generating','downloading')"
        ).fetchone()[0]
        legacy_recover = conn.execute(
            "SELECT COUNT(*) FROM ewo_export_jobs WHERE state IN ('generating','downloading')"
        ).fetchone()[0]
    # 旧版本的三条入口（重试接受 interrupted/failed、取消白名单、recover 谓词）全部空集。
    assert (legacy_retry, legacy_cancel, legacy_recover) == (0, 0, 0)
    for job_id in jobs.values():
        assert a.decide_retry(job_id) == a.RETRY_FORBIDDEN


def test_count_active_jobs_can_be_scoped_by_purpose(tmp_path):
    """并发上限按子系统计：CSV 导出的上限不能被只读面板的在途任务占满。"""
    a = EWOExportJobs(tmp_path / 'jobs.db')
    a.create('s1', ['A' * 32], now=1)
    a.create('s2', ['B' * 32], purpose='csv_export', now=1)
    a.create('s3', ['C' * 32], purpose='csv_export', now=1)
    assert a.count_active_jobs() == 3
    assert a.count_active_jobs(purpose='csv_export') == 2
    assert a.count_active_jobs(purpose='enrichment') == 1


def test_create_reports_whether_it_created_a_new_job(tmp_path):
    """路由据此只在真正新建时 spawn 执行器，避免同一选择两条线程。"""
    a = EWOExportJobs(tmp_path / 'jobs.db')
    first = a.create('s', ['A' * 32], now=1)
    again = a.create('s', ['A' * 32], now=2)
    assert first.get('is_new') is True
    assert 'is_new' not in again
    assert again['id'] == first['id']
    assert a.cancel(first['id'], 's', now=3) is True
    third = a.create('s', ['A' * 32], now=4)
    assert third.get('is_new') is True
    assert third['id'] != first['id']


def test_recover_is_scoped_to_one_purpose(tmp_path):
    """增强导表收敛在途任务时，绝不能把正在运行的 CSV 导出改成 generation_unknown。"""
    a = EWOExportJobs(tmp_path / 'jobs.db')
    enrichment = a.create('s1', ['A' * 32], now=1)
    export = a.create('s2', ['B' * 32], purpose='csv_export', now=1)
    with sqlite3.connect(tmp_path / 'jobs.db') as conn:
        conn.execute(
            "UPDATE ewo_export_jobs SET state='generating',lease_token='t',lease_until=2 "
            "WHERE id IN (?,?)", (enrichment['id'], export['id']))
    assert a.recover(purpose='enrichment', now=10) == 1
    assert a.get(enrichment['id'], 's1')['state'] == 'generation_unknown'
    assert a.get(export['id'], 's2')['state'] == 'generating'


def test_recover_startup_converges_unexpired_inflight_jobs(tmp_path):
    """进程启动即证明旧 daemon 线程已死：未过期租约也要收敛，且取消请求落 cancelled。"""
    a = EWOExportJobs(tmp_path / 'jobs.db')
    ids = {}
    for index, state in enumerate(('listing', 'generating', 'downloading')):
        job = a.create(f's-{state}', [f'{index + 1:032X}'], now=1)
        ids[state] = job['id']
        with sqlite3.connect(tmp_path / 'jobs.db') as conn:
            conn.execute(
                "UPDATE ewo_export_jobs SET state=?,lease_token='t',lease_until=999999 WHERE id=?",
                (state, job['id']))
    cancelling = a.create('s-cancel', ['F' * 32], now=1)
    with sqlite3.connect(tmp_path / 'jobs.db') as conn:
        conn.execute(
            "UPDATE ewo_export_jobs SET state='generating',cancel_requested=1,"
            "lease_token='t',lease_until=999999 WHERE id=?", (cancelling['id'],))
    assert a.recover_startup(now=10) == 4
    assert a.get(ids['listing'], 's-listing')['state'] == 'export_failed'
    assert a.get(ids['listing'], 's-listing')['error_code'] == 'E_LIST_TIMEOUT'
    assert a.get(ids['generating'], 's-generating')['state'] == 'generation_unknown'
    assert a.get(ids['downloading'], 's-downloading')['state'] == 'generated'
    assert a.get(cancelling['id'], 's-cancel')['state'] == 'cancelled'


def test_quiesce_for_rollback_refuses_live_lease_and_freezes_legacy_states(tmp_path):
    a = EWOExportJobs(tmp_path / 'jobs.db')
    running = a.create('s-run', ['A' * 32], now=1)
    a.claim(running['id'], 's-run', now=2, lease_seconds=1800)
    with pytest.raises(ExportJobConflict):
        a.quiesce(for_rollback=True, now=3)

    # 停掉租约后，回滚模式必须把所有“旧代码可重试/可续”的行冻结到人工状态。
    with sqlite3.connect(tmp_path / 'jobs.db') as conn:
        conn.execute('UPDATE ewo_export_jobs SET lease_until=2 WHERE id=?', (running['id'],))
    rows = {}
    for index, state in enumerate(('generated', 'interrupted', 'failed', 'downloading')):
        row = a.create(f's-{state}', [f'{index + 10:032X}'], now=1)
        rows[state] = row['id']
        with sqlite3.connect(tmp_path / 'jobs.db') as conn:
            conn.execute('UPDATE ewo_export_jobs SET state=? WHERE id=?', (state, row['id']))
    with sqlite3.connect(tmp_path / 'jobs.db') as conn:
        conn.execute("UPDATE ewo_export_jobs SET lease_until=? WHERE state IN ('generating','downloading')", (2,))
    counts = a.quiesce(for_rollback=True, now=100)
    assert counts['legacy_retryable_to_abandoned'] == 2
    assert a.get(rows['generated'], 's-generated')['state'] == 'generation_unknown'
    assert a.get(rows['interrupted'], 's-interrupted')['state'] == 'abandoned'
    assert a.get(rows['failed'], 's-failed')['state'] == 'abandoned'
    assert a.get(rows['downloading'], 's-downloading')['state'] == 'generation_unknown'
    # 旧代码只认识 generation_unknown（人工核查），其余名字它一律不认 → 不会重发。
    assert a.get(running['id'], 's-run')['state'] == 'generation_unknown'
    assert a.decide_retry(running['id']) == a.RETRY_FORBIDDEN
    assert a.decide_retry(rows['interrupted']) == a.RETRY_FORBIDDEN
