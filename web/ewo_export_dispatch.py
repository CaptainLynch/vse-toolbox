"""EWO 官方导出/续下载的本机后台派发。

任务中心只负责展示状态（``EWOExportJobs``），真正的下载动作由本模块在本机线程里
执行：用已绑定的 Aras 域会话构造客户端与 transport，调用
``services.ewo_csv_export.run_official_export``。

约束：
- 只允许同一域会话（scope）继续自己的任务；
- 线程内异常只记录日志，任务状态由编排器落库（generation_unknown / export_failed）；
- 不持有凭据、不写 token；线程为 daemon，进程退出后在途任务由 ``recover`` 收敛。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from core.ewo_export_jobs import EWOExportJobs
from services.aras_auth import DEFAULT_ARAS_BASE_URL
from services.aras_crawler import ArasCrawlerClient
from services.ewo_csv_export import EwoExportDeps, run_official_export
from services.ewo_export_transport import EWOExportTransport

logger = logging.getLogger(__name__)

__all__ = ["build_export_resume_runner", "spawn_official_export"]


def spawn_official_export(job_id: str, scope: str, deps: EwoExportDeps) -> threading.Thread:
    """在本机 daemon 线程里推进导出；返回线程对象便于测试 join。"""

    def run() -> None:
        try:
            run_official_export(job_id, scope, deps)
        except Exception:  # noqa: BLE001 - 状态已由编排器落库，这里只保证线程不炸
            logger.exception("EWO official export failed (job=%s)", job_id)

    thread = threading.Thread(target=run, name=f"ewo-export-{job_id[:8]}", daemon=True)
    thread.start()
    return thread


def build_export_resume_runner(
    domain_sessions: Any,
    db: Any,
    downloads_dir: Path,
    *,
    base_url: str = DEFAULT_ARAS_BASE_URL,
    client_factory: Callable[..., Any] = ArasCrawlerClient,
    transport_factory: Callable[[Any], Any] = EWOExportTransport,
) -> Callable[[str, str], bool]:
    """返回 ``resume(job_id, scope) -> bool``：续下载任务（generated → exported）。

    返回 False 表示无法续跑（没有匹配的域会话、库不可用），调用方应给出明确提示。
    """
    downloads = Path(downloads_dir)

    def resume(job_id: str, scope: str) -> bool:
        binding = domain_sessions.bound_session('aras', base_url)
        if binding is None:
            return False
        session, session_scope = binding
        if session_scope != scope:
            return False
        try:
            jobs = EWOExportJobs(db.db_path)
        except Exception:  # noqa: BLE001 - 迁移失败已降级，这里再兜一次
            logger.exception("EWO export jobs unavailable for resume")
            return False
        client = client_factory(base_url, session=session, timeout=30.0)
        deps = EwoExportDeps(
            jobs=jobs,
            crawler=client,
            transport=transport_factory(client),
            downloads_dir=downloads,
        )
        spawn_official_export(job_id, scope, deps)
        return True

    return resume
