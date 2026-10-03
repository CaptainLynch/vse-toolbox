# -*- coding: utf-8 -*-
"""签署日报插件后端（3D单签署进展日报 需求规格 v2.0）。路由挂在 /api/p/sign-daily/ 下。

口径在 ``rules.py``（纯函数），邮件正文与 .eml 在 ``mail.py``，取数、快照与基线在 ``service.py``，
花名册与长周期规则的种子叠加、导入与备份在 ``settings.py``。所有写路由先过 ``ctx.local_guard()``。

日报：
- GET  state                    数据时间、可选项目与归属科室（A9）、上次的选择与偏好、关注清单概况
- POST config                   保存偏好（按范围记住的文案与收件人、通讯录、阈值、未在册人员区域、区域显示名）
- POST preview                  预览，不写快照
- POST generate                 生成并写当天零件级快照（D1），记住本次选择
- POST eml                      下载 .eml 草稿（三张图由前端 Canvas 画好后以 PNG 传入，按 Content-ID 内嵌）
- POST refresh / GET refresh/<task_id>   后台抓取与进度（R1、R3）

长周期复核（§7）：GET long-cycle?project=、POST long-cycle（确认并记住 / 单条改判）、POST long-cycle/clear

设置（§7 M1–M8），dataset 是 roster、rules 或 vocabulary：
- GET  settings/<dataset>       生效值与来源、种子与本地都改过的条目、备份列表
- POST settings/roster/person、settings/roster/revert、settings/rules/rule、settings/rules/revert、settings/vocabulary
- POST settings/<dataset>/import   CSV 导入：commit=false 只做校验与差异预览；commit=true 单事务提交并先备份
- GET  settings/<dataset>.csv      导出生效值（与导入格式相同）
- POST settings/<dataset>/restore、settings/<dataset>/reset（恢复内置种子）
"""

from __future__ import annotations

import base64
import binascii
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from flask import Response, request

from services import data_model_watchlist as W
from services.deliverable_form_analysis import form_definition
from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview

from . import mail as M
from . import rules as V
from . import service as S
from . import settings as SET

_TEXT_LIMIT = 20000
_LIST_LIMIT = 2000
_CSV_LIMIT = 2 * 1024 * 1024
_XLSX_LIMIT = 5 * 1024 * 1024
_IMPORT_MAX_ROWS = 5000
#: 数据日期换算用的时区；None 取本机时区（测试里固定）。
_DATA_TZ = None

# 与 services/scheduled_archive_runner.py 的闭集指引码一致。
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
_DEFAULT_THRESHOLDS = {"warnDays": 7, "overdueDays": 14, "baselineMaxGapDays": S.BASELINE_MAX_GAP_DAYS}
_DEFAULT_REGION = "车体区域"


def _today() -> date:
    return date.today()


def _default_config() -> dict[str, Any]:
    return {
        # A11：未在册人员 -> 指定区域
        "personAreas": {},
        # 角色列配置：外部列 -> 区域显示名（默认 空调电子 -> 空调电子/ES科）
        "areaNames": dict(V.AREA_DISPLAY),
        "addressBook": "",
        "thresholds": dict(_DEFAULT_THRESHOLDS),
        # 范围 key -> {region, greeting, planText, feishuLink, to, cc}
        "preferences": {},
        "form": {"projects": [], "departments": [], "watchlistOnly": False, "region": _DEFAULT_REGION},
        # v1 的「范围 key -> {to, cc}」，只读兜底（同范围的收件人带到 v2）
        "recipients": {},
    }


def sync_failure_message(result: Mapping[str, Any]) -> str:
    """归档任务结果 -> 给用户看的抓取失败原因（带闭集处理指引）。"""
    first = (result.get("results") or [{}])[0] if isinstance(result, Mapping) else {}
    reason = first.get("errorMessage") or first.get("errorType") or f"退出码 {result.get('exitCode')}"
    remedy = first.get("remedy") or _REMEDY_BY_ERROR_TYPE.get(str(first.get("errorType")))
    hint = _REMEDY_TEXT.get(str(remedy))
    return f"TDC 抓取未完成：{hint}（{reason}）" if hint else f"TDC 抓取未完成：{reason}"


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


def _str_list(value: Any, name: str, limit: int = _LIST_LIMIT) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise _Invalid(f"{name} 必须是文本数组")
    out = []
    for item in value:
        text = _str(item, name, 200).strip()
        if text and text not in out:
            out.append(text)
    return out


def _str_map(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > _LIST_LIMIT:
        raise _Invalid(f"{name} 必须是对象")
    return {
        _str(k, name, 200).strip(): _str(v, name, 200).strip()
        for k, v in value.items() if str(k).strip() and str(v or "").strip()
    }


def _int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _Invalid(f"{name} 必须是 {low}–{high} 的整数")
    return value


def _texts(value: Mapping[str, Any]) -> dict[str, str]:
    return {
        "region": _str(value.get("region"), "区域名", 100).strip() or _DEFAULT_REGION,
        "greeting": _str(value.get("greeting"), "称呼", 200).strip() or "各位领导、同事：",
        "planText": _str(value.get("planText"), "计划/超期说明"),
        "feishuLink": _str(value.get("feishuLink"), "飞书链接", 2000),
    }


def _validate_request(value: Any) -> tuple[S.Scope, bool, dict[str, str]]:
    if not isinstance(value, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    scope = S.Scope(_str_list(value.get("projects"), "项目/车型"), _str_list(value.get("departments"), "归属科室"))
    watchlist_only = value.get("watchlistOnly", False)
    if not isinstance(watchlist_only, bool):
        raise _Invalid("只统计关注清单 必须是布尔值")
    return scope, watchlist_only, _texts(value)


def scope_key(scope: S.Scope, watchlist_only: bool) -> str:
    """日报偏好按范围记住；格式与 v1 相同（不开关注清单时），v1 的收件人可以直接带过来。"""
    key: dict[str, Any] = {"projects": sorted(scope.projects), "departments": sorted(scope.departments)}
    if watchlist_only:
        key["watchlistOnly"] = True
    return json.dumps(key, ensure_ascii=False)


def _validate_config_patch(patch: Any) -> dict[str, Any]:
    if not isinstance(patch, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    allowed = {"personAreas", "areaNames", "addressBook", "thresholds", "preferences"}
    unknown = set(patch) - allowed
    if unknown:
        raise _Invalid("未知配置项：" + "、".join(sorted(unknown)))
    clean: dict[str, Any] = {}
    if "personAreas" in patch:
        clean["personAreas"] = {
            V.normalize_name(name)[0]: area for name, area in _str_map(patch["personAreas"], "未在册人员→区域").items()
        }
    if "areaNames" in patch:
        names = _str_map(patch["areaNames"], "区域显示名")
        unknown_columns = set(names) - (set(V.COUNTERSIGN_COLUMNS) - set(V.INTERNAL_COLUMNS))
        if unknown_columns:
            raise _Invalid("区域显示名只能改外部会签列：" + "、".join(sorted(unknown_columns)))
        clean["areaNames"] = names
    if "addressBook" in patch:
        clean["addressBook"] = _str(patch["addressBook"], "通讯录", 200000)
    if "thresholds" in patch:
        value = patch["thresholds"]
        if not isinstance(value, Mapping):
            raise _Invalid("阈值必须是对象")
        warn = _int(value.get("warnDays"), "预警天数", 1, 365)
        overdue = _int(value.get("overdueDays"), "超期天数", 1, 365)
        if overdue < warn:
            raise _Invalid("超期天数不能小于预警天数")
        clean["thresholds"] = {
            "warnDays": warn, "overdueDays": overdue,
            "baselineMaxGapDays": _int(value.get("baselineMaxGapDays", S.BASELINE_MAX_GAP_DAYS),
                                       "基线最长间隔天数", 1, 90),
        }
    if "preferences" in patch:
        value = patch["preferences"]
        if not isinstance(value, Mapping) or len(value) > 500:
            raise _Invalid("偏好必须是对象")
        clean["preferences"] = {}
        for key, item in value.items():
            if not isinstance(item, Mapping):
                raise _Invalid("偏好必须是对象")
            clean["preferences"][_str(key, "范围", 4000)] = {
                **_texts(item),
                "to": _str(item.get("to"), "收件人"),
                "cc": _str(item.get("cc"), "抄送"),
            }
    return clean


# ── 配置存储（插件 KV）───────────────────────────────────────────────


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
            # v1 的日汇总表：v2 改用零件级快照（service.SnapshotStore），旧表保留不读。
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
        form = config.get("form") or {}
        config["form"] = {**_default_config()["form"], **{k: v for k, v in form.items()
                                                          if k in _default_config()["form"]}}
        config["thresholds"] = {**_DEFAULT_THRESHOLDS, **(config.get("thresholds") or {})}
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


def preferences_for(config: Mapping[str, Any], key: str) -> dict[str, str]:
    """该范围记住的文案与收件人；没有时用 v1 同范围的收件人兜底。"""
    stored = dict((config.get("preferences") or {}).get(key) or {})
    legacy = (config.get("recipients") or {}).get(key) or {}
    stored.setdefault("to", legacy.get("to", ""))
    stored.setdefault("cc", legacy.get("cc", ""))
    return stored


# ── 数据 ────────────────────────────────────────────────────────────


def import_rows(value: Mapping[str, Any]) -> str | list[list[Any]]:
    """导入来源：CSV 原文，或 base64 的 xlsx（宿主自带的无依赖读取器，只读第一个工作表，§7）。"""
    if value.get("xlsx") is not None:
        raw = _str(value.get("xlsx"), "xlsx", _XLSX_LIMIT * 4 // 3 + 4)
        try:
            data = base64.b64decode(raw.split(",", 1)[1] if raw.startswith("data:") else raw, validate=True)
        except (binascii.Error, ValueError):
            raise _Invalid("xlsx 文件不是有效的 base64") from None
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "import.xlsx"
            path.write_bytes(data)
            try:
                preview = read_xlsx_preview(path, max_rows=_IMPORT_MAX_ROWS + 1, max_columns=20)
            except XLSXPreviewError:
                raise _Invalid("读不了这个 xlsx，请另存为 CSV 再导入") from None
        if preview.truncated:
            raise _Invalid(f"文件超过 {_IMPORT_MAX_ROWS} 行，请拆分后导入")
        return [list(row) for row in preview.rows]
    return _str(value.get("csv"), "CSV", _CSV_LIMIT)


def _headers(latest: Mapping[str, Any]) -> list[str]:
    schema = latest.get("schema")
    if schema is None and latest.get("schema_json"):
        try:
            schema = json.loads(latest["schema_json"])
        except ValueError:
            schema = None
    if not isinstance(schema, Mapping) or not schema.get("headerRows"):
        schema = form_definition(S.FORM_KEY)
    return [str(h or "").strip() for h in schema["headerRows"][0]]


# ── 路由 ────────────────────────────────────────────────────────────


def register(host):
    ctx = host.context
    bp = host.blueprint
    store = Store(ctx.db, host.table_prefix)
    snapshots = S.SnapshotStore(ctx.db, host.table_prefix)
    settings = SET.SettingsStore(ctx.db, host.table_prefix, S.seed_roster(), S.seed_rule_rows())
    host.migrate([*store.migrations(), snapshots.migration(), settings.migration()])
    settings.reconcile()

    def body() -> Any:
        return request.get_json(silent=True)

    def guarded(handler):
        def wrapper(*args, **kwargs):
            guard = ctx.local_guard()
            if guard is not None:
                return guard
            try:
                return handler(*args, **kwargs)
            except (_Invalid, SET.SettingsError) as exc:
                return ctx.json_error(400, "ValidationError", str(exc))
        wrapper.__name__ = handler.__name__
        return wrapper

    def effective(config: Mapping[str, Any]) -> S.Effective:
        vocab = SET.to_vocabulary(settings.vocabulary())
        return S.Effective(
            roster=V.Roster(settings.roster()),
            rules=settings.rules(vocab),
            vocab=vocab,
            person_areas=dict(config.get("personAreas") or {}),
            area_names={**V.AREA_DISPLAY, **(config.get("areaNames") or {})},
        )

    def watchlist_state() -> dict[str, Any]:
        scope, serials = W.load_watchlist(ctx.db)
        return {"scope": scope, "serials": list(serials), "count": len(serials)}

    # ── 日报 ────────────────────────────────────────────────────────

    @bp.get("/state")
    def state():
        config = store.config()
        eff = effective(config)
        latest = ctx.db.get_latest_deliverable_form_snapshot(S.FORM_KEY)
        full = W.latest_full_snapshot(ctx.db, S.FORM_KEY) if latest else None
        meta = None
        options = {"projects": [], "departments": list(V.CURRENT_DEPARTMENTS)}
        error = None
        try:
            source = S.load_source(ctx.db, _headers, _DATA_TZ, watchlist_only=full is None)
            parsed = V.build_flows(source.records)
            options = S.scope_options(parsed.flows, S._Context(snapshots, [], eff))
            meta = {
                "dataDate": source.data_date.isoformat(),
                "snapshotAt": latest.get("snapshot_at") if latest else None,
                "coverage": W.snapshot_coverage(latest)["kind"],
                "fullSnapshotAt": full.get("snapshot_at") if full else None,
            }
        except (S.NoData, V.MissingColumnsError) as exc:
            error = str(exc)
        return ctx.json_ok({
            "data": meta, "dataError": error, "options": options,
            "form": config["form"], "preferences": config.get("preferences") or {},
            "legacyRecipients": config.get("recipients") or {},
            "thresholds": config["thresholds"], "addressBook": config.get("addressBook") or "",
            "personAreas": config.get("personAreas") or {},
            "areaNames": {**V.AREA_DISPLAY, **(config.get("areaNames") or {})},
            "externalColumns": [c for c in V.COUNTERSIGN_COLUMNS if c not in V.INTERNAL_COLUMNS],
            "watchlist": watchlist_state(), "seedVersion": S.seed_version(),
        })

    @bp.post("/config")
    @guarded
    def save_config():
        patch = _validate_config_patch(body())
        if "preferences" in patch:
            merged = dict(store.config().get("preferences") or {})
            merged.update(patch["preferences"])
            patch["preferences"] = merged
        store.save_config(patch)
        return ctx.json_ok({"saved": sorted(patch)})

    def compose(payload: Any, *, save: bool) -> tuple[dict[str, Any] | None, Any]:
        scope, watchlist_only, texts = _validate_request(payload)
        config = store.config()
        watch = watchlist_state()["serials"] if watchlist_only else None
        if watch is not None and not watch:
            return None, ctx.json_error(409, "WatchlistEmpty", "关注清单为空，请先在交付物明细里加入要关注的流水单号")
        try:
            source = S.load_source(ctx.db, _headers, _DATA_TZ, watchlist_only=watchlist_only)
            result = S.compose(
                snapshots, source, scope, region=texts["region"], effective=effective(config),
                save_snapshot=save, today=_today(), watchlist=watch,
                max_gap_days=int(config["thresholds"]["baselineMaxGapDays"]),
            )
        except S.NoData as exc:
            return None, ctx.json_error(409, "NoData", str(exc))
        except V.MissingColumnsError as exc:
            return None, ctx.json_error(422, "MissingColumns", str(exc))
        except LookupError as exc:
            return None, ctx.json_error(404, "EmptyScope", str(exc))
        key = scope_key(scope, watchlist_only)
        prefs = preferences_for(config, key)
        recipients = M.recipients(prefs.get("to"), prefs.get("cc"), config.get("addressBook"), M.owed_names(result))
        result.update({
            "scopeKey": key,
            "texts": texts,
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
        return result, None

    @bp.post("/preview")
    @guarded
    def preview():
        result, error = compose(body(), save=False)
        return error if error is not None else ctx.json_ok(result)

    @bp.post("/generate")
    @guarded
    def generate():
        result, error = compose(body(), save=True)
        return error if error is not None else ctx.json_ok(result)

    @bp.post("/eml")
    @guarded
    def eml():
        payload = body()
        if not isinstance(payload, Mapping):
            raise _Invalid("请求体必须是 JSON 对象")
        proceed = payload.get("proceedWithSuggestion", False)
        images_in = payload.get("images") or {}
        if not isinstance(proceed, bool) or not isinstance(images_in, Mapping):
            raise _Invalid("请求格式不对")
        result, error = compose({k: v for k, v in payload.items() if k not in ("images", "proceedWithSuggestion")},
                                save=False)
        if error is not None:
            return error
        if result["exportBlocked"] and not proceed:
            return ctx.json_error(409, "LongCycleReviewPending", "有长周期初筛待确认，确认或选择「本次按建议继续」后再导出")
        expected = set(result["chartsWithData"])
        if set(images_in) != expected:
            raise _Invalid("图片与正文里的图不一致，请重新生成后再下载")
        try:
            images = {key: M.decode_png(images_in[key]) for key in result["chartsWithData"]}
        except M.ImageError as exc:
            raise _Invalid(str(exc)) from None
        recipients = result["recipients"]
        data = M.build_eml(
            subject=result["subject"],
            to=[(r["name"], r["address"]) for r in recipients["to"]],
            cc=[(r["name"], r["address"]) for r in recipients["cc"]],
            text_body=result["text"], html_body=result["html"], images=images,
        )
        response = Response(data, mimetype="message/rfc822")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=\"daily-report.eml\"; filename*=UTF-8''{quote(result['subject'] + '.eml')}"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    # ── 长周期复核 ──────────────────────────────────────────────────

    @bp.get("/long-cycle")
    def long_cycle_list():
        project = (request.args.get("project") or "").strip()[:200]
        if not project:
            return ctx.json_ok({"projects": snapshots.projects_with_conclusions()})
        return ctx.json_ok({"project": project, "items": snapshots.list_conclusions(project)})

    @bp.post("/long-cycle")
    @guarded
    def long_cycle_confirm():
        value = body()
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
        classified = S.classify_keys((item["key"] for item in clean), effective(store.config()))
        snapshots.save_conclusions(project, [
            {**item, "autoResult": classified[item["key"]].result, "rule": classified[item["key"]].rule_id}
            for item in clean
        ])
        return ctx.json_ok({"project": project, "saved": len(clean)})

    @bp.post("/long-cycle/clear")
    @guarded
    def long_cycle_clear():
        value = body()
        project = _str((value or {}).get("project") if isinstance(value, Mapping) else None, "项目", 200).strip()
        if not project:
            raise _Invalid("缺少项目")
        return ctx.json_ok({"project": project, "cleared": snapshots.clear_conclusions(project)})

    # ── 后台抓取 ────────────────────────────────────────────────────

    @bp.post("/refresh")
    @guarded
    def refresh():
        value = body() if isinstance(body(), Mapping) else {}
        watchlist_only = value.get("watchlistOnly", False)
        if not isinstance(watchlist_only, bool):
            raise _Invalid("只统计关注清单 必须是布尔值")
        try:
            runner = ctx.service("crawl_task_runner")
            archive = ctx.service("scheduled_archive_admin")
        except LookupError as exc:
            return ctx.json_error(409, "SyncNotReady", str(exc))
        scope = watchlist_state()["scope"]
        if not watchlist_only and scope == W.SCOPE_WATCHLIST:
            # 开关关：日报只认全量快照，一键生成要触发全量抓取；同步范围由交付物明细页维护。
            return ctx.json_error(409, "WatchlistScope",
                                  "数模报表的同步范围是「仅关注清单」，抓不到全量数据：请到交付物明细把同步范围改为"
                                  "「全部表单」，或打开「只统计关注清单」")
        for task in runner.list_tasks(source=S.TASK_SOURCE, limit=10):
            if task.get("status") in ("queued", "running"):
                return ctx.json_ok({**S.task_view(task), "reused": True})
        worker = S.make_refresh_worker(archive, ctx.db, sync_failure_message)
        task_id = runner.submit_task(S.TASK_TYPE, S.TASK_SOURCE, {}, worker_fn=worker)
        task = runner.get_task(task_id) or {"task_id": task_id, "status": "queued"}
        return ctx.json_ok({**S.task_view(task), "reused": False})

    @bp.get("/refresh/<task_id>")
    def refresh_status(task_id: str):
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

    # ── 设置与导入 ──────────────────────────────────────────────────

    def dataset_view(dataset: str) -> dict[str, Any]:
        conflicts = settings.reconcile()
        view: dict[str, Any] = {"dataset": dataset, "backups": settings.backups(dataset)}
        if dataset == "roster":
            view.update({"mode": settings.mode("roster"), "rows": settings.roster_rows(),
                         "conflicts": conflicts["roster"], "departments": list(V.CURRENT_DEPARTMENTS)})
        elif dataset == "rules":
            view.update({"mode": settings.mode("rules"), "rows": settings.rule_rows(), "conflicts": conflicts["rules"]})
        else:
            view.update({"vocabulary": settings.vocabulary(), "defaults": SET.default_vocabulary()})
        return view

    def check_dataset(dataset: str) -> None:
        if dataset not in SET.DATASETS:
            raise _Invalid("没有这个配置数据集")

    @bp.get("/settings/<dataset>")
    def settings_view(dataset: str):
        if dataset not in SET.DATASETS:
            return ctx.json_error(404, "NotFound", "没有这个配置数据集")
        return ctx.json_ok(dataset_view(dataset))

    @bp.post("/settings/roster/person")
    @guarded
    def roster_person():
        value = body() if isinstance(body(), Mapping) else {}
        name = V.normalize_name(_str(value.get("name"), "姓名", 50))[0]
        if not name:
            raise _Invalid("姓名不能为空")
        department = value.get("department")
        if department is not None:
            department = _str(department, "科室", 50).strip()
            if department not in V.CURRENT_DEPARTMENTS:
                raise _Invalid("科室必须是现行科室：" + "、".join(V.CURRENT_DEPARTMENTS))
        settings.set_person(name, department, _str(value.get("note"), "备注", 200).strip())
        return ctx.json_ok(dataset_view("roster"))

    @bp.post("/settings/roster/revert")
    @guarded
    def roster_revert():
        value = body() if isinstance(body(), Mapping) else {}
        settings.revert_person(V.normalize_name(_str(value.get("name"), "姓名", 50))[0])
        return ctx.json_ok(dataset_view("roster"))

    @bp.post("/settings/rules/rule")
    @guarded
    def rules_rule():
        value = body() if isinstance(body(), Mapping) else {}
        rule_id = _str(value.get("id"), "规则编号", 20).strip()
        if value.get("delete") is True:
            if not rule_id:
                raise _Invalid("缺少规则编号")
            settings.set_rule(rule_id, None)
            return ctx.json_ok(dataset_view("rules"))
        fields = {
            "name": _str(value.get("name"), "零件名称", 100).strip(),
            "remark": _str(value.get("remark"), "备注", 200).strip(),
            "aliases": _str(value.get("aliases"), "别名", 500).strip(),
            "enabled": value.get("enabled", True),
        }
        if not isinstance(fields["enabled"], bool):
            raise _Invalid("启用必须是布尔值")
        vocab = SET.to_vocabulary(settings.vocabulary())
        aliases = [a for a in fields["aliases"].replace("，", "、").split("、") if a.strip()]
        if not fields["name"] or not V.build_rule("x", fields["name"], fields["remark"], vocab, aliases).core_groups:
            raise _Invalid("零件名称规范化后没有核心词")
        settings.set_rule(rule_id or settings.next_rule_id(), fields)
        return ctx.json_ok(dataset_view("rules"))

    @bp.post("/settings/rules/revert")
    @guarded
    def rules_revert():
        value = body() if isinstance(body(), Mapping) else {}
        settings.revert_rule(_str(value.get("id"), "规则编号", 20).strip())
        return ctx.json_ok(dataset_view("rules"))

    @bp.post("/settings/vocabulary")
    @guarded
    def vocabulary_save():
        value = body() if isinstance(body(), Mapping) else {}
        settings.save_vocabulary(SET.validate_vocabulary(value.get("vocabulary")), "修改词表前")
        return ctx.json_ok(dataset_view("vocabulary"))

    @bp.post("/settings/<dataset>/import")
    @guarded
    def dataset_import(dataset: str):
        check_dataset(dataset)
        if dataset == "vocabulary":
            raise _Invalid("词表不支持 CSV 导入")
        value = body() if isinstance(body(), Mapping) else {}
        source = import_rows(value)
        replace, commit, skip = value.get("replace", False), value.get("commit", False), value.get("skipErrors", False)
        if not all(isinstance(flag, bool) for flag in (replace, commit, skip)):
            raise _Invalid("导入选项必须是布尔值")
        if dataset == "roster":
            plan = settings.roster_import_plan(source, replace)
        else:
            plan = settings.rules_import_plan(source, replace, SET.to_vocabulary(settings.vocabulary()))
        preview = {k: v for k, v in plan.items() if k != "entries"}
        preview["counts"] = {k: len(plan[k]) for k in ("added", "changed", "removed", "conflicts", "errors")}
        if not commit:
            return ctx.json_ok({"plan": preview, "committed": False})
        if plan["errors"] and not skip:
            return ctx.json_error(409, "ImportHasErrors", f"有 {len(plan['errors'])} 行错误；可选择跳过错误行导入或全部取消")
        if dataset == "roster":
            settings.commit_roster_import(plan)
        else:
            settings.commit_rules_import(plan)
        return ctx.json_ok({"plan": preview, "committed": True, "view": dataset_view(dataset)})

    @bp.get("/settings/<dataset>.csv")
    def dataset_csv(dataset: str):
        if dataset not in ("roster", "rules"):
            return ctx.json_error(404, "NotFound", "没有这个配置数据集")
        text = settings.roster_csv() if dataset == "roster" else settings.rules_csv()
        response = Response("﻿" + text, mimetype="text/csv")
        response.headers["Content-Disposition"] = f"attachment; filename=\"{dataset}.csv\""
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.post("/settings/<dataset>/restore")
    @guarded
    def dataset_restore(dataset: str):
        check_dataset(dataset)
        value = body() if isinstance(body(), Mapping) else {}
        backup_id = value.get("backupId")
        if isinstance(backup_id, bool) or not isinstance(backup_id, int):
            raise _Invalid("缺少备份编号")
        settings.restore(dataset, backup_id)
        return ctx.json_ok(dataset_view(dataset))

    @bp.post("/settings/<dataset>/reset")
    @guarded
    def dataset_reset(dataset: str):
        check_dataset(dataset)
        settings.reset_seed(dataset)
        return ctx.json_ok(dataset_view(dataset))
