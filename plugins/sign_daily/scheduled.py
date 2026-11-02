# -*- coding: utf-8 -*-
"""签署日报工作日 08:30 定时生成与当天补生成（DSH-V2-23）。

职责边界（勿破）：
- 本模块只做「一个作业」的业务：读已保存的 form → 先刷新 TDC 数据并等待结束
  → 用与 ``POST /generate`` **同一套** compose 核心生成 → 把结果写进插件表
  ``{prefix}scheduled_reports``（同槽 ``INSERT OR IGNORE``，不覆盖已生成内容）。
- 只生成、不发送：不生成 ``.eml``、不调用任何外发；``mail.build_eml`` 只在
  ``POST /eml`` 路由里使用。
- 处理器在调度线程运行，**不得依赖 Flask request/app 上下文**：这里不 import
  ``flask``、不 import ``web.*``、不 import 其他插件；所有宿主依赖（db、抓取任务
  执行器、归档服务）都由 ``plugins/sign_daily/backend.py`` 在注册时注入。
- 调度语义全部交给既有分层：到点槽由 ``services.schedule_policy`` 计算（日报绑定
  ``workdays_only=True``，周末不产槽；只补当天），槽唯一键与租约由
  ``services.schedule_slots`` 保证，处理器注册由 ``services.schedule_jobs`` 承载。
- 失败口径（主控冻结）：会话失效/刷新失败/刷新超时 → ``retry=True``，调度器按
  300 秒退避重试一次，第二次仍失败落 failed；compose 业务失败（NoData /
  MissingColumns / EmptyScope / WatchlistEmpty）→ 对应 error_code，不重试、不写表；
  未保存 form → ``not_configured``，不重试。失败一律不覆盖上次成功日报。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping

from core.time_rules import now_utc, pure_date
from services import data_model_watchlist as W
from services import schedule_policy as SP
from services import user_notifications
from services.deliverable_form_analysis import form_definition
from services.form_search import snapshot_schema
from services.schedule_jobs import JobOutcome

from . import mail as M
from . import rules as V
from . import service as S

logger = logging.getLogger("vse_toolbox.sign_daily.scheduled")

#: 日报作业的 project_id：槽键 ``projectId`` 段，与其它项目/作业互不干扰。
DAILY_PROJECT_ID = "sign-daily"

#: 未配置区域时的默认值（与既有 /generate 的默认一致）。
DEFAULT_REGION = "车体区域"
#: 默认称呼（与既有 /generate 的默认一致）。
DEFAULT_GREETING = "各位领导、同事："

#: 等待抓取任务结束的上限：13 分钟——须明显短于调度器槽租约（900 秒），
#: 给生成留余量，避免租约在 handler 仍运行时过期被他人回收（复审低风险项）。
REFRESH_TIMEOUT_SECONDS = 13 * 60
#: 等待抓取任务的轮询间隔。
REFRESH_POLL_SECONDS = 1.0

#: 会话失效判定：抓取任务只落 ``error_message``（自由文本已脱敏），因此只匹配本模块
#: 闭集指引文案里的固定片段，不解析上游自由文本；错误码仍如实记为 ``session_required``。
_SESSION_MARKERS = ("登录信息已失效", "凭据保护库")

#: 与 services/scheduled_archive_runner.py 的闭集指引码一致。
_REMEDY_TEXT = {
    "bind_domain_credential": "到「自动归档」页给数模设计审核报表任务选择统一域账号",
    "enable_job": "到「自动归档」页启用数模设计审核报表任务",
    "inspect_job_configuration": "到「自动归档」页检查数模设计审核报表任务的配置",
    "fill_watchlist": "同步范围是「仅关注清单」但清单为空，请先在交付物明细里加入要关注的流水单号",
    "save_domain_credential": "请登录 TDC 并勾选“保存至凭据保护库”",
    "refresh_domain_credential": "登录信息已失效，请重新登录并保存至凭据保护库",
    "wait_and_retry": "抓取任务正在运行，请稍后重试",
    "retry_or_narrow_filters": "请稍后重试",
}
_REMEDY_BY_ERROR_TYPE = {
    "job_not_ready": "inspect_job_configuration",
    "missing_job": "inspect_job_configuration",
    "credential_unavailable": "save_domain_credential",
    "credential_invalid": "refresh_domain_credential",
    "authentication_error": "refresh_domain_credential",
    "lease_busy": "wait_and_retry",
    "query_failed": "retry_or_narrow_filters",
    "timeout": "retry_or_narrow_filters",
}


# ── 失败与文案 ────────────────────────────────────────────────────────────────


class ReportFailure(Exception):
    """compose 业务失败：``status``/``code`` 与既有 /preview、/generate 响应一一对应。"""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)
        self.message = str(message)


class RefreshTimeout(Exception):
    """等待抓取任务结束超过上限（15 分钟）。"""


def sync_failure_message(result: Mapping[str, Any]) -> str:
    """归档任务结果 -> 给用户看的抓取失败原因（带闭集处理指引）。"""
    first = (result.get("results") or [{}])[0] if isinstance(result, Mapping) else {}
    reason = first.get("errorMessage") or first.get("errorType") or f"退出码 {result.get('exitCode')}"
    remedy = first.get("remedy") or _REMEDY_BY_ERROR_TYPE.get(str(first.get("errorType")))
    hint = _REMEDY_TEXT.get(str(remedy))
    return f"TDC 抓取未完成：{hint}（{reason}）" if hint else f"TDC 抓取未完成：{reason}"


def is_session_failure(message: Any) -> bool:
    """抓取失败文案是否属于「企业会话失效」（需要用户登录后重试）。

    只匹配本模块闭集指引文案里的固定片段，不猜测上游自由文本；无法判定时按
    普通刷新失败处理（同样 retry，但错误码如实记为 ``refresh_failed``）。
    """
    text = str(message or "")
    return any(marker in text for marker in _SESSION_MARKERS)


# ── 与 /preview、/generate 共用的 compose 核心 ────────────────────────────────


def headers_for(latest: Mapping[str, Any]) -> list[str]:
    """表单快照的表头（与既有 /state、/generate 的取法一致）。"""
    schema = snapshot_schema(latest)
    if not schema or not schema.get("headerRows"):
        schema = form_definition(S.FORM_KEY)
    return [str(h or "").strip() for h in schema["headerRows"][0]]


def watchlist_serials(db: Any) -> list[str]:
    """当前关注清单的流水单号（与 /state、/refresh 同一份权威数据）。"""
    return list(W.load_watchlist(db)[1])


def watchlist_scope(db: Any) -> str:
    """数模报表的同步范围（``all`` / ``watchlist``）。"""
    return W.load_watchlist(db)[0]


def scope_key(scope: S.Scope, watchlist_only: bool) -> str:
    """日报偏好按范围记住；格式与 v1 相同（不开关注清单时），v1 的收件人可以直接带过来。"""
    key: dict[str, Any] = {"projects": sorted(scope.projects), "departments": sorted(scope.departments)}
    if watchlist_only:
        key["watchlistOnly"] = True
    return json.dumps(key, ensure_ascii=False)


def preferences_for(config: Mapping[str, Any], key: str) -> dict[str, str]:
    """该范围记住的文案与收件人；没有时用 v1 同范围的收件人兜底。"""
    stored = dict((config.get("preferences") or {}).get(key) or {})
    legacy = (config.get("recipients") or {}).get(key) or {}
    stored.setdefault("to", legacy.get("to", ""))
    stored.setdefault("cc", legacy.get("cc", ""))
    return stored


def saved_form_request(
    config: Mapping[str, Any],
) -> tuple[S.Scope, bool, dict[str, str]] | None:
    """把已保存的 form 还原成生成请求；没有保存过范围时返回 ``None``。

    定时生成没有请求体，文案取该范围已保存的偏好（称呼/计划说明/飞书链接），
    区域取 form 里保存的值；与 /generate 的 ``_texts`` 默认值一致。
    """
    form = config.get("form") or {}
    projects = [str(item) for item in (form.get("projects") or []) if str(item).strip()]
    departments = [str(item) for item in (form.get("departments") or []) if str(item).strip()]
    if not projects and not departments:
        return None
    watchlist_only = bool(form.get("watchlistOnly"))
    scope = S.Scope(projects, departments)
    prefs = preferences_for(config, scope_key(scope, watchlist_only))
    texts = {
        "region": str(form.get("region") or DEFAULT_REGION).strip() or DEFAULT_REGION,
        "greeting": str(prefs.get("greeting") or "").strip() or DEFAULT_GREETING,
        "planText": str(prefs.get("planText") or ""),
        "feishuLink": str(prefs.get("feishuLink") or ""),
    }
    return scope, watchlist_only, texts


def build_report(
    *,
    db: Any,
    store: Any,
    snapshots: Any,
    effective: Callable[[Mapping[str, Any]], S.Effective],
    scope: S.Scope,
    watchlist_only: bool,
    texts: Mapping[str, str],
    save: bool,
    today: date,
    tz: Any = None,
) -> dict[str, Any]:
    """compose 业务核心（不调用 ``ctx.json_error``）：路由与定时作业共用。

    失败统一抛 :class:`ReportFailure`，由调用方映射成 HTTP 响应或 ``JobOutcome``；
    成功返回与 ``POST /generate`` 完全相同的响应体。
    """
    config = store.config()
    watch = watchlist_serials(db) if watchlist_only else None
    if watch is not None and not watch:
        raise ReportFailure(409, "WatchlistEmpty", "关注清单为空，请先在交付物明细里加入要关注的流水单号")
    try:
        source = S.load_source(db, headers_for, tz, watchlist_only=watchlist_only)
        result = S.compose(
            snapshots, source, scope, region=texts["region"], effective=effective(config),
            save_snapshot=save, today=today, watchlist=watch,
            max_gap_days=int(config["thresholds"]["baselineMaxGapDays"]),
            status_gate_enabled=bool(config.get("statusGateEnabled", True)),
        )
    except S.NoData as exc:
        raise ReportFailure(409, "NoData", str(exc)) from None
    except V.MissingColumnsError as exc:
        raise ReportFailure(422, "MissingColumns", str(exc)) from None
    except LookupError as exc:
        raise ReportFailure(404, "EmptyScope", str(exc)) from None
    key = scope_key(scope, watchlist_only)
    prefs = preferences_for(config, key)
    recipients = M.recipients(prefs.get("to"), prefs.get("cc"), config.get("addressBook"), M.owed_names(result))
    result.update({
        "scopeKey": key,
        "texts": dict(texts),
        "thresholds": config["thresholds"],
        "html": M.render_html(result, texts, config["thresholds"]),
        "text": M.render_text(result, texts),
        "chartsWithData": M.chart_keys_with_data(result),
        "recipients": {
            "to": [{"name": n, "address": a} for n, a in recipients["to"]],
            "cc": [{"name": n, "address": a} for n, a in recipients["cc"]],
            "added": [{"name": n, "address": a} for n, a in recipients["added"]],
            "missing": recipients["missing"], "ambiguous": recipients["ambiguous"],
        },
        "recipientsText": {"to": prefs.get("to", ""), "cc": prefs.get("cc", "")},
    })
    if save:
        store.save_config({
            "form": {"projects": scope.projects, "departments": scope.departments,
                     "watchlistOnly": watchlist_only, "region": texts["region"]},
            "preferences": {**(config.get("preferences") or {}), key: {**prefs, **texts}},
        })
    return result


# ── 抓取任务（复用既有 /refresh 的任务与等待语义）────────────────────────────


def refresh_scope_blocker(db: Any, watchlist_only: bool) -> str | None:
    """开关关但同步范围是「仅关注清单」时，抓不到全量数据（与 /refresh 同一判定）。"""
    if not watchlist_only and watchlist_scope(db) == W.SCOPE_WATCHLIST:
        return ("数模报表的同步范围是「仅关注清单」，抓不到全量数据：请到交付物明细把同步范围改为"
                "「全部表单」，或打开「只统计关注清单」")
    return None


def start_refresh(
    *,
    runner: Any,
    archive: Any,
    db: Any,
    watchlist_only: bool,
) -> tuple[dict[str, Any], bool]:
    """提交或复用既有刷新抓取任务；返回 ``(task_view, reused)``。

    与 ``POST /refresh`` 完全同一套逻辑：已有 queued/running 任务就复用，否则用
    ``service.make_refresh_worker`` 提交新任务。抓取失败原因由 worker 写进任务
    的 ``error_message``，调用方据此判定会话失效。
    """
    for task in runner.list_tasks(source=S.TASK_SOURCE, limit=10):
        if task.get("status") in ("queued", "running"):
            return S.task_view(task), True
    worker = S.make_refresh_worker(archive, db, sync_failure_message)
    task_id = runner.submit_task(S.TASK_TYPE, S.TASK_SOURCE, {}, worker_fn=worker)
    task = runner.get_task(task_id) or {"task_id": task_id, "status": "queued"}
    return S.task_view(task), False


def wait_refresh(
    runner: Any,
    task_id: Any,
    *,
    timeout: float = REFRESH_TIMEOUT_SECONDS,
    poll_seconds: float = REFRESH_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """同步等待抓取任务结束；超时抛 :class:`RefreshTimeout`，不伪报成功。"""
    deadline = monotonic() + timeout
    while True:
        task = runner.get_task(str(task_id or ""))
        if task is None:
            return {
                "taskId": task_id, "status": "failed", "stage": None, "percent": None,
                "error": "抓取任务不存在",
            }
        view = S.task_view(task)
        if view.get("status") not in ("queued", "running"):
            return view
        if monotonic() >= deadline:
            raise RefreshTimeout(str(task_id))
        sleep(poll_seconds)


# ── 定时生成结果表 ───────────────────────────────────────────────────────────


class ScheduledReportStore:
    """``{prefix}scheduled_reports``：每个槽最多一条成功生成结果（不覆盖）。"""

    def __init__(self, db: Any, prefix: str) -> None:
        self.db = db
        self.table = f"{prefix}scheduled_reports"

    def migration(self) -> tuple[int, Callable[[Any], None]]:
        """增量迁移 v4：只建新表，不改既有表（插件迁移只增不删）。"""
        table = self.table

        def v4(conn: Any) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "slot_key TEXT PRIMARY KEY NOT NULL, "
                "project_id TEXT NOT NULL, "
                "job_id TEXT NOT NULL, "
                "business_date TEXT NOT NULL, "
                "scheduled_time TEXT NOT NULL, "
                "generated_at TEXT NOT NULL, "
                "subject TEXT NOT NULL, "
                "data_date TEXT NOT NULL, "
                "html TEXT NOT NULL, "
                "text TEXT NOT NULL, "
                "status_gate_json TEXT NOT NULL, "
                "export_blocked INTEGER NOT NULL, "
                "result_json TEXT NOT NULL)"
            )

        return (4, v4)

    def save(self, *, slot_key: str, project_id: str, job_id: str, business_date: str,
             scheduled_time: str, generated_at: str, result: Mapping[str, Any]) -> bool:
        """写一条生成结果；同槽已存在时忽略（返回 ``False``），绝不覆盖。"""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO {self.table} ("
                "slot_key, project_id, job_id, business_date, scheduled_time, generated_at, "
                "subject, data_date, html, text, status_gate_json, export_blocked, result_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    slot_key,
                    project_id,
                    job_id,
                    business_date,
                    scheduled_time,
                    generated_at,
                    str(result.get("subject") or ""),
                    str(result.get("dataDate") or ""),
                    str(result.get("html") or ""),
                    str(result.get("text") or ""),
                    json.dumps(result.get("statusGate") or {}, ensure_ascii=False),
                    1 if result.get("exportBlocked") else 0,
                    json.dumps(dict(result), ensure_ascii=False),
                ),
            )
            return bool(cursor.rowcount and cursor.rowcount > 0)

    def get(self, slot_key: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.table} WHERE slot_key = ?", (str(slot_key),)
            ).fetchone()
        return report_row(row) if row is not None else None

    def latest(self) -> dict[str, Any] | None:
        """最近一次成功生成（按生成时间，其次插入顺序）。"""
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.table} ORDER BY generated_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return report_row(row) if row is not None else None


def report_row(row: Any) -> dict[str, Any]:
    """持久化行 -> 路由/作业共用的完整结果（html/text 等）。"""
    try:
        payload = json.loads(row["result_json"] or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update({
        "slotKey": row["slot_key"],
        "projectId": row["project_id"],
        "jobId": row["job_id"],
        "businessDate": row["business_date"],
        "scheduledTime": row["scheduled_time"],
        "generatedAt": row["generated_at"],
        "subject": row["subject"],
        "dataDate": row["data_date"],
        "html": row["html"],
        "text": row["text"],
        "statusGate": json.loads(row["status_gate_json"] or "{}"),
        "exportBlocked": bool(row["export_blocked"]),
    })
    return payload


def report_summary(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``GET /schedule`` 的 ``latest`` 摘要（不含 html/text 大字段）。"""
    if row is None:
        return None
    return {
        "slotKey": row["slotKey"],
        "generatedAt": row["generatedAt"],
        "subject": row["subject"],
        "dataDate": row["dataDate"],
        "statusGate": row["statusGate"],
        "exportBlocked": row["exportBlocked"],
    }


# ── 作业处理器 ───────────────────────────────────────────────────────────────


def utc_text(value: datetime) -> str:
    """aware datetime -> 固定宽度 UTC 文本（与槽表/快照表的写法一致）。"""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("generated_at 必须是带时区的 aware datetime")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DailyReportJob:
    """日报作业处理器：刷新 → 生成 → 落表；只生成不发送。

    所有外部依赖由 ``plugins/sign_daily/backend.py`` 注入（db、配置存储、快照存储、
    生效配置工厂、抓取执行器/归档服务工厂），因此可在调度线程运行且不碰 Flask。
    """

    def __init__(
        self,
        *,
        db: Any,
        store: Any,
        snapshots: Any,
        reports: ScheduledReportStore,
        effective: Callable[[Mapping[str, Any]], S.Effective],
        runner_factory: Callable[[], Any],
        archive_factory: Callable[[], Any],
        data_tz: Callable[[], Any] = lambda: None,
        clock: Callable[[], datetime] = now_utc,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        refresh_timeout: float = REFRESH_TIMEOUT_SECONDS,
        poll_seconds: float = REFRESH_POLL_SECONDS,
    ) -> None:
        self._db = db
        self._store = store
        self._snapshots = snapshots
        self._reports = reports
        self._effective = effective
        self._runner_factory = runner_factory
        self._archive_factory = archive_factory
        self._data_tz = data_tz
        self._clock = clock
        self._sleep = sleep
        self._monotonic = monotonic
        self._timeout = refresh_timeout
        self._poll = poll_seconds

    # ── 调度器入口 ────────────────────────────────────────────────────

    def handle(self, slot_row: Mapping[str, Any]) -> JobOutcome:
        """执行一个已领取的日报槽；``slot_row`` 是槽持久化行（camelCase 字段）。"""
        key = SP.slot_key_from_mapping(slot_row)
        config = self._store.config()
        request = saved_form_request(config)
        if request is None:
            # 没保存过生成范围：先让用户在页面上生成一次，定时任务不猜范围。
            return JobOutcome(False, "not_configured")
        scope, watchlist_only, texts = request

        outcome = self._refresh(watchlist_only)
        if outcome is not None:
            return outcome
        if not self._data_is_fresh(key.business_date, watchlist_only):
            # 刷新「成功」但没有产出覆盖当天的数据：不得用旧数据冒充当天。
            logger.warning(
                "scheduled daily report %s refresh produced no data for %s",
                key.as_text(),
                key.business_date.isoformat(),
            )
            return JobOutcome(False, "refresh_failed", retry=True)

        try:
            result = build_report(
                db=self._db,
                store=self._store,
                snapshots=self._snapshots,
                effective=self._effective,
                scope=scope,
                watchlist_only=watchlist_only,
                texts=texts,
                save=True,
                today=key.business_date,
                tz=self._data_tz(),
            )
        except ReportFailure as exc:
            # 业务失败（NoData/MissingColumns/EmptyScope/WatchlistEmpty）：不重试、不写表。
            logger.warning(
                "scheduled daily report %s failed: %s (%s)", key.as_text(), exc.code, exc.message
            )
            return JobOutcome(False, exc.code)

        saved = self._reports.save(
            slot_key=key.as_text(),
            project_id=key.project_id,
            job_id=key.job_id,
            business_date=key.business_date.isoformat(),
            scheduled_time=key.scheduled_time.strftime("%H:%M"),
            generated_at=utc_text(self._clock()),
            result=result,
        )
        if not saved:
            # 同槽已有一条成功结果：保持首次生成内容（INSERT OR IGNORE），本次仍算成功。
            logger.info("scheduled daily report %s already recorded; kept the first result", key.as_text())
        try:
            # 生成结果已写入 scheduled_reports：发布一次「日报已生成」托盘通知。
            data_date = str(result.get("dataDate") or key.business_date.isoformat())
            user_notifications.publish(
                "daily_ready",
                project_id=key.project_id,
                key=key.as_text(),
                title="日报已生成",
                body=f"数据日期 {data_date}，请到报告中心查看并发送",
            )
        except Exception:  # noqa: BLE001 - a balloon must never change the job outcome
            logger.warning("daily ready notification skipped for %s", key.as_text())
        return JobOutcome(True)

    # ── 刷新（数据新鲜度）────────────────────────────────────────────

    def _refresh(self, watchlist_only: bool) -> JobOutcome | None:
        """先刷新 TDC 数据并等待结束；失败返回 JobOutcome，成功返回 ``None``。

        不等待 09:00 同步：这里主动提交/复用日报的刷新抓取任务。刷新后仍拿不到
        当天数据时按刷新失败处理，绝不用旧数据冒充当天。
        """
        try:
            runner = self._runner_factory()
            archive = self._archive_factory()
        except LookupError:
            logger.warning("crawl task runner is unavailable; scheduled daily report cannot refresh")
            return JobOutcome(False, "refresh_failed", retry=True)

        blocker = refresh_scope_blocker(self._db, watchlist_only)
        if blocker is not None:
            logger.warning("scheduled daily report refresh blocked: %s", blocker)
            return JobOutcome(False, "refresh_failed", retry=True)

        try:
            view, _reused = start_refresh(
                runner=runner, archive=archive, db=self._db, watchlist_only=watchlist_only
            )
            view = wait_refresh(
                runner,
                view.get("taskId"),
                timeout=self._timeout,
                poll_seconds=self._poll,
                sleep=self._sleep,
                monotonic=self._monotonic,
            )
        except RefreshTimeout:
            logger.warning("scheduled daily report refresh timed out")
            return JobOutcome(False, "refresh_timeout", retry=True)
        except Exception as exc:  # 提交失败（线程池/DB）也算刷新失败，可重试一次
            logger.warning("scheduled daily report refresh could not start: %s", type(exc).__name__)
            return JobOutcome(False, "refresh_failed", retry=True)

        if view.get("status") != "succeeded":
            code = "session_required" if is_session_failure(view.get("error")) else "refresh_failed"
            logger.warning(
                "scheduled daily report refresh failed: status=%s code=%s",
                view.get("status"), code,
            )
            return JobOutcome(False, code, retry=True)

        return None

    # ── 当天数据判定 ─────────────────────────────────────────────────

    def _data_is_fresh(self, business_date: date, watchlist_only: bool = False) -> bool:
        """生成将使用的表单快照的数据日期必须覆盖业务日期（刷新后仍旧 = 失败）。

        取快照口径与 ``S.load_source`` 一致：关注清单模式用最新快照，否则只认
        全量快照；否则一份更新的关注清单快照会让旧全量数据蒙混过关。
        """
        if watchlist_only:
            latest = self._db.get_latest_deliverable_form_snapshot(S.FORM_KEY)
        else:
            latest = W.latest_full_snapshot(self._db, S.FORM_KEY)
        if latest is None:
            return False
        data_date = S.data_date_of(latest.get("snapshot_at"), self._data_tz())
        if data_date is None:
            return False
        return data_date >= pure_date(business_date)


__all__ = [
    "DAILY_PROJECT_ID",
    "DEFAULT_GREETING",
    "DEFAULT_REGION",
    "DailyReportJob",
    "REFRESH_POLL_SECONDS",
    "REFRESH_TIMEOUT_SECONDS",
    "RefreshTimeout",
    "ReportFailure",
    "ScheduledReportStore",
    "build_report",
    "headers_for",
    "is_session_failure",
    "preferences_for",
    "refresh_scope_blocker",
    "report_row",
    "report_summary",
    "saved_form_request",
    "scope_key",
    "start_refresh",
    "sync_failure_message",
    "utc_text",
    "wait_refresh",
    "watchlist_scope",
    "watchlist_serials",
]
