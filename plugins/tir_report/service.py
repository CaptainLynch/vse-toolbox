# -*- coding: utf-8 -*-
"""TIR 数据简表导出：落盘 Excel、幂等复用、自动导出、任务视图（不含 Flask）。

交付物只有一件：帆软原样导出的 xlsx。落盘格式与「自动归档」的其他交付物完全一致（用户 2026-10-09 确认）：
同一个 ``core.archive_store.ArchiveStore`` 写入同一个归档根目录（设置里的 ``archiveDirectory``，缺省
``data/output/exports``），路径 ``<根>/finereport/tir_brief/<日期>/<运行号>/<平台文件名，缺省 TIR数据简表.xlsx>``，
artifact_type 为 ``official_xlsx``，与 TDC/Aras 官方工作簿同一套安全检查与重名处理。
同一导出日同一组筛选条件已有成功产物时直接复用（``force`` 才重跑）；复用判断与产物列表用的运行记录是插件内部数据，
放在 ``<插件数据目录>/runs/<导出日>/<筛选键>.json``（不提供下载）。失败不写任何文件。

账号：帆软账号与统一域账号相同，只经宿主的 DPAPI 域账号库读取（``DOMAIN_REF``），插件不保存账号口令。
自动导出参照「自动归档」：Windows 计划任务每小时跑一次 ``tools/tir_export_cli.py --once``，
由 ``auto_decision`` 判断是否到点、当天是否已有结果；登录类失败当天不再重试，避免锁定域账号。
同一时刻只允许一个导出（页面任务与计划任务跨进程互斥，``run_lock``）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from . import protocol as P
from .client import FineReportClient, TirError

TASK_TYPE = "tir_report_export"
#: 归档路径中的来源/报表段，命名风格同 core.db_common.ARCHIVE_JOB_CONTRACTS（aras/ewo、tdc/data_model）。
ARCHIVE_SOURCE = "finereport"
ARCHIVE_REPORT = "tir_brief"
ARTIFACT_TYPE = "official_xlsx"
RUN_SEQ_FILE = "run-seq.json"
TASK_SOURCE = "tir-report"
CONFIG_FILE = "config.json"
AUTO_STATE_FILE = "auto-state.json"
#: DPAPICredentialProvider 只认这个引用名：统一域账号。
DOMAIN_REF = "domain"
DEFAULT_AUTO_HOUR = 8
AUTO_MAX_ATTEMPTS = 3
#: 这些失败重试也不会好，还可能锁定域账号：当天停止自动重试。
AUTO_STOP_CODES = frozenset({"credential_missing", "credential_unavailable", "login_failed", "login_unsupported"})
_LOCK_STALE_SECONDS = 30 * 60
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STEM_RE = re.compile(r"^tir_[A-Za-z0-9-]{1,24}_\d{8}-\d{8}_[0-9a-f]{8}$")
_TASK_ID_RE = re.compile(r"^crawl_[0-9a-f]{12}$")
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── 配置（只存默认筛选与自动导出设置，不存账号口令） ──────────────────


def default_config() -> dict[str, Any]:
    return {
        "defaults": {"project": P.DEFAULT_PROJECT, "department": P.DEFAULT_DEPARTMENT, "section": "",
                     "startDate": P.DEFAULT_START_DATE},
        "auto": {"enabled": False, "hour": DEFAULT_AUTO_HOUR},
    }


def load_config(data_dir: Path) -> dict[str, Any]:
    config = default_config()
    try:
        stored = json.loads((Path(data_dir) / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config
    if isinstance(stored, Mapping):
        defaults = stored.get("defaults")
        if isinstance(defaults, Mapping):
            for key in config["defaults"]:
                if isinstance(defaults.get(key), str):
                    config["defaults"][key] = defaults[key]
        auto = stored.get("auto")
        if isinstance(auto, Mapping):
            if isinstance(auto.get("enabled"), bool):
                config["auto"]["enabled"] = auto["enabled"]
            hour = auto.get("hour")
            if isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23:
                config["auto"]["hour"] = hour
    return config


def validate_auto(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise P.ProtocolError("自动导出设置无效")
    enabled = value.get("enabled", False)
    hour = value.get("hour", DEFAULT_AUTO_HOUR)
    if not isinstance(enabled, bool):
        raise P.ProtocolError("自动导出开关必须是布尔值")
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        raise P.ProtocolError("自动导出时间必须是 0~23 点")
    return {"enabled": enabled, "hour": hour}


def default_filters(config: Mapping[str, Any], today: date) -> P.ExportFilters:
    """自动导出用保存的默认筛选，结束日期取当天。"""
    return P.normalize_filters({**config["defaults"], "endDate": today.isoformat()}, today=today)


def save_config(data_dir: Path, config: Mapping[str, Any]) -> None:
    _atomic_write(Path(data_dir) / CONFIG_FILE, json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"))


# ── 路径 ─────────────────────────────────────────────────────────


def archive_store(archive_directory: Any = None) -> Any:
    """Same root selection as the scheduled-archive runner/admin (``archiveDirectory`` setting)."""
    from core.archive_store import ArchiveStore

    if isinstance(archive_directory, str) and archive_directory.strip():
        return ArchiveStore({"default": archive_directory.strip()})
    return ArchiveStore()


def runs_root(data_dir: Path) -> Path:
    return Path(data_dir) / "runs"


def file_stem(filters: P.ExportFilters) -> str:
    """Run-record key for one filter set (ASCII; not the delivered file name)."""
    project = re.sub(r"[^A-Za-z0-9-]", "", filters.project)[:24] or "all"
    digest = hashlib.sha256(filters.cache_key().encode("utf-8")).hexdigest()[:8]
    return f"tir_{project}_{filters.start_date.replace('-', '')}-{filters.end_date.replace('-', '')}_{digest}"


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


def artifact_path(store: Any, record: Mapping[str, Any]) -> Path | None:
    """Absolute path of a recorded export, only if it is still a file inside the archive root."""
    relative = record.get("relativePath")
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in relative.split("/"):
        return None
    try:
        root = store.root("default").resolve()
        target = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _read_record(data_dir: Path, day: str, stem: str) -> dict[str, Any] | None:
    try:
        record = json.loads((runs_root(data_dir) / day / f"{stem}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("ok") else None


def find_cached(data_dir: Path, store: Any, day: str, filters: P.ExportFilters) -> dict[str, Any] | None:
    record = _read_record(data_dir, day, file_stem(filters))
    if record is not None and artifact_path(store, record) is not None:
        return {**record, "day": day}
    return None


def list_exports(data_dir: Path, store: Any, limit: int = 50) -> list[dict[str, Any]]:
    root = runs_root(data_dir)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for day_dir in sorted((p for p in root.iterdir() if p.is_dir() and _DAY_RE.match(p.name)), reverse=True):
        for path in sorted(day_dir.glob("tir_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            record = _read_record(data_dir, day_dir.name, path.stem)
            if record is None or artifact_path(store, record) is None:
                continue
            items.append({**record, "day": day_dir.name})
            if len(items) >= limit:
                return items
    return items


def download_path(data_dir: Path, store: Any, day: str, stem: str) -> tuple[Path, str] | None:
    """Resolve a download by (export day, run-record key); ``None`` unless it is a recorded export."""
    if not _DAY_RE.match(day or "") or not _STEM_RE.match(stem or ""):
        return None
    record = _read_record(data_dir, day, stem)
    if record is None:
        return None
    target = artifact_path(store, record)
    if target is None:
        return None
    return target, str(record.get("fileName") or P.DEFAULT_FILE_NAME)


def _next_run_id(data_dir: Path) -> int:
    """Monotonic run number (the ``<运行号>`` folder, like the archive runner's run id). Call under ``run_lock``."""
    path = runs_root(data_dir) / RUN_SEQ_FILE
    try:
        current = int(json.loads(path.read_text(encoding="utf-8")).get("last", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        current = 0
    value = current + 1
    _atomic_write(path, json.dumps({"last": value}).encode("utf-8"))
    return value


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


def login_name(username: str) -> str:
    """域账号库可能存成 ``域\\工号``；帆软用工号登录（Phase 0 探针复核）。"""
    return username.rsplit("\\", 1)[-1].strip()


@contextmanager
def run_lock(data_dir: Path, *, now: Callable[[], float] = time.time) -> Iterator[None]:
    """Cross-process lock: the web task and the scheduled CLI never export at the same time."""
    path = runs_root(data_dir) / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                stale = now() - path.stat().st_mtime > _LOCK_STALE_SECONDS
            except OSError:
                stale = True
            if not stale:
                raise TirError("busy") from None
            try:
                path.unlink()
            except OSError:
                pass
    else:
        raise TirError("busy")
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def run_export(
    filters: P.ExportFilters,
    *,
    data_dir: Path,
    store: Any,
    credential_provider: Any,
    session_factory: Callable[[], Any],
    today: date,
    force: bool = False,
    base_url: str = P.DEFAULT_BASE_URL,
    progress: Callable[[str, int], None] = lambda stage, percent: None,
    cancelled: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run one export with the domain account and archive the original xlsx. Returns the run record."""
    day = today.isoformat()
    if not force:
        cached = find_cached(data_dir, store, day, filters)
        if cached is not None:
            return {**cached, "reused": True}
    if credential_provider is None or not credential_provider.is_available(DOMAIN_REF):
        raise TirError("credential_missing")

    stem = file_stem(filters)
    client_kwargs: dict[str, Any] = {"base_url": base_url, "cancelled": cancelled}
    if sleep is not None:
        client_kwargs["sleep"] = sleep
    from core.credential_provider import CredentialProviderError

    with run_lock(data_dir):
        if not force:  # 等锁期间另一进程可能刚导出完
            cached = find_cached(data_dir, store, day, filters)
            if cached is not None:
                return {**cached, "reused": True}
        client = FineReportClient(session_factory(), **client_kwargs)
        started = datetime.now().isoformat(timespec="seconds")
        progress("login", 10)
        try:
            with credential_provider.resolve(DOMAIN_REF) as credential:
                result = client.run(login_name(credential.username), credential.password,
                                    P.build_parameters(filters))
        except CredentialProviderError:
            raise TirError("credential_unavailable") from None
        progress("save", 90)
        run_id = _next_run_id(data_dir)
        artifact = store.write_bytes(result.content, source=ARCHIVE_SOURCE, report=ARCHIVE_REPORT, run_id=run_id,
                                     file_name=result.file_name, artifact_type=ARTIFACT_TYPE)
        meta: dict[str, Any] = {
            "ok": True, "report": P.REPORT_NAME, "filters": filters.as_payload(), "stem": stem,
            "runId": run_id, "relativePath": artifact.relative_path, "fileName": artifact.display_name,
            "sha256": artifact.sha256, "rows": result.rows, "headerCheck": header_check(result.content),
            "bytes": artifact.size_bytes, "steps": list(result.steps), "startedAt": started,
            "finishedAt": datetime.now().isoformat(timespec="seconds"),
        }
        _atomic_write(runs_root(data_dir) / day / f"{stem}.json",
                      json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    progress("done", 100)
    return {**meta, "day": day, "reused": False}


# ── 自动导出（计划任务每小时调用一次） ─────────────────────────────


def load_auto_state(data_dir: Path) -> dict[str, Any]:
    try:
        state = json.loads((runs_root(data_dir) / AUTO_STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def auto_decision(config: Mapping[str, Any], state: Mapping[str, Any], now: datetime, data_dir: Path,
                  store: Any) -> str:
    """-> ``run`` 或不跑的原因（disabled / not_yet / done / stopped_today / attempts_exhausted）。"""
    auto = config["auto"]
    if not auto["enabled"]:
        return "disabled"
    if now.hour < auto["hour"]:
        return "not_yet"
    today = now.date()
    if find_cached(data_dir, store, today.isoformat(), default_filters(config, today)) is not None:
        return "done"
    if state.get("day") == today.isoformat():
        if state.get("errorCode") in AUTO_STOP_CODES:
            return "stopped_today"
        if int(state.get("attempts") or 0) >= AUTO_MAX_ATTEMPTS:
            return "attempts_exhausted"
    return "run"


def run_auto(
    data_dir: Path,
    *,
    now: datetime,
    store: Any,
    credential_provider: Any,
    session_factory: Callable[[], Any],
    base_url: str = P.DEFAULT_BASE_URL,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """One scheduled pass: decide, export with the saved defaults, record the outcome."""
    config = load_config(data_dir)
    state = load_auto_state(data_dir)
    decision = auto_decision(config, state, now, data_dir, store)
    if decision != "run":
        return {"decision": decision}
    today = now.date()
    attempts = int(state.get("attempts") or 0) + 1 if state.get("day") == today.isoformat() else 1
    record: dict[str, Any] = {"day": today.isoformat(), "attempts": attempts,
                              "at": now.isoformat(timespec="seconds")}
    try:
        meta = run_export(default_filters(config, today), data_dir=data_dir, store=store,
                          credential_provider=credential_provider,
                          session_factory=session_factory, today=today, base_url=base_url, sleep=sleep)
        record.update({"status": "ok", "stem": meta.get("stem"), "rows": meta.get("rows"),
                       "relativePath": meta.get("relativePath")})
    except TirError as exc:
        record.update({"status": "failed", "errorCode": exc.code, "error": str(exc)})
    _atomic_write(runs_root(data_dir) / AUTO_STATE_FILE, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    return {"decision": "run", **record}


# ── 任务 ─────────────────────────────────────────────────────────


def valid_task_id(task_id: str) -> bool:
    return bool(_TASK_ID_RE.match(task_id or ""))


def task_params(filters: P.ExportFilters, force: bool) -> dict[str, Any]:
    # 只放业务筛选；账号在执行时从域账号库读取，不进任务参数。
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
