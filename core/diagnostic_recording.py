"""Bounded, local, cross-process diagnostic recording; never stores raw payloads.

SQLite serializes writers and quotas. Each event uses a short transaction with
a 50ms lock timeout; failures drop diagnostics, never change business results.
Context state is request-local, not a process-global active trace.
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import hmac
import io
import inspect
from itertools import islice
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import is_dataclass, fields
from urllib.parse import urlsplit


_recorder = contextvars.ContextVar('diagnostic_recorder', default=None)
_trace = contextvars.ContextVar('diagnostic_trace', default='')
_span = contextvars.ContextVar('diagnostic_span', default='')
_parent = contextvars.ContextVar('diagnostic_parent', default='')
_recording = contextvars.ContextVar('diagnostic_recording', default='')
_ID = re.compile(r'^[a-f0-9]{32}$')
_SECRET = re.compile(r'password|token|cookie|authorization|secret|credential|session|csrf|private.?key|api.?key', re.I)
_NUMBER_FIELDS = set('status_code elapsed_ms page page_size attempt timeout content_length record_count total pages accumulated_count unique_count duplicate_count current_page estimated_pages bytes_written line column status code apiCode upstreamHttpStatus run_id binding_id count row_count byte_count updated_count failed_count skipped_count success_count'.split())
_TEXT_FIELDS = set('stage method page_type content_type stop_reason validation exception_type source operation outcome run_state state status error_type trigger_type'.split())
_VALUES = set('GET POST PUT PATCH DELETE HEAD OPTIONS request response request-start request-end exception failed failure success succeeded skipped partial interrupted cancelled running pending completed needs_attention conflict busy query export auth login authenticate authenticated anonymous password browser tdc aras data_model sor aface a_face ewo paa ncr ncr_progress ncr_detail http api-validation export-validation contract-validation request-validation parse pagination cache hit miss commit rollback start end retry timeout manual scheduled attention not_modified valid invalid application/json application/xml text/xml text/html application/octet-stream application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'.split())
_INPUT_KEYS = set('filters query params project project_id projectId projectNo projectName project_model department section applicant report_type form_key source_type job_key page page_size pageSize limit offset start end date_start date_end submit_start submit_end auth_mode base_url url path origin serial_number model_number part_number incident trigger_type output_format format status'.split())
_INPUT_KEYS.update('run_id job_id binding_id deliverable_id max_pages max_records source report root_id output_subdir file_name'.split())
_INPUT_KEYS.update('projectID project_no project_name application_start application_end startusername requestDateStart requestDateEnd projectModel superDepartment partNumber incident rows items content filters result state count'.split())
_default = None

# Fixed vocabulary from the production adapters. Unknown upstream strings remain fingerprints.
_VALUES.update('''aras-session-init credential-validation ecm-auth-discovery login-form-ready
app.js diagnostics.js unknown
ecm-credentials credentials-redirect authorization-code-received ecm-token oidc-token-received
ecm-userinfo userinfo-received ecm-advalidate innovator-md5-received ecm-innovator-token
innovator-token-received ecm-validate-user ecm-oidc-discovery oidc-metadata-received
oidc-metadata-fallback origin-validation callback-validation oidc-parameter-generation
auth-discovery auth-credentials oidc-token tdc-session-init tdc-token tdc-session-established
auth-verify tdc-entry tdc-cookie-migration entry-observed entry-http-observed
entry-redirect-not-followed entry-redirect-limit cookie-migration-performed cookie-migration-skipped
download-token prewarm soap-ApplyItem soap-ApplyMethod parse-json single_page
status-validation content-validation rejected-login-html rejected-content-type invalid-json
json-not-object api-error json-ok rejected-json-response rejected-xlsx-signature
content-type+xlsx-pk-ok max_pages max_records empty_page reported_pages short_page continue
sync_now no_change needs-attention sor_projects approved rejected succeeded_with_warnings'''.split())
_PATHS = set('''/tpc/dataAdmin/dataModelDesign/index /uwf/procuwfpe3ddigitalmodeldesignreview/list
/uwf/procuwfpe3ddigitalmodeldesignreview/export /tpc/dataAdmin/intelligent/sor/index
/sp/carTypeProject/list /sp/sor/sorPage /sp/sor/export /tpc/dataAdmin/intelligent/ots2/index
/tpc/ /auth/oauth/token /uwf/user/info /Server/InnovatorServer.aspx /Client/default.aspx
/Server/AuthenticationBroker.asmx/GetFileDownloadToken /auth/realms/common/protocol/openid-connect/auth
/auth/realms/common/protocol/openid-connect/token'''.split())
_FIELDS = set('code msg message error data success status rows items total pages records current size id projectId projectNo projectName'.split())
_NUMBER_FIELDS.update({'api_code', 'completed_pages'})
_NUMBER_FIELDS.add('job_id')
_TEXT_FIELDS.add('final_state')
# NCR 披露事件（部门过滤 / 歧义表头标签）的载荷必须可读：键走白名单、文本值走
# 闭集词表。否则 emit 的事件名留存、data 却是 {}，等于"记录了但读不到"。
_NUMBER_FIELDS.update({'kept_count', 'dropped_count'})
_TEXT_FIELDS.update({'report_type', 'remedy'})
_VALUES.add('reproject_from_archived_workbook')


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and abs(value) < 1e15


def _name(value):
    text = str(value)
    return text[:100] if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,99}', text) else '[filtered]'


def _fingerprint(value, salt):
    return 'ref:' + hmac.new(salt.encode(), str(value)[:8192].encode('utf-8', errors='replace'), hashlib.sha256).hexdigest()[:16]


def _shape(value, salt, depth=0):
    if depth > 3:
        return '[depth-limit]'
    if isinstance(value, dict):
        return {(str(k) if str(k) in _INPUT_KEYS else _fingerprint(k, salt)):
                _shape(v, salt, depth + 1) for k, v in islice(value.items(), 32) if not _SECRET.search(str(k))}
    if isinstance(value, (tuple, list)):
        return {'length': len(value), 'sample_shapes': [_shape(v, salt, depth + 1) for v in value[:3]]}
    if value is None or isinstance(value, bool):
        return value
    if _numeric(value):
        return value
    if isinstance(value, str):
        return {'type': 'string', 'length': len(value), 'ref': _fingerprint(value, salt)}
    return {'type': _name(type(value).__name__)}


def safe_metadata(data, salt):
    """Project untrusted data, not a best-effort regex scrub of raw strings."""
    result = {}
    if not isinstance(data, dict):
        return result
    for key, value in islice(data.items(), 64):
        if key in _NUMBER_FIELDS and _numeric(value):
            result[key] = value
        elif key in _TEXT_FIELDS and isinstance(value, str):
            result[key] = value if value in _VALUES else _fingerprint(value, salt)
        elif key in {'ok', 'hit', 'reasonAvailable', 'cancelled'} and isinstance(value, bool):
            result[key] = value
        elif key in {'response_fields', 'json_fields', 'responseFields'} and isinstance(value, (list, tuple)):
            result[key] = [v if isinstance(v, str) and v in _FIELDS else _fingerprint(v, salt) for v in value[:64]]
        elif key in {'inputs', 'query', 'result_shape'}:
            result[key] = _shape(value, salt)
        elif key in {'url', 'path'} and isinstance(value, str):
            path = urlsplit(value).path
            result['path'] = path if path in _PATHS else _fingerprint(path, salt)
        elif key in {'request_id', 'action_id', 'resource_id', 'requestId'} and isinstance(value, str):
            result[key] = _fingerprint(value, salt)
    return result


class Recorder:
    def __init__(self, root, *, clock=time.time, max_bytes=100 * 1024 * 1024,
                 retention_bytes=500 * 1024 * 1024, retention_days=7):
        self.root = Path(root)
        self.path = self.root / 'recordings.sqlite3'
        self.clock = clock
        self.max_bytes = max_bytes
        self.retention_bytes = retention_bytes
        self.retention_days = retention_days
        self.dropped = 0
        self._lock = threading.RLock()
        self._keeper = None
        self._build = None

    def _connect(self, create=False):
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        elif not self.path.is_file():
            raise FileNotFoundError('No diagnostic recordings')
        conn = sqlite3.connect(str(self.path), timeout=0.05)
        conn.row_factory = sqlite3.Row
        if create:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS recordings (
                  id TEXT PRIMARY KEY, created REAL, expires REAL, stopped REAL,
                  reason TEXT, size INTEGER DEFAULT 0, salt TEXT, environment TEXT);
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY, recording TEXT, payload TEXT, size INTEGER);
                CREATE INDEX IF NOT EXISTS events_recording ON events(recording);
            ''')
        return conn

    @contextmanager
    def _db(self, create=False, serialize=False):
        if serialize:
            self._lock.acquire()
        try:
            conn = self._connect(create)
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
        finally:
            if serialize:
                self._lock.release()

    def _expire(self, conn):
        conn.execute("UPDATE recordings SET stopped=?,reason='expired' WHERE stopped IS NULL AND expires<=?", (self.clock(), self.clock()))

    def start(self, duration=1800):
        if not _numeric(duration) or not 1 <= duration <= 1800:
            raise ValueError('duration must be between 1 and 1800 seconds')
        now = self.clock()
        identity = uuid.uuid4().hex
        with self._db(create=True) as conn:
            if self._keeper is None:
                # Keep WAL open between short event transactions; closing the last
                # connection on every event otherwise forces repeated checkpoints.
                self._keeper = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.execute('BEGIN IMMEDIATE')
            self._expire(conn)
            active = conn.execute('SELECT id FROM recordings WHERE stopped IS NULL').fetchone()
            if active:
                raise ValueError('A recording is already active')
            rows = conn.execute('SELECT id,created,size FROM recordings ORDER BY created DESC').fetchall()
            used = 0
            for row in rows:
                used += row['size']
                if row['created'] < now - self.retention_days * 86400 or used > self.retention_bytes - self.max_bytes:
                    conn.execute('DELETE FROM events WHERE recording=?', (row['id'],))
                    conn.execute('DELETE FROM recordings WHERE id=?', (row['id'],))
            environment = {'python': platform.python_version(), 'os': platform.system(),
                           'os_release': platform.release(), 'architecture': platform.machine(),
                           'frozen': bool(getattr(sys, 'frozen', False)), 'build': build_identity(),
                           'proxy_configured': any(bool(os.environ.get(k)) for k in ('HTTP_PROXY', 'HTTPS_PROXY'))}
            conn.execute('INSERT INTO recordings(id,created,expires,salt,environment) VALUES(?,?,?,?,?)',
                         (identity, now, now + duration, secrets.token_hex(32), _dumps(environment)))
        return self.status()['latest']

    def status(self):
        try:
            with self._db() as conn:
                rows = conn.execute('SELECT id,created,expires,stopped,reason,size FROM recordings ORDER BY created DESC,rowid DESC LIMIT 20').fetchall()
                items = [dict(row) for row in rows]
                for row in items:
                    if row['stopped'] is None and row['expires'] <= self.clock():
                        row.update(stopped=row['expires'], reason='expired')
                active = next((row for row in items if row['stopped'] is None), None)
                return {'active': active is not None, 'latest': items[0] if items else None,
                        'recordings': items, 'dropped_in_process': self.dropped}
        except (OSError, sqlite3.Error):
            return {'active': False, 'latest': None, 'recordings': [], 'dropped_in_process': self.dropped}

    def active_id(self):
        state = self.status()
        return state['latest']['id'] if state['active'] else ''

    def stop(self):
        with self._db() as conn:
            self._expire(conn)
            conn.execute("UPDATE recordings SET stopped=?,reason='stopped' WHERE stopped IS NULL", (self.clock(),))
        return self.status()

    def emit(self, kind, data=None, *, name='', trace_id='', span_id='', parent_id='', recording_id='', exception=None):
        try:
            if self._build is None:
                self._build = build_identity()
            with self._db(serialize=True) as conn:
                conn.execute('BEGIN IMMEDIATE')
                self._expire(conn)
                row = conn.execute('SELECT * FROM recordings WHERE stopped IS NULL').fetchone()
                if row is None or (recording_id and row['id'] != recording_id):
                    return
                projected = safe_metadata(data or {}, row['salt'])
                if exception is not None:
                    projected.update(safe_metadata(vars(exception), row['salt']))
                    projected['exception_type'] = _name(type(exception).__name__)
                    projected['frames'] = []
                    projected['causes'] = []
                    chain = exception
                    seen = set()
                    while chain is not None and id(chain) not in seen and len(seen) < 5:
                        seen.add(id(chain))
                        cause_info = {'type': _name(type(chain).__name__)}
                        for field_name in ('errno', 'winerror', 'hresult'):
                            value = getattr(chain, field_name, None)
                            if _numeric(value):
                                cause_info[field_name] = value
                        projected['causes'].append(cause_info)
                        tb = chain.__traceback__
                        while tb is not None and len(projected['frames']) < 40:
                            projected['frames'].append({'file': _name(Path(tb.tb_frame.f_code.co_filename).name),
                                                        'function': _name(tb.tb_frame.f_code.co_name), 'line': tb.tb_lineno})
                            tb = tb.tb_next
                        chain = chain.__cause__ or (None if chain.__suppress_context__ else chain.__context__)
                event = {'kind': _name(kind), 'name': _name(name) if name else '',
                         'timestamp': self.clock(), 'process_id': os.getpid(),
                         'build': self._build,
                         'dropped_before_in_process': self.dropped,
                         'trace_id': trace_id if _ID.fullmatch(trace_id) else uuid.uuid4().hex,
                         'span_id': span_id if _ID.fullmatch(span_id) else '',
                         'parent_id': parent_id if _ID.fullmatch(parent_id) else '', 'data': projected}
                payload = _dumps(event)
                size = len(payload.encode('utf-8')) + 128
                if row['size'] + size > self.max_bytes:
                    conn.execute("UPDATE recordings SET stopped=?,reason='capacity' WHERE id=?", (self.clock(), row['id']))
                    return
                conn.execute('INSERT INTO events(recording,payload,size) VALUES(?,?,?)', (row['id'], payload, size))
                conn.execute('UPDATE recordings SET size=size+? WHERE id=?', (size, row['id']))
        except Exception:
            self.dropped += 1

    def export(self, identity):
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            raise ValueError('Invalid recording ID')
        with self._db() as conn:
            conn.execute('BEGIN')
            row = conn.execute('SELECT * FROM recordings WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise KeyError('Recording not found')
            row = dict(row)
            if row['stopped'] is None and row['expires'] <= self.clock():
                row.update(stopped=row['expires'], reason='expired')
            events = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM events WHERE recording=? ORDER BY seq', (identity,))]
        errors = [e for e in events if e['kind'] == 'exception']
        failures = [e for e in events if e['data'].get('ok') is False
                    or e['data'].get('status_code', 0) >= 400
                    or e['data'].get('final_state') in {'failed', 'needs_attention', 'interrupted'}
                    or (e['kind'] == 'result' and e['data'].get('outcome') in {'failed', 'needs_attention', 'interrupted'})]
        opened = {e['span_id']: e['name'] for e in events if e['kind'] == 'start'}
        for event in events:
            if event['kind'] == 'end':
                opened.pop(event['span_id'], None)
        manifest = {'schema_version': 1, 'id': identity, 'created': row['created'],
                    'expires': row['expires'], 'stopped': row['stopped'], 'reason': row['reason'],
                    'event_count': len(events), 'incomplete_spans': list(opened.values()),
                    'dropped_in_export_process': self.dropped,
                    'observed_drops_by_process': {str(pid): max(e.get('dropped_before_in_process', 0) for e in events if e['process_id'] == pid) for pid in {e['process_id'] for e in events}},
                    'limitations': ['Office/Excel Worker excluded', 'Upstream server internals unavailable',
                                    'No raw bodies, headers, exception messages, source lines or locals',
                                    'Strings fingerprinted; no automatic replay',
                                    'Abrupt exits/lock contention can lose events; per-process drop counters are not durable',
                                    'Snapshot export: running spans may be incomplete']}
        summary = ['# VSE 安全诊断报告', '', f'- 录制 ID: {identity}',
                   f'- 事件: {len(events)}；异常: {len(errors)}；未结束步骤: {len(opened)}',
                   f'- 停止原因: {row["reason"] or "仍在录制（本包为快照）"}', '',
                   '## 异常定位（不含异常消息和业务原文）']
        summary.extend(f'- {e["name"]}: {e["data"].get("exception_type", "")} trace={e["trace_id"]}' for e in errors[:100])
        summary += ['', '## 失败响应与业务结果']
        summary.extend(f'- {e["name"]}: {_dumps(e["data"])} trace={e["trace_id"]}' for e in failures[:100])
        summary += ['', '## 问题标记']
        summary.extend(f'- timestamp={e["timestamp"]}' for e in events if e['kind'] == 'mark')
        summary += ['', '## 证据边界', 'Office/Excel Worker 未纳入。上游内部不可见。字符串为同次录制内稳定指纹。',
                    '未结束步骤可能是仍在执行、进程退出、容量上限或事件丢失；不能仅凭缺少结束事件认定崩溃。']
        contents = {'summary.md': '\n'.join(summary).encode('utf-8'),
                    'environment.json': row['environment'].encode('utf-8'),
                    'events.jsonl': ('\n'.join(_dumps(e) for e in events) + '\n').encode('utf-8'),
                    'exceptions.json': _dumps(errors).encode('utf-8')}
        manifest['files'] = {name: {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value)} for name, value in contents.items()}
        contents['manifest.json'] = _dumps(manifest).encode('utf-8')
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, value in contents.items():
                archive.writestr(name, value)
        return output.getvalue()


def build_identity():
    digest = hashlib.sha256()
    if getattr(sys, 'frozen', False):
        with open(sys.executable, 'rb') as executable:
            for chunk in iter(lambda: executable.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    for name in ('web/static/app.js', 'web/static/diagnostics.js', 'core/diagnostic_recording.py'):
        path = root / name
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def default_recorder():
    global _default
    if _default is None:
        from core.runtime_paths import app_root
        _default = Recorder(app_root() / 'data' / 'diagnostics')
    return _default


@contextmanager
def recording_scope(recorder, trace_id=''):
    tokens = (_recorder.set(recorder), _trace.set(trace_id if _ID.fullmatch(trace_id) else uuid.uuid4().hex),
              _span.set(''), _recording.set(recorder.active_id()), _parent.set(''))
    try:
        yield
    finally:
        for variable, token in zip((_recorder, _trace, _span, _recording, _parent), tokens):
            variable.reset(token)


def emit(kind, data=None, *, name='', exception=None):
    recorder = _recorder.get()
    if recorder is not None and _recording.get():
        recorder.emit(kind, data, name=name, trace_id=_trace.get(), span_id=_span.get(),
                      parent_id=_parent.get(), recording_id=_recording.get(), exception=exception)


@contextmanager
def operation(name, inputs=None):
    if not _recording.get():
        yield
        return
    parent = _span.get()
    token = _span.set(uuid.uuid4().hex)
    parent_token = _parent.set(parent)
    started = time.perf_counter()
    outcome = 'success'
    emit('start', {'inputs': inputs or {}}, name=name)
    try:
        yield
    except BaseException as exc:
        outcome = 'failed'
        emit('exception', name=name, exception=exc)
        raise
    finally:
        recorder = _recorder.get()
        if recorder is not None and _recording.get():
            recorder.emit('end', {'outcome': outcome, 'elapsed_ms': (time.perf_counter() - started) * 1000},
                          name=name, trace_id=_trace.get(), span_id=_span.get(), parent_id=parent,
                          recording_id=_recording.get())
        _span.reset(token)
        _parent.reset(parent_token)


def observed(name, *, background=False):
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            def run():
                bound = signature.bind(*args, **kwargs)
                inputs = {k: v for k, v in bound.arguments.items() if k != 'self' and not _SECRET.search(k)}
                inputs = {k: ({f.name: getattr(v, f.name) for f in fields(v) if not _SECRET.search(f.name)}
                              if is_dataclass(v) and k in {'filters', 'context'} else v) for k, v in inputs.items()}
                with operation(name, inputs):
                    result = function(*args, **kwargs)
                    metadata = {}
                    if is_dataclass(result):
                        metadata = {f.name: getattr(result, f.name) for f in fields(result) if f.name in _NUMBER_FIELDS | _TEXT_FIELDS | {'hit', 'ok'}}
                        metadata['result_shape'] = {f.name: getattr(result, f.name) for f in fields(result) if not _SECRET.search(f.name)}
                        for field_name in ('rows', 'items', 'records'):
                            values = getattr(result, field_name, None)
                            if isinstance(values, (list, tuple)):
                                metadata['record_count'] = len(values)
                        content = getattr(result, 'content', None)
                        if isinstance(content, bytes):
                            metadata['byte_count'] = len(content)
                    elif isinstance(result, (list, tuple)):
                        metadata = {'count': len(result)}
                    elif isinstance(result, dict):
                        metadata = result
                    emit('result', metadata, name=name)
                    return result
            if background and _recorder.get() is None:
                recorder = default_recorder()
                if recorder.active_id():
                    with recording_scope(recorder):
                        return run()
            if _recorder.get() is None or not _recording.get():
                return function(*args, **kwargs)
            return run()
        return wrapped
    return decorate


def record_http(source, event):
    if _recorder.get() is None:
        return
    try:
        data = event if isinstance(event, dict) else {f.name: getattr(event, f.name) for f in fields(event)}
        emit('http', dict(data, source=source), name=source + '.http')
    except Exception:
        pass
