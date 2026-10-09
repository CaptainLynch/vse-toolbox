# -*- coding: utf-8 -*-
"""TIR 数据简表导出：落盘 Excel、幂等复用、任务视图（不含 Flask）。

交付物只有一件：帆软原样导出的 xlsx，落在 ``<插件数据目录>/exports/<导出日 YYYY-MM-DD>/``，文件名是纯 ASCII 的
``tir_<项目>_<起>-<止>_<键哈希>.xlsx``——同一导出日同一组筛选条件的文件名固定，已有成功产物时直接复用
（``force`` 才重跑）。复用与产物列表需要的运行记录（行数、表头校验）是插件内部数据，放在
``<插件数据目录>/runs/<导出日>/<同名>.json``，不进导出目录、不提供下载。失败不写任何文件，原因见任务错误信息。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import protocol as P
from .client import FineReportClient, TirError

TASK_TYPE = "tir_report_export"
TASK_SOURCE = "tir-report"
CONFIG_FILE = "config.json"
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}\.xlsx$")
_TASK_ID_RE = re.compile(r"^crawl_[0-9a-f]{12}$")
_REF_RE = re.compile(r"^[^\x00-\x1f]{1,256}$")
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── 配置（只存凭据别名与默认筛选，不存账号口令） ────────────────────


def default_config() -> dict[str, Any]:
    return {"credentialRef": "", "defaults": {"project": P.DEFAULT_PROJECT, "department": P.DEFAULT_DEPARTMENT,
                                              "section": "", "startDate": P.DEFAULT_START_DATE}}


def load_config(data_dir: Path) -> dict[str, Any]:
    config = default_config()
    try:
        stored = json.loads((Path(data_dir) / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config
    if isinstance(stored, Mapping):
        ref = stored.get("credentialRef")
        if isinstance(ref, str) and (not ref or _REF_RE.match(ref)):
            config["credentialRef"] = ref
        defaults = stored.get("defaults")
        if isinstance(defaults, Mapping):
            for key in config["defaults"]:
                if isinstance(defaults.get(key), str):
                    config["defaults"][key] = defaults[key]
    return config


def validate_credential_ref(value: Any) -> str:
    if not isinstance(value, str):
        raise P.ProtocolError("凭据条目名必须是文本")
    ref = value.strip()
    if ref and not _REF_RE.match(ref):
        raise P.ProtocolError("凭据条目名无效")
    return ref


def save_config(data_dir: Path, config: Mapping[str, Any]) -> None:
    _atomic_write(Path(data_dir) / CONFIG_FILE, json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"))


# ── 路径 ─────────────────────────────────────────────────────────


def exports_root(data_dir: Path) -> Path:
    return Path(data_dir) / "exports"


def runs_root(data_dir: Path) -> Path:
    return Path(data_dir) / "runs"


def file_stem(filters: P.ExportFilters) -> str:
    project = re.sub(r"[^A-Za-z0-9-]", "", filters.project)[:24] or "project"
    digest = hashlib.sha256(filters.cache_key().encode("utf-8")).hexdigest()[:8]
    return f"tir_{project}_{filters.start_date.replace('-', '')}-{filters.end_date.replace('-', '')}_{digest}"


def safe_file_path(data_dir: Path, day: str, name: str) -> Path | None:
    """Resolve a download request; ``None`` unless it is a listed export inside the exports root."""
    if not _DAY_RE.match(day or "") or not _NAME_RE.match(name or ""):
        return None
    root = exports_root(data_dir).resolve()
    target = (root / day / name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def find_cached(data_dir: Path, day: str, filters: P.ExportFilters) -> dict[str, Any] | None:
    stem = file_stem(filters)
    try:
        meta = json.loads((runs_root(data_dir) / day / f"{stem}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if meta.get("ok") and (exports_root(data_dir) / day / f"{stem}.xlsx").is_file():
        return {**meta, "day": day}
    return None


def list_exports(data_dir: Path, limit: int = 50) -> list[dict[str, Any]]:
    root = exports_root(data_dir)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for day_dir in sorted((p for p in root.iterdir() if p.is_dir() and _DAY_RE.match(p.name)), reverse=True):
        for xlsx in sorted(day_dir.glob("tir_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta = json.loads((runs_root(data_dir) / day_dir.name / f"{xlsx.stem}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {"stem": xlsx.stem}
            items.append({**meta, "day": day_dir.name, "file": xlsx.name})
            if len(items) >= limit:
                return items
    return items


# ── 导出 ─────────────────────────────────────────────────────────


def header_check(content: bytes) -> dict[str, Any]:
    """Compare row 1 of the workbook with the sample's 50 headers (via ``services.xlsx_preview``)."""
    from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check.xlsx"
        path.write_bytes(content)
        try:
            preview = read_xlsx_preview(path, max_rows=2)
        except (XLSXPreviewError, OSError, ValueError) as exc:
            return {"ok": False, "columns": 0, "reason": type(exc).__name__}
    first = preview.rows[0] if preview.rows else []
    headers = [str(value if value is not None else "").strip() for value in first]
    while headers and not headers[-1]:
        headers.pop()
    return {"ok": tuple(headers) == P.EXPECTED_HEADERS, "columns": len(headers)}


def run_export(
    filters: P.ExportFilters,
    *,
    data_dir: Path,
    credential_ref: str,
    credential_provider: Any,
    session_factory: Callable[[], Any],
    today: date,
    force: bool = False,
    base_url: str = P.DEFAULT_BASE_URL,
    progress: Callable[[str, int], None] = lambda stage, percent: None,
    cancelled: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run one export and write the original xlsx. Returns the run record."""
    day = today.isoformat()
    if not force:
        cached = find_cached(data_dir, day, filters)
        if cached is not None:
            return {**cached, "reused": True}
    if not credential_ref:
        raise TirError("credential_missing")

    stem = file_stem(filters)
    client_kwargs: dict[str, Any] = {"base_url": base_url, "cancelled": cancelled}
    if sleep is not None:
        client_kwargs["sleep"] = sleep
    client = FineReportClient(session_factory(), **client_kwargs)
    started = datetime.now().isoformat(timespec="seconds")
    from core.credential_provider import CredentialProviderError

    progress("login", 10)
    try:
        with credential_provider.resolve(credential_ref) as credential:
            result = client.run(credential.username, credential.password, P.build_parameters(filters))
    except CredentialProviderError:
        raise TirError("credential_unavailable") from None
    progress("save", 90)
    meta: dict[str, Any] = {
        "ok": True, "report": P.REPORT_NAME, "filters": filters.as_payload(), "stem": stem,
        "rows": result.rows, "headerCheck": header_check(result.content), "bytes": len(result.content),
        "steps": list(result.steps), "startedAt": started,
        "finishedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _atomic_write(exports_root(data_dir) / day / f"{stem}.xlsx", result.content)
    _atomic_write(runs_root(data_dir) / day / f"{stem}.json", json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    progress("done", 100)
    return {**meta, "day": day, "reused": False}


# ── 任务 ─────────────────────────────────────────────────────────


def valid_task_id(task_id: str) -> bool:
    return bool(_TASK_ID_RE.match(task_id or ""))


def task_params(filters: P.ExportFilters, force: bool) -> dict[str, Any]:
    # 只放业务筛选；凭据别名在执行时从配置读（sanitize_task_params 会剔除 credential* 键）。
    return {"filters": filters.as_payload(), "force": bool(force)}


def task_view(task: Mapping[str, Any]) -> dict[str, Any]:
    try:
        progress = json.loads(task.get("progress_json") or "{}")
    except ValueError:
        progress = {}
    try:
        params = json.loads(task.get("params_json") or "{}")
    except ValueError:
        params = {}
    return {
        "taskId": task.get("task_id"),
        "status": task.get("status"),
        "stage": progress.get("stage"),
        "percent": progress.get("percent"),
        "result": progress.get("result"),
        "filters": params.get("filters") if isinstance(params, Mapping) else None,
        "error": task.get("error_message"),
    }
