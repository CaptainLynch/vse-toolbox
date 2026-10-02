"""Local-only HTTP adapter for account-bound EWO enrichment."""
from dataclasses import fields
import re

from flask import jsonify, request

from core.ewo_export_jobs import ExportJobConflict
from services.aras_auth import DEFAULT_ARAS_BASE_URL
from services.aras_crawler import ArasCrawlerClient, EWOReportFilters


def register_ewo_enrichment(app, service, registry, local_guard, *, crawler_factory=ArasCrawlerClient):
    allowed_filters = {field.name for field in fields(EWOReportFilters)}

    def error(status, code, message):
        response = jsonify({'ok': False, 'error': {'type': code, 'message': message}})
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    def handle(action, job_id=None):
        blocked = local_guard()
        if blocked is not None:
            return blocked
        body = request.get_json(silent=True)
        allowed = {'filters', 'sourceItemId'} if action in ('prepare', 'restore') else set()
        if not isinstance(body, dict) or set(body) - allowed:
            return error(400, 'ValidationError', '请求字段不符合增强导表接口要求')
        binding = registry.bound_session('aras', DEFAULT_ARAS_BASE_URL)
        if binding is None:
            return error(401, 'DomainLoginRequired', '请在系统设置中重新登录域账号')
        session, scope = binding
        if job_id is not None and not re.fullmatch('[0-9a-fA-F]{32}', job_id):
            return error(404, 'NotFound', '增强导表任务不可用')
        try:
            if action in ('prepare', 'restore'):
                values = body.get('filters', {})
                if not isinstance(values, dict) or set(values) - allowed_filters:
                    return error(400, 'ValidationError', 'EWO筛选字段无效')
                if any(v is not None and (not isinstance(v, str) or len(v) > 256
                                          or any(ord(c) < 32 for c in v)) for v in values.values()):
                    return error(400, 'ValidationError', 'EWO筛选值无效')
                filters = EWOReportFilters(**{k: v.strip() or None if v is not None else None
                                              for k, v in values.items()})
                if action == 'restore':
                    data = service.restore(scope, filters, source_item_id=body.get('sourceItemId'))
                else:
                    crawler = crawler_factory(DEFAULT_ARAS_BASE_URL, session=session, prewarm=False, timeout=30)
                    data = service.prepare(scope, crawler, filters, source_item_id=body.get('sourceItemId'))
            elif action == 'run':
                # Authorize job before constructing any upstream operation.
                service.status(job_id, scope)
                crawler = crawler_factory(DEFAULT_ARAS_BASE_URL, session=session, prewarm=False, timeout=30)
                data = service.run(job_id, scope, crawler)
            else:
                data = service.status(job_id, scope)
            current = registry.bound_session('aras', DEFAULT_ARAS_BASE_URL)
            if current is None or current[0] is not session or current[1] != scope:
                return error(401, 'DomainLoginChanged', '登录状态已变化，请重新读取任务')
            response = jsonify({'ok': True, 'data': data})
            response.headers['Cache-Control'] = 'no-store'
            return response
        except ExportJobConflict:
            return error(409, 'ExportJobUnavailable', '任务不可用、正在运行或不属于当前账号')
        except ValueError:
            return error(422, 'IncompleteSelection', '无法准备完整EWO集合，请核对筛选条件或缩小范围')
        except Exception:
            return error(502, 'EWOEnrichmentUnavailable', '增强导表暂不可用，请检查登录及源系统状态')

    @app.post('/api/aras/ewo/enrichment/jobs')
    def ewo_enrichment_prepare():
        return handle('prepare')

    @app.post('/api/aras/ewo/enrichment/jobs/restore')
    def ewo_enrichment_restore():
        return handle('restore')

    @app.post('/api/aras/ewo/enrichment/jobs/<job_id>/run')
    def ewo_enrichment_run(job_id):
        return handle('run', job_id)

    @app.post('/api/aras/ewo/enrichment/jobs/<job_id>/status')
    def ewo_enrichment_status(job_id):
        return handle('status', job_id)
