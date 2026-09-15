"""Local-only recording controls and Flask request correlation."""
from __future__ import annotations

import io
import ipaddress
import logging
import threading
import time
from urllib.parse import urlsplit

from flask import g, jsonify, request, send_file
from core import diagnostic_recording as dr


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
        # Record only bounded structural input; credentials are excluded by projection.
        if request.is_json and request.content_length is not None and request.content_length <= 65536:
            payload = request.get_json(silent=True)
            if isinstance(payload, dict):
                dr.emit('input', {'inputs': payload}, name=name)
        dr.emit('request', {'method': request.method, 'inputs': dict(request.args),
                            'action_id': request.headers.get('X-VSE-Action-ID', '')}, name=name)

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
                    if isinstance(error, dict) and isinstance(error.get('diagnostic'), dict):
                        metadata.update(error['diagnostic'])
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
            payload = recorder.export(identity)
        except (ValueError, KeyError, FileNotFoundError):
            return jsonify(ok=False, error='RecordingNotFound'), 404
        except Exception:
            return jsonify(ok=False, error='DiagnosticExportUnavailable'), 503
        return send_file(io.BytesIO(payload), mimetype='application/zip', as_attachment=True,
                         download_name=f'vse-diagnostics-{identity}.zip')
