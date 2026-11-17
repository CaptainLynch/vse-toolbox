"""Local-only recording controls and Flask request correlation."""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import logging
import re
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import g, jsonify, request, send_file
from core import diagnostic_recording as dr
from core.redaction import redact_sensitive_text

# 诊断导出核心白名单字段集合（契约 C10：允许导出的顶层字段闭集）
DIAGNOSTIC_WHITELIST_FIELDS = frozenset({
    "anonymous_installation_id",
    "module_health",
    "safe_error_codes",
    "build_info",
    "user_notes",
})

# 模块健康字段白名单
MODULE_HEALTH_FIELDS = frozenset({
    "success_count",
    "failure_count",
    "last_timestamp",
})

# 构建信息字段白名单
BUILD_INFO_FIELDS = frozenset({
    "version",
    "build",
})

# 安全错误类型码闭集枚举（既有错误 type 码，仅收集属于此闭集的类型）
SAFE_ERROR_CODE_ENUM = frozenset({
    "LocalAccessRequired",
    "BodyTooLargeOrUnknown",
    "RecordingAlreadyActive",
    "DiagnosticStorageUnavailable",
    "DiagnosticExportUnavailable",
    "RecordingNotFound",
    "RateLimited",
    "InvalidEvent",
    "NotConfigured",
    "ValidationError",
    "UpstreamError",
    "AuthError",
    "NotFoundError",
    "ConflictError",
    "InternalError",
    "TimeoutError",
    "NetworkError",
    "DatabaseError",
    "InvalidState",
    "TaskFailed",
    "PayloadTooLarge",
    "BadGateway",
    "ServiceUnavailable",
})

# 内网 IP 地址与保留网段正则（第二道防线）
_INTERNAL_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"127\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
)
_INTERNAL_HOST_RE = re.compile(
    r"\b[a-zA-Z0-9_-]+\.(?:local|internal|corp|lan)\b",
    re.IGNORECASE
)
# 长随机串正则（32位及以上连续十六进制串或字母数字高熵串）
_LONG_RANDOM_STR_RE = re.compile(
    r"\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9_-]{32,}\b"
)

# 匿名安装盐值与内存种子（确保不包含机器名、用户名或宿主敏感标识）
_INSTALLATION_SALT = "vse-toolbox-anonymous-install-salt-v2"
_ANONYMOUS_SEED = str(uuid.uuid4())

_health_lock = threading.Lock()
_module_health: dict[str, dict[str, object]] = {}

_safe_errors_lock = threading.Lock()
_recorded_error_codes: set[str] = set()

_user_notes_lock = threading.Lock()
_active_user_notes: str | None = None


def redact_diagnostics_text(value: object) -> str:
    """脱敏辅助函数：在 core.redaction 基础上增加内网地址与长随机串脱敏（第二道防线）。"""
    if value is None:
        return ""
    text = redact_sensitive_text(value)
    # 脱敏内网 IPv4 地址与内部主机名，避免拓扑泄露
    text = _INTERNAL_IP_RE.sub("[internal address redacted]", text)
    text = _INTERNAL_HOST_RE.sub("[internal host redacted]", text)
    # 脱敏长随机串（单号特征、未知令牌或哈希），保留通用占位符
    text = _LONG_RANDOM_STR_RE.sub("[token redacted]", text)
    return text


def get_anonymous_installation_id(seed: str | None = None) -> str:
    """生成匿名安装标识（单向哈希，不含机器名、用户名或环境标识）。"""
    raw = f"{_INSTALLATION_SALT}:{(seed or _ANONYMOUS_SEED)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def record_module_health(module: str, success: bool, timestamp: str | None = None) -> None:
    """记录各模块健康计数：成功/失败次数与最近一次时间戳。"""
    if not isinstance(module, str) or not module.strip():
        module = "unknown"
    module_name = re.sub(r"[^a-zA-Z0-9_-]", "_", module.strip())[:32]
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    with _health_lock:
        rec = _module_health.setdefault(module_name, {
            "success_count": 0,
            "failure_count": 0,
            "last_timestamp": ts,
        })
        if success:
            rec["success_count"] = int(rec["success_count"]) + 1
        else:
            rec["failure_count"] = int(rec["failure_count"]) + 1
        rec["last_timestamp"] = ts


def get_module_health() -> dict[str, dict[str, object]]:
    """获取各模块健康计数字典（保证仅含白名单字段）。"""
    with _health_lock:
        return {
            mod: {
                "success_count": data["success_count"],
                "failure_count": data["failure_count"],
                "last_timestamp": data["last_timestamp"],
            }
            for mod, data in _module_health.items()
        }


def reset_module_health() -> None:
    """重置模块健康计数（测试与会话清理用）。"""
    with _health_lock:
        _module_health.clear()


def record_safe_error_code(code: str) -> None:
    """收集安全错误码（非白名单枚举值直接丢弃不收集）。"""
    if isinstance(code, str) and code in SAFE_ERROR_CODE_ENUM:
        with _safe_errors_lock:
            _recorded_error_codes.add(code)


def get_safe_error_codes() -> list[str]:
    """获取收集到的安全错误码列表。"""
    with _safe_errors_lock:
        return sorted(_recorded_error_codes)


def reset_safe_error_codes() -> None:
    """重置安全错误码记录（测试与会话清理用）。"""
    with _safe_errors_lock:
        _recorded_error_codes.clear()


def get_build_info() -> dict[str, str]:
    """获取版本与构建信息（仅限版本号与构建标识，不含路径与环境变量）。"""
    build_val = "vse-2.0.0"
    if hasattr(dr, "build_identity") and callable(dr.build_identity):
        try:
            build_val = str(dr.build_identity())
        except Exception:
            pass
    return {
        "version": "2.0.0",
        "build": build_val,
    }


def set_user_notes(text: str | None) -> None:
    """设置用户主动勾选的说明文本（经过脱敏处理作为第二道防线）。"""
    global _active_user_notes
    with _user_notes_lock:
        if text:
            _active_user_notes = redact_diagnostics_text(str(text))
        else:
            _active_user_notes = None


def get_user_notes() -> str:
    """获取用户说明文本。"""
    with _user_notes_lock:
        return _active_user_notes or ""


def build_diagnostic_payload(user_notes: str | None = None) -> dict[str, object]:
    """重构为字段白名单导出载荷，白名单之外的字段一律不进入导出。"""
    notes = redact_diagnostics_text(user_notes) if user_notes is not None else get_user_notes()
    raw = {
        "anonymous_installation_id": get_anonymous_installation_id(),
        "module_health": get_module_health(),
        "safe_error_codes": get_safe_error_codes(),
        "build_info": get_build_info(),
        "user_notes": notes,
    }
    # 严格白名单过滤：保证所有顶层键 ⊆ DIAGNOSTIC_WHITELIST_FIELDS
    return {k: v for k, v in raw.items() if k in DIAGNOSTIC_WHITELIST_FIELDS}


def _extract_module(path: str) -> str:
    """从请求路径提取模块名称用于健康计数统计。"""
    parts = [p for p in path.split('/') if p and p != 'api']
    if not parts:
        return 'web'
    first = parts[0].lower()
    if 'tdc' in first:
        return 'tdc'
    if 'aras' in first:
        return 'aras'
    if 'excel' in first:
        return 'excel'
    return first


def filter_diagnostic_bundle(raw_zip_bytes: bytes, user_notes: str | None = None) -> bytes:
    """过滤并重构诊断压缩包，确保符合白名单契约并阻断禁止清单内容。"""
    output_buf = io.BytesIO()
    payload = build_diagnostic_payload(user_notes)
    payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode('utf-8')

    forbidden_suffixes = ('.db', '.sqlite', '.sqlite3', '.sql', '.xlsx', '.xls', '.csv', '.xlsm', '.tsv', '.log')
    forbidden_names = {'environment.json'}

    with zipfile.ZipFile(io.BytesIO(raw_zip_bytes), 'r') as in_zip:
        with zipfile.ZipFile(output_buf, 'w', compression=zipfile.ZIP_DEFLATED) as out_zip:
            # 写入核心白名单诊断载荷
            out_zip.writestr('diagnostics.json', payload_bytes)

            for item in in_zip.infolist():
                name = item.filename
                # 禁止清单检查：阻断环境变量全集、数据库文件、工作簿与日志原文
                if name in forbidden_names or name.lower().endswith(forbidden_suffixes):
                    continue

                content = in_zip.read(name)

                if name == 'events.jsonl':
                    filtered_lines = []
                    for line in content.splitlines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except Exception:
                            continue
                        # 阻断原始请求体记录
                        if event.get('kind') in {'input'}:
                            continue
                        data = event.get('data')
                        if isinstance(data, dict):
                            # 剔除未白名单化的原始输入/请求细节
                            for k in list(data.keys()):
                                if k in {'inputs', 'request_body', 'response_body', 'query', 'request_headers'}:
                                    del data[k]
                                elif isinstance(data[k], str):
                                    data[k] = redact_diagnostics_text(data[k])
                        filtered_lines.append(json.dumps(event, ensure_ascii=False).encode('utf-8'))
                    out_zip.writestr('events.jsonl', b'\n'.join(filtered_lines) + (b'\n' if filtered_lines else b''))

                elif name == 'manifest.json':
                    try:
                        manifest = json.loads(content)
                        safe_manifest = {
                            k: manifest[k] for k in ('id', 'created', 'reason', 'duration', 'build')
                            if k in manifest
                        }
                        safe_manifest['diagnostics_whitelist'] = True
                        out_zip.writestr('manifest.json', json.dumps(safe_manifest, indent=2, ensure_ascii=False).encode('utf-8'))
                    except Exception:
                        pass

                elif name == 'summary.md':
                    safe_summary = redact_diagnostics_text(content.decode('utf-8', errors='replace'))
                    out_zip.writestr('summary.md', safe_summary.encode('utf-8'))

                elif name == 'exceptions.json':
                    try:
                        exceptions = json.loads(content)
                        if isinstance(exceptions, list):
                            safe_exc = []
                            for exc in exceptions:
                                if isinstance(exc, dict):
                                    edata = exc.get('data') or {}
                                    filtered_data = {
                                        k: edata[k] for k in ('exception_type', 'errno')
                                        if k in edata
                                    }
                                    safe_exc.append({'kind': exc.get('kind', 'exception'), 'data': filtered_data})
                            out_zip.writestr('exceptions.json', json.dumps(safe_exc, indent=2, ensure_ascii=False).encode('utf-8'))
                    except Exception:
                        pass
                else:
                    # 白名单机制：未明确允许的文件一律不进入导出包
                    continue

    return output_buf.getvalue()


def _local_error():
    try:
        if not ipaddress.ip_address(request.remote_addr).is_loopback:
            raise ValueError()
        host = urlsplit(request.host_url)
        if host.hostname != 'localhost' and not ipaddress.ip_address(host.hostname).is_loopback:
            raise ValueError()
        origin = request.headers.get('Origin')
        if origin is not None and origin.rstrip('/') != request.host_url.rstrip('/'):
            raise ValueError()
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify(ok=False, error='LocalAccessRequired'), 403
    return None


class _ExceptionHandler(logging.Handler):
    def emit(self, record):
        if record.exc_info and record.exc_info[1]:
            dr.emit('exception', name='logged.exception', exception=record.exc_info[1])


def install_diagnostics(app, recorder=None, local_guard=None):
    recorder = recorder or dr.default_recorder()
    app.extensions['diagnostic_recorder'] = recorder
    guard = local_guard or _local_error
    rate_lock = threading.Lock()
    rate = [0.0, 0]
    logger = logging.getLogger()
    if not any(isinstance(h, _ExceptionHandler) for h in logger.handlers):
        logger.addHandler(_ExceptionHandler(level=logging.ERROR))

    @app.before_request
    def diagnostic_begin():
        if request.path.startswith('/api/diagnostics'):
            denied = guard()
            if denied is not None:
                return denied
            if request.method != 'GET' and (request.content_length is None or request.content_length > 4096):
                return jsonify(ok=False, error='BodyTooLargeOrUnknown'), 413
            return None
        if not request.path.startswith('/api/') or request.path.startswith('/api/excel'):
            return None
        scope = dr.recording_scope(recorder, request.headers.get('X-VSE-Trace-ID', ''))
        scope.__enter__()
        g.diagnostic_scope = scope
        g.diagnostic_trace = dr._trace.get()
        name = request.endpoint or 'unknown_route'
        op = dr.operation(name)
        op.__enter__()
        g.diagnostic_operation = op

        # 白名单机制：直接不收集原始请求体与查询参数，仅记录有界操作标识
        action_id = request.headers.get('X-VSE-Action-ID', '')
        dr.emit('request', {'method': request.method, 'action_id': action_id}, name=name)

    @app.after_request
    def diagnostic_finish(response):
        if request.path.startswith('/api/diagnostics'):
            response.headers['Cache-Control'] = 'no-store'
        if hasattr(g, 'diagnostic_trace'):
            response.headers['X-VSE-Trace-ID'] = g.diagnostic_trace
            metadata = {'status_code': response.status_code}
            if response.is_json and response.calculate_content_length() is not None and response.calculate_content_length() <= 65536:
                payload = response.get_json(silent=True)
                if isinstance(payload, dict):
                    if isinstance(payload.get('ok'), bool):
                        metadata['ok'] = payload['ok']
                    error = payload.get('error')
                    if isinstance(error, dict):
                        err_type = error.get('type')
                        if isinstance(err_type, str) and err_type in SAFE_ERROR_CODE_ENUM:
                            metadata['error_type'] = err_type
                            record_safe_error_code(err_type)
                        diag = error.get('diagnostic')
                        if isinstance(diag, dict):
                            # 仅保留白名单安全诊断字段，如 apiCode
                            for k, v in diag.items():
                                if k in {'apiCode', 'stage', 'status_code'} or isinstance(v, (int, bool)):
                                    metadata[k] = v
                    elif isinstance(error, str) and error in SAFE_ERROR_CODE_ENUM:
                        record_safe_error_code(error)
            # 统计各模块健康计数（成功/失败与最近时间戳）
            mod = _extract_module(request.path)
            record_module_health(mod, success=(response.status_code < 400))
            dr.emit('response', metadata, name=request.endpoint or 'unknown_route')
        return response

    @app.teardown_request
    def diagnostic_teardown(error):
        op = g.pop('diagnostic_operation', None)
        scope = g.pop('diagnostic_scope', None)
        try:
            if op is not None:
                op.__exit__(type(error) if error else None, error, error.__traceback__ if error else None)
        finally:
            if scope is not None:
                scope.__exit__(None, None, None)

    @app.get('/api/diagnostics')
    def diagnostic_status():
        return jsonify(recorder.status())

    @app.post('/api/diagnostics/start')
    def diagnostic_start():
        try:
            payload = request.get_json(silent=True)
            if isinstance(payload, dict):
                note = payload.get('user_notes') or payload.get('note') or payload.get('description')
                if note:
                    set_user_notes(str(note))
            recorder.start()
            return jsonify(recorder.status())
        except ValueError:
            return jsonify(ok=False, error='RecordingAlreadyActive'), 409
        except Exception:
            return jsonify(ok=False, error='DiagnosticStorageUnavailable'), 503

    @app.post('/api/diagnostics/stop')
    def diagnostic_stop():
        try:
            return jsonify(recorder.stop())
        except Exception:
            return jsonify(ok=False, error='DiagnosticStorageUnavailable'), 503

    @app.post('/api/diagnostics/mark')
    def diagnostic_mark():
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            note = payload.get('user_notes') or payload.get('note') or payload.get('description')
            if note:
                set_user_notes(str(note))
        with dr.recording_scope(recorder):
            dr.emit('mark', name='user.mark')
        return jsonify(ok=True), 202

    @app.post('/api/diagnostics/events')
    def diagnostic_events():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('kind') not in {'action', 'frontend_error', 'fetch_error'}:
            return jsonify(ok=False, error='InvalidEvent'), 400
        with rate_lock:
            now = time.monotonic()
            if now - rate[0] >= 5:
                rate[:] = [now, 0]
            if rate[1] >= 100:
                return jsonify(ok=False, error='RateLimited'), 429
            rate[1] += 1
        metadata = {k: payload[k] for k in ('line', 'column', 'action_id') if k in payload}
        if payload.get('source') in {'app.js', 'diagnostics.js', 'unknown'}:
            metadata['source'] = payload['source']
        trace = payload.get('trace_id', '')
        if not isinstance(trace, str):
            trace = ''
        with dr.recording_scope(recorder, trace):
            dr.emit(payload['kind'], metadata, name='browser.event')
        return jsonify(ok=True), 202

    @app.get('/api/diagnostics/bundles/<identity>')
    def diagnostic_download(identity):
        try:
            raw_payload = recorder.export(identity)
        except (ValueError, KeyError, FileNotFoundError):
            return jsonify(ok=False, error='RecordingNotFound'), 404
        except Exception:
            return jsonify(ok=False, error='DiagnosticExportUnavailable'), 503
        note = request.args.get('note') or request.args.get('user_notes')
        payload = filter_diagnostic_bundle(raw_payload, user_notes=note)
        return send_file(io.BytesIO(payload), mimetype='application/zip', as_attachment=True,
                         download_name=f'vse-diagnostics-{identity}.zip')
