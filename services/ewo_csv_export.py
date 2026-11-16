"""EWO 111 列 CSV 导出编排（官方工作簿为唯一数据源）。

流程（每一步都先提交状态、再产生外部副作用）：

    queued → listing（列表预检，只读，可自由重试）
           → generating（提交后才调用官方导出；失败只能落 generation_unknown）
           → generated（file_id 已持久化）→ downloading（claim，可续）
           → [下载 / 表头门禁 / 对账 / 投影 / 原子写盘]
           → exported

失败分流：
- 列表阶段失败（含不完整、ID/编号非法）→ ``export_failed(stage=listing)``，允许用户显式重建任务；
- 生成阶段任何异常 → ``interruption``（generating → generation_unknown），绝不重发；
- 下载/写盘失败 → 回 ``generated``（保留 file_id，可续下载）；
- 门禁失败（表头、契约外列有值、对账不等）→ ``export_failed``，需重建并重新确认范围。

本模块只负责编排，不处理凭据、不拼接 HTTP；下载 token 由 transport 管理且不落盘。
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.ewo_export_jobs import EWOExportJobs
from services.aras_export import write_table_csv_atomically
from services.ewo_official_rows import (
    EwoExportGateError,
    contract_labels,
    project_official_ewo_rows,
    read_official_ewo_rows,
    reconcile_official_rows,
)

_ITEM_ID = re.compile(r'[0-9a-fA-F]{32}')

__all__ = ["EwoCsvExportError", "EwoExportDeps", "prepare_selection", "run_official_export"]


class EwoCsvExportError(ValueError):
    """导出编排的本地错误；消息不得包含凭据或上游响应正文。"""


@dataclass(frozen=True)
class EwoExportDeps:
    """编排依赖；reader/writer 可注入以便离线测试。"""

    jobs: EWOExportJobs
    crawler: Any
    transport: Any
    downloads_dir: Path
    filters: Any = None
    reader: Callable[[Path], tuple[dict[str, object], ...]] = read_official_ewo_rows
    writer: Callable[[Path, list[str], list[list[object | None]]], None] = write_table_csv_atomically


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _selection_ids(result: Any) -> list[str]:
    ids = [str(value or '').strip() for value in getattr(result, 'item_ids', None) or []]
    if not ids:
        raise EwoExportGateError('E_LIST_EMPTY', '列表预检未返回任何 EWO')
    if len(set(ids)) != len(ids):
        raise EwoExportGateError('E_LIST_KEY_INVALID', '列表预检返回重复内部 ID')
    if any(not _ITEM_ID.fullmatch(value) for value in ids):
        raise EwoExportGateError('E_LIST_KEY_INVALID', '列表预检返回非 32 位内部 ID')
    return ids


def _base_rows(ids: list[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) != len(ids):
        raise EwoExportGateError('E_LIST_KEY_INVALID', '列表预检行数与内部 ID 数不一致')
    base: list[dict[str, Any]] = []
    for item_id, row in zip(ids, rows):
        base.append({'id': item_id, '_no': row.get('_no') if isinstance(row, dict) else None})
    return base


def _list_and_generate(job_id: str, scope: str, deps: EwoExportDeps, *,
                       page_size: int, max_pages: int, max_records: int) -> None:
    jobs = deps.jobs
    listing = jobs.start_listing(job_id, scope)
    try:
        result = deps.crawler.crawl_ewo_report_all(
            deps.filters,
            page_size=page_size, max_pages=max_pages, max_records=max_records,
        )
    except Exception:
        jobs.fail_export(job_id, scope, listing['lease_token'], stage='listing', code='E_LIST_FAILED')
        raise
    if not getattr(result, 'complete', False) or getattr(result, 'truncated', False):
        jobs.fail_export(job_id, scope, listing['lease_token'], stage='listing', code='E_LIST_INCOMPLETE')
        raise EwoCsvExportError('列表预检不完整，已按 fail-closed 终止（未调用官方导出）')
    try:
        ids = _selection_ids(result)
        base_rows = _base_rows(ids, list(getattr(result, 'rows', []) or []))
    except EwoExportGateError as exc:
        jobs.fail_export(job_id, scope, listing['lease_token'], stage='listing', code=exc.code)
        raise
    jobs.update_context(job_id, scope, {'base_rows': base_rows})
    # 顺序契约：先把 generating 提交到库，再调用非幂等的服务端生成。
    jobs.begin_generation(job_id, scope, listing['lease_token'])
    try:
        file_id = deps.transport.generate(ids)
    except Exception:
        jobs.interrupted(job_id, scope, listing['lease_token'])
        return
    jobs.generated(job_id, scope, listing['lease_token'], file_id)


def _generate_only(job_id: str, scope: str, deps: EwoExportDeps) -> None:
    """路由已完成列表预检（context 已有 base_rows）：只做生成，不再重复列表。"""
    jobs = deps.jobs
    context, _ = jobs.data(job_id, scope)
    ids = [str(row.get('id') or '') for row in context.get('base_rows') or []]
    if not ids:
        raise EwoCsvExportError('缺少选择集上下文，无法生成')
    listing = jobs.start_listing(job_id, scope)
    jobs.begin_generation(job_id, scope, listing['lease_token'])
    try:
        file_id = deps.transport.generate(ids)
    except Exception:
        jobs.interrupted(job_id, scope, listing['lease_token'])
        return
    jobs.generated(job_id, scope, listing['lease_token'], file_id)


def _download_and_export(job_id: str, scope: str, deps: EwoExportDeps) -> dict[str, Any]:
    jobs = deps.jobs
    run = jobs.claim(job_id, scope, lease_seconds=1800)
    context, _ = jobs.data(job_id, scope)
    base_rows = context.get('base_rows') or []
    if not base_rows:
        jobs.fail_export(job_id, scope, run['lease_token'], stage='projecting', code='E_SELECTION_MISSING')
        raise EwoCsvExportError('缺少选择集上下文，无法对账')
    labels = contract_labels()
    deps.downloads_dir.mkdir(parents=True, exist_ok=True)
    target = deps.downloads_dir / f'ewo_export_{job_id}.csv'
    try:
        with tempfile.TemporaryDirectory(prefix='ewo-export-', dir=str(deps.downloads_dir)) as tmp:
            workbook_path = deps.transport.download(run['file_id'], Path(tmp))
            rows = deps.reader(Path(workbook_path))
            matrix = project_official_ewo_rows(rows, labels)
            reconcile_official_rows(base_rows, matrix, labels)
            deps.writer(target, labels, matrix)
            digest = _sha256(target)
    except EwoExportGateError as exc:
        jobs.fail_export(job_id, scope, run['lease_token'], stage='projecting', code=exc.code)
        raise
    except Exception:
        jobs.interrupted(job_id, scope, run['lease_token'])
        raise
    return jobs.complete_export(
        job_id, scope, run['lease_token'],
        artifact_path=target.name, artifact_sha256=digest, row_count=len(matrix),
    )


def prepare_selection(result: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """把列表预检结果规范成（内部 ID 列表，对账用 base_rows）。

    路由层在创建任务前调用：任何 ID/行数异常都在这里 fail-closed，避免把
    不完整的集合带进非幂等的生成阶段。
    """
    ids = _selection_ids(result)
    return ids, _base_rows(ids, list(getattr(result, 'rows', []) or []))


def run_official_export(
    job_id: str,
    scope: str,
    deps: EwoExportDeps,
    *,
    page_size: int = 1000,
    max_pages: int = 6,
    max_records: int = 5000,
) -> dict[str, Any]:
    """推进一个 csv_export 任务；重复调用不会重新生成（幂等续跑）。"""
    jobs = deps.jobs
    job = jobs.get(job_id, scope)
    if job.get('purpose') != 'csv_export':
        raise EwoCsvExportError('仅支持 csv_export 任务')
    if job['state'] == 'queued':
        context, _ = jobs.data(job_id, scope)
        if context.get('base_rows'):
            # 路由层已做同步列表预检：这里只负责生成，避免对同一选择重复抓列表。
            _generate_only(job_id, scope, deps)
        else:
            _list_and_generate(job_id, scope, deps, page_size=page_size,
                               max_pages=max_pages, max_records=max_records)
        job = jobs.get(job_id, scope)
    if job['state'] == 'generated':
        return _download_and_export(job_id, scope, deps)
    return job
