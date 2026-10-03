# -*- coding: utf-8 -*-
"""签署日报 plugin backend. Routes are mounted at /api/p/sign-daily/.

- GET  state       数据时间、可选项目/部门、插件配置
- POST config      保存配置（部分字段）
- POST refresh     触发一次 TDC 数模设计审核流程归档同步（全量抓取）
- POST generate    生成日报预览，并按 范围+日期 存当天汇总（日变化基线）
- POST eml         生成 .eml 草稿下载（不改汇总）

v2.0（口径在 rules.py，取数与存储在 service.py；前端切换前与 v1 并存）：

- GET  v2/state                 数据日期、可选项目/归属科室（A9）、种子版本
- POST v2/preview               预览，不写快照
- POST v2/generate              生成并写当天零件级快照（D1）
- POST v2/long-cycle            长周期复核「确认并记住」
- POST v2/long-cycle/clear      按项目清空长周期结论
- POST v2/refresh               后台抓取；已有抓取在跑时复用它
- GET  v2/refresh/<task_id>     抓取进度

数据只读最新的 tdc_data_model 表单快照；v1 计算口径在 report.py。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Mapping
from urllib.parse import quote

from flask import Response, request

from services.deliverable_form_analysis import form_definition

from . import report as R
from . import rules as V
from . import service as S

FORM_KEY = "tdc_data_model"
ARCHIVE_JOB_KEY = "tdc_data_model"
_TEXT_LIMIT = 20000
# 与 services/scheduled_archive_runner.py 的闭集指引码一致；任务在「自动归档」页维护。
_REMEDY_TEXT = {
    "bind_domain_credential": "到「自动归档」页给数模设计审核报表任务选择统一域账号",
    "enable_job": "到「自动归档」页启用数模设计审核报表任务",
    "inspect_job_configuration": "到「自动归档」页检查数模设计审核报表任务的配置",
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
_LIST_LIMIT = 2000
#: 数据日期换算用的时区；None 取本机时区（测试里固定）。
_DATA_TZ = None


def _today() -> date:
    return date.today()


def _default_config() -> dict[str, Any]:
    return {
        "roleDepartments": dict(R.DEFAULT_ROLE_DEPARTMENTS),
        "personDepartments": {},
        # v2 A11：未在册人员 -> 指定区域
        "personAreas": {},
        "longCycleNames": [],
        # 项目 -> {零件名称: 是否长周期}，生成前勾选确认的结果
        "longCycleConfirmed": {},
        # 范围 key -> {"to": 粘贴文本, "cc": 粘贴文本}
        "recipients": {},
        "addressBook": "",
        "form": {"projects": [], "departments": [], "region": "车体区域", "planText": "", "feishuLink": ""},
    }


# ── 校验 ────────────────────────────────────────────────────────────


class _Invalid(ValueError):
    pass


def _str(value: Any, name: str, limit: int = _TEXT_LIMIT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _Invalid(f"{name} 必须是文本")
    if len(value) > limit:
        raise _Invalid(f"{name} 过长")
    return value


def _str_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _LIST_LIMIT:
        raise _Invalid(f"{name} 必须是文本数组")
    return [_str(item, name, 200).strip() for item in value if _str(item, name, 200).strip()]


def _str_map(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > _LIST_LIMIT:
        raise _Invalid(f"{name} 必须是对象")
    return {_str(k, name, 200).strip(): _str(v, name, 200).strip() for k, v in value.items() if str(k).strip()}


def sync_failure_message(result: Mapping[str, Any]) -> str:
    """归档任务结果 -> 给用户看的抓取失败原因（带闭集处理指引）。"""
    first = (result.get("results") or [{}])[0] if isinstance(result, Mapping) else {}
    reason = first.get("errorMessage") or first.get("errorType") or f"退出码 {result.get('exitCode')}"
    remedy = first.get("remedy") or _REMEDY_BY_ERROR_TYPE.get(str(first.get("errorType")))
    hint = _REMEDY_TEXT.get(str(remedy))
    return f"TDC 抓取未完成：{hint}（{reason}）" if hint else f"TDC 抓取未完成：{reason}"


def _validate_config_patch(patch: Any) -> dict[str, Any]:
    if not isinstance(patch, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    allowed = set(_default_config())
    unknown = set(patch) - allowed
    if unknown:
        raise _Invalid("未知配置项：" + "、".join(sorted(unknown)))
    clean: dict[str, Any] = {}
    if "roleDepartments" in patch:
        clean["roleDepartments"] = _str_map(patch["roleDepartments"], "角色列→科室")
    if "personDepartments" in patch:
        clean["personDepartments"] = _str_map(patch["personDepartments"], "人员→科室")
    if "personAreas" in patch:
        clean["personAreas"] = _str_map(patch["personAreas"], "未在册人员→区域")
    if "longCycleNames" in patch:
        clean["longCycleNames"] = _str_list(patch["longCycleNames"], "长周期件清单")
    if "longCycleConfirmed" in patch:
        value = patch["longCycleConfirmed"]
        if not isinstance(value, Mapping):
            raise _Invalid("长周期确认结果必须是对象")
        clean["longCycleConfirmed"] = {
            _str(project, "项目", 200): {
                _str(part, "零件名称", 200): bool(flag) for part, flag in dict(parts or {}).items()
            }
            for project, parts in value.items()
        }
    if "recipients" in patch:
        value = patch["recipients"]
        if not isinstance(value, Mapping):
            raise _Invalid("收件人必须是对象")
        clean["recipients"] = {
            _str(key, "范围", 2000): {
                "to": _str((item or {}).get("to"), "收件人"),
                "cc": _str((item or {}).get("cc"), "抄送"),
            }
            for key, item in value.items()
        }
    if "addressBook" in patch:
        clean["addressBook"] = _str(patch["addressBook"], "通讯录", 200000)
    if "form" in patch:
        clean["form"] = _validate_form(patch["form"])
    return clean


def _validate_form(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    region = _str(value.get("region"), "区域名", 100).strip() or "车体区域"
    return {
        "projects": _str_list(value.get("projects"), "项目/车型"),
        "departments": _str_list(value.get("departments"), "部门"),
        "region": region,
        "planText": _str(value.get("planText"), "计划/超期说明"),
        "feishuLink": _str(value.get("feishuLink"), "飞书链接", 2000),
    }


def scope_key(projects: list[str], departments: list[str]) -> str:
    return json.dumps({"projects": sorted(projects), "departments": sorted(departments)}, ensure_ascii=False)


# ── 存储 ────────────────────────────────────────────────────────────


class Store:
    def __init__(self, db: Any, prefix: str):
        self.db = db
        self.config_table = f"{prefix}config"
        self.summary_table = f"{prefix}daily_summary"

    def migrations(self) -> list[tuple[int, Any]]:
        def v1(conn) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.config_table} ("
                "key TEXT PRIMARY KEY NOT NULL, value_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.summary_table} ("
                "scope_key TEXT NOT NULL, report_date TEXT NOT NULL, summary_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "PRIMARY KEY (scope_key, report_date))"
            )

        return [(1, v1)]

    def config(self) -> dict[str, Any]:
        config = _default_config()
        with self.db.get_connection() as conn:
            for row in conn.execute(f"SELECT key, value_json FROM {self.config_table}"):
                if row["key"] in config:
                    try:
                        config[row["key"]] = json.loads(row["value_json"])
                    except ValueError:
                        pass
        return config

    def save_config(self, patch: Mapping[str, Any]) -> None:
        with self.db.get_connection() as conn:
            for key, value in patch.items():
                conn.execute(
                    f"INSERT INTO {self.config_table} (key, value_json) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    def previous_summary(self, key: str, today: date) -> tuple[dict[str, Any] | None, date | None]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT report_date, summary_json FROM {self.summary_table} "
                "WHERE scope_key = ? AND report_date < ? ORDER BY report_date DESC LIMIT 1",
                (key, today.isoformat()),
            ).fetchone()
        if row is None:
            return None, None
        return json.loads(row["summary_json"]), date.fromisoformat(row["report_date"])

    def save_summary(self, key: str, today: date, summary: Mapping[str, Any]) -> None:
        # 同一天同一范围多次生成只保留最后一次。
        with self.db.get_connection() as conn:
            conn.execute(
                f"INSERT INTO {self.summary_table} (scope_key, report_date, summary_json) VALUES (?, ?, ?) "
                "ON CONFLICT(scope_key, report_date) DO UPDATE SET summary_json = excluded.summary_json, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (key, today.isoformat(), json.dumps(summary, ensure_ascii=False)),
            )


# ── 数据 ────────────────────────────────────────────────────────────


class NoData(LookupError):
    pass


def _headers(latest: Mapping[str, Any]) -> list[str]:
    schema = latest.get("schema")
    if schema is None and latest.get("schema_json"):
        try:
            schema = json.loads(latest["schema_json"])
        except ValueError:
            schema = None
    if not isinstance(schema, Mapping) or not schema.get("headerRows"):
        schema = form_definition(FORM_KEY)
    return [str(h or "").strip() for h in schema["headerRows"][0]]


def load_flows(db: Any) -> tuple[list[R.Flow], dict[str, Any]]:
    latest = db.get_latest_deliverable_form_snapshot(FORM_KEY)
    if latest is None:
        raise NoData("还没有 TDC 数模设计审核流程数据，请先点「一键生成」抓取")
    headers = _headers(latest)
    R.check_columns(headers)
    rows = db.list_deliverable_form_snapshot_rows(int(latest["id"]))
    records = [dict(zip(headers, row.get("values") or [])) for row in rows]
    meta = {"updatedAt": latest.get("snapshot_at"), "rowCount": int(latest.get("row_count") or 0)}
    return R.build_flows(records), meta


def _address_book(config: Mapping[str, Any]) -> list[tuple[str, str]]:
    entries = R.parse_recipients(config.get("addressBook") or "")
    for item in (config.get("recipients") or {}).values():
        entries += R.parse_recipients(item.get("to")) + R.parse_recipients(item.get("cc"))
    return entries


def compose(db: Any, config: Mapping[str, Any], form: Mapping[str, Any], today: date, store: Store) -> dict[str, Any]:
    flows, meta = load_flows(db)
    flows = R.filter_scope(flows, form["projects"], form["departments"])
    if not flows:
        raise LookupError("范围内没有 3D单")

    notices: list[dict[str, Any]] = []
    long_names = config.get("longCycleNames") or []
    confirmed_by_project = config.get("longCycleConfirmed") or {}
    pending_hits: list[dict[str, str]] = []
    if not long_names:
        notices.append({"kind": "longCycleMissing", "text": "长周期件清单还没配置，长周期两行先显示为 0。"})
    else:
        for project in sorted({f.project for f in flows}):
            parts = {p for f in flows if f.project == project for p in f.parts}
            decided = confirmed_by_project.get(project) or {}
            for part, matched in sorted(R.long_cycle_hits(parts, long_names).items()):
                if part not in decided:
                    pending_hits.append({"project": project, "part": part, "matched": matched})
        if pending_hits:
            notices.append({"kind": "longCycleConfirm", "text": f"有 {len(pending_hits)} 个零件名称疑似长周期件，确认后计入长周期。"})
    for flow in flows:
        R.mark_long_cycle([flow], confirmed_by_project.get(flow.project) or {})

    key = scope_key(form["projects"], form["departments"])
    previous, previous_date = store.previous_summary(key, today)
    result = R.build_report(
        flows,
        projects=form["projects"],
        today=today,
        region=form["region"],
        plan_text=form["planText"],
        feishu_link=form["feishuLink"],
        role_departments=config.get("roleDepartments") or R.DEFAULT_ROLE_DEPARTMENTS,
        person_departments=config.get("personDepartments") or {},
        previous=previous,
        previous_date=previous_date,
    )
    if result["unassigned"]:
        notices.append({
            "kind": "unassigned",
            "text": "以下未签人没有归到科室，请在设置里补「人员→科室」：" + "、".join(result["unassigned"]),
        })

    recipients_text = (config.get("recipients") or {}).get(key) or {}
    owed_names = [p["name"] for groups in result["owed"].values() for g in groups for p in g["people"]]
    recipients = R.recipients_for(
        recipients_text.get("to", ""), recipients_text.get("cc", ""), _address_book(config), owed_names
    )
    result.update({
        "scopeKey": key,
        "data": meta,
        "notices": notices,
        "longCycleHits": pending_hits,
        "recipients": {k: [{"name": n, "address": a} for n, a in v] for k, v in recipients.items()},
        "recipientsText": {"to": recipients_text.get("to", ""), "cc": recipients_text.get("cc", "")},
        "previousDate": previous_date.isoformat() if previous_date else None,
        "reportDate": today.isoformat(),
    })
    return result


# ── 路由 ────────────────────────────────────────────────────────────


def register(host):
    ctx = host.context
    bp = host.blueprint
    store = Store(ctx.db, host.table_prefix)
    snapshots = S.SnapshotStore(ctx.db, host.table_prefix)
    host.migrate([*store.migrations(), snapshots.migration()])

    def body() -> Any:
        return request.get_json(silent=True)

    @bp.get("/state")
    def state():
        config = store.config()
        try:
            flows, meta = load_flows(ctx.db)
            options, data_error = R.scope_options(flows), None
        except NoData as exc:
            meta, options, data_error = None, {"projects": [], "departments": []}, str(exc)
        except R.MissingColumnsError as exc:
            meta, options, data_error = None, {"projects": [], "departments": []}, str(exc)
        return ctx.json_ok({"data": meta, "dataError": data_error, "options": options, "config": config})

    @bp.post("/config")
    def save_config():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        try:
            patch = _validate_config_patch(body())
        except _Invalid as exc:
            return ctx.json_error(400, "ValidationError", str(exc))
        store.save_config(patch)
        return ctx.json_ok({"config": store.config()})

    @bp.post("/refresh")
    def refresh():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        try:
            service = ctx.service("scheduled_archive_admin")
            result = service.sync_now(ARCHIVE_JOB_KEY)
        except KeyError:
            return ctx.json_error(409, "SyncNotReady", "未找到 TDC 数模设计审核流程归档任务")
        except LookupError as exc:
            return ctx.json_error(409, "SyncNotReady", str(exc))
        except Exception as exc:  # noqa: BLE001 - 抓取失败要带原因回到页面
            return ctx.json_error(502, "SyncFailed", ctx.redact(f"TDC 抓取失败：{exc}"))
        first = (result.get("results") or [{}])[0] if isinstance(result, Mapping) else {}
        if not isinstance(result, Mapping) or result.get("exitCode") != 0 or first.get("outcome") != "completed":
            message = sync_failure_message(result if isinstance(result, Mapping) else {})
            return ctx.json_error(502, "SyncFailed", ctx.redact(message))
        latest = ctx.db.get_latest_deliverable_form_snapshot(FORM_KEY)
        return ctx.json_ok({"updatedAt": latest.get("snapshot_at") if latest else None})

    def _compose(save: bool):
        guard = ctx.local_guard()
        if guard is not None:
            return None, guard
        try:
            form = _validate_form(body())
        except _Invalid as exc:
            return None, ctx.json_error(400, "ValidationError", str(exc))
        config = store.config()
        today = _today()
        try:
            result = compose(ctx.db, config, form, today, store)
        except NoData as exc:
            return None, ctx.json_error(409, "NoData", str(exc))
        except R.MissingColumnsError as exc:
            return None, ctx.json_error(422, "MissingColumns", str(exc))
        except LookupError as exc:
            return None, ctx.json_error(404, "EmptyScope", str(exc))
        if save:
            store.save_config({"form": form})
            store.save_summary(result["scopeKey"], today, result["summary"])
        return result, None

    @bp.post("/generate")
    def generate():
        result, error = _compose(save=True)
        return error if error is not None else ctx.json_ok(result)

    @bp.post("/eml")
    def eml():
        result, error = _compose(save=False)
        if error is not None:
            return error
        recipients = result["recipients"]
        payload = R.build_eml(
            subject=result["subject"],
            to=[(r["name"], r["address"]) for r in recipients["to"]],
            cc=[(r["name"], r["address"]) for r in recipients["cc"]],
            text_body=result["text"],
            html_body=result["html"],
        )
        filename = f"{result['subject']}.eml"
        response = Response(payload, mimetype="message/rfc822")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=\"daily-report.eml\"; filename*=UTF-8''{quote(filename)}"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    _register_v2(host, store, snapshots, body)


# ── v2.0 路由 ───────────────────────────────────────────────────────


def _validate_scope(value: Any) -> tuple[S.Scope, str]:
    if not isinstance(value, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    scope = S.Scope(_str_list(value.get("projects"), "项目/车型"), _str_list(value.get("departments"), "归属科室"))
    region = _str(value.get("region"), "区域名", 100).strip() or "车体区域"
    return scope, region


def _validate_review(value: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(value, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    project = _str(value.get("project"), "项目", 200).strip()
    items = value.get("items")
    if not project:
        raise _Invalid("缺少项目")
    if not isinstance(items, list) or not items or len(items) > _LIST_LIMIT:
        raise _Invalid("复核结果必须是非空数组")
    clean = []
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("include"), bool):
            raise _Invalid("每项复核结果要有零件键和是否纳入")
        key = V.conclusion_key(_str(item.get("key"), "零件键", 200))
        if not key:
            raise _Invalid("零件键不能为空")
        clean.append({"key": key, "include": item["include"]})
    return project, clean


def _register_v2(host, store: Store, snapshots: S.SnapshotStore, body) -> None:  # type: ignore[no-untyped-def]
    ctx = host.context
    bp = host.blueprint

    def source() -> S.SourceData:
        return S.load_source(ctx.db, _headers, _DATA_TZ)

    @bp.get("/v2/state")
    def v2_state():
        try:
            data = source()
            parsed = V.build_flows(data.records)
            context = S._Context(snapshots, [], {})
            meta = {"dataDate": data.data_date.isoformat(), "snapshotAt": data.snapshot_at}
            options, error = S.scope_options(parsed.flows, context), None
        except (S.NoData, V.MissingColumnsError) as exc:
            meta, options, error = None, {"projects": [], "departments": list(V.CURRENT_DEPARTMENTS)}, str(exc)
        return ctx.json_ok({
            "data": meta, "dataError": error, "options": options,
            "form": store.config().get("form"), "seedVersion": S.seed_version(),
        })

    def compose(save: bool):
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        try:
            scope, region = _validate_scope(body())
        except _Invalid as exc:
            return ctx.json_error(400, "ValidationError", str(exc))
        config = store.config()
        try:
            result = S.compose(
                snapshots, source(), scope, region=region,
                person_areas=config.get("personAreas") or {}, save_snapshot=save, today=_today(),
            )
        except S.NoData as exc:
            return ctx.json_error(409, "NoData", str(exc))
        except V.MissingColumnsError as exc:
            return ctx.json_error(422, "MissingColumns", str(exc))
        except LookupError as exc:
            return ctx.json_error(404, "EmptyScope", str(exc))
        if save:
            form = dict(config.get("form") or {})
            form.update({"projects": scope.projects, "departments": scope.departments, "region": region})
            store.save_config({"form": form})
        return ctx.json_ok(result)

    @bp.post("/v2/preview")
    def v2_preview():
        return compose(save=False)

    @bp.post("/v2/generate")
    def v2_generate():
        return compose(save=True)

    @bp.post("/v2/long-cycle")
    def v2_long_cycle_confirm():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        try:
            project, items = _validate_review(body())
        except _Invalid as exc:
            return ctx.json_error(400, "ValidationError", str(exc))
        classified = S.classify_keys(item["key"] for item in items)
        snapshots.save_conclusions(project, [
            {**item, "autoResult": classified[item["key"]].result, "rule": classified[item["key"]].rule_id}
            for item in items
        ])
        return ctx.json_ok({"project": project, "saved": len(items)})

    @bp.post("/v2/long-cycle/clear")
    def v2_long_cycle_clear():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        value = body()
        try:
            project = _str((value or {}).get("project") if isinstance(value, Mapping) else None, "项目", 200).strip()
        except _Invalid as exc:
            return ctx.json_error(400, "ValidationError", str(exc))
        if not project:
            return ctx.json_error(400, "ValidationError", "缺少项目")
        return ctx.json_ok({"project": project, "cleared": snapshots.clear_conclusions(project)})

    @bp.post("/v2/refresh")
    def v2_refresh():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        try:
            runner = ctx.service("crawl_task_runner")
            archive = ctx.service("scheduled_archive_admin")
        except LookupError as exc:
            return ctx.json_error(409, "SyncNotReady", str(exc))
        for task in runner.list_tasks(source=S.TASK_SOURCE, limit=10):
            if task.get("status") in ("queued", "running"):
                return ctx.json_ok({**S.task_view(task), "reused": True})
        worker = S.make_refresh_worker(archive, ctx.db, sync_failure_message)
        task_id = runner.submit_task(S.TASK_TYPE, S.TASK_SOURCE, {}, worker_fn=worker)
        task = runner.get_task(task_id) or {"task_id": task_id, "status": "queued"}
        return ctx.json_ok({**S.task_view(task), "reused": False})

    @bp.get("/v2/refresh/<task_id>")
    def v2_refresh_status(task_id: str):
        if not S.valid_task_id(task_id):
            return ctx.json_error(400, "ValidationError", "无效的任务编号")
        try:
            runner = ctx.service("crawl_task_runner")
        except LookupError as exc:
            return ctx.json_error(409, "SyncNotReady", str(exc))
        task = runner.get_task(task_id)
        if task is None or task.get("source") != S.TASK_SOURCE:
            return ctx.json_error(404, "NotFound", "没有这个抓取任务")
        view = S.task_view(task)
        if view["error"]:
            view["error"] = ctx.redact(str(view["error"]))
        return ctx.json_ok(view)
