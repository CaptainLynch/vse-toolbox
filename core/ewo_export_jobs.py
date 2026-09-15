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
            conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS ewo_export_jobs_active
                ON ewo_export_jobs(scope, selection_hash)
                WHERE state IN ('queued','generating','generation_unknown','generated','downloading')''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ewo_export_data (
                job_id TEXT PRIMARY KEY, context TEXT NOT NULL, snapshot TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ewo_export_failures (
                job_id TEXT PRIMARY KEY, stage TEXT NOT NULL
            )''')

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

    def create(self, scope, item_ids, *, context=None, now=None):
        if not isinstance(scope, str) or not scope.strip() or len(scope) > 256:
            raise ValueError('Invalid source scope')
        if not isinstance(item_ids, (list, tuple)) or not 1 <= len(item_ids) <= 5000:
            raise ValueError('Invalid selection size')
        ids = sorted(_reference(value) for value in item_ids)
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate source item reference')
        encoded = json.dumps(ids, separators=(',', ':'))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        timestamp = _now(now)
        with self._transaction() as conn:
            row = conn.execute('''SELECT * FROM ewo_export_jobs WHERE scope=? AND selection_hash=?
                AND state IN ('queued','generating','generation_unknown','generated','downloading')''',
                               (scope, digest)).fetchone()
            if row is None:
                job_id = uuid.uuid4().hex
                conn.execute('''INSERT INTO ewo_export_jobs
                    (id,scope,selection_hash,item_ids,state,created,updated) VALUES (?,?,?,?,'queued',?,?)''',
                             (job_id, scope, digest, encoded, timestamp, timestamp))
                conn.execute('INSERT INTO ewo_export_data(job_id,context) VALUES (?,?)',
                             (job_id, json.dumps(context or {}, ensure_ascii=False, allow_nan=False)))
                row = conn.execute('SELECT * FROM ewo_export_jobs WHERE id=?', (job_id,)).fetchone()
            return dict(row)

    def data(self, job_id, scope):
        with self._transaction() as conn:
            self._row(conn, job_id, scope)
            row = conn.execute('SELECT * FROM ewo_export_data WHERE job_id=?', (job_id,)).fetchone()
            if row is None:
                raise ExportJobConflict('Export context unavailable')
            return json.loads(row['context']), json.loads(row['snapshot']) if row['snapshot'] else None

    def read(self, job_id, scope):
        with self._transaction() as conn:
            job = dict(self._row(conn, job_id, scope))
            row = conn.execute('SELECT * FROM ewo_export_data WHERE job_id=?', (job_id,)).fetchone()
            if row is None:
                raise ExportJobConflict('Export context unavailable')
            error = conn.execute('SELECT stage FROM ewo_export_failures WHERE job_id=?', (job_id,)).fetchone()
            return (job, json.loads(row['context']), json.loads(row['snapshot']) if row['snapshot'] else None,
                    error['stage'] if error else None)

    def latest(self, scope, query_signature):
        with self._transaction() as conn:
            rows = conn.execute('''SELECT j.id,d.context FROM ewo_export_jobs j
                JOIN ewo_export_data d ON d.job_id=j.id WHERE j.scope=? ORDER BY j.created DESC''', (scope,))
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
            if row['state'] not in ('queued', 'generated'):
                raise ExportJobConflict('Export job cannot be claimed')
            state = 'generating' if row['state'] == 'queued' else 'downloading'
            conn.execute('''UPDATE ewo_export_jobs SET state=?,lease_token=?,lease_until=?,updated=? WHERE id=?''',
                         (state, uuid.uuid4().hex, timestamp + lease_seconds, timestamp, job_id))
            return dict(self._row(conn, job_id, scope))

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
        return self._finish(job_id, scope, lease_token, 'generating', 'generated',
                            'file_id', _reference(file_id), now)

    def parsed(self, job_id, scope, lease_token, snapshot_ref, *, now=None):
        if not isinstance(snapshot_ref, str) or not snapshot_ref or len(snapshot_ref) > 256:
            raise ValueError('Invalid snapshot reference')
        return self._finish(job_id, scope, lease_token, 'downloading', 'parsed',
                            'snapshot_ref', snapshot_ref, now)

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

    def recover(self, *, now=None):
        timestamp = _now(now)
        with self._transaction() as conn:
            cursor = conn.execute('''UPDATE ewo_export_jobs SET
                state=CASE WHEN state='generating' THEN 'generation_unknown' ELSE 'generated' END,
                lease_token=NULL,lease_until=NULL,updated=?
                WHERE state IN ('generating','downloading') AND lease_until<=?''', (timestamp, timestamp))
            return cursor.rowcount
