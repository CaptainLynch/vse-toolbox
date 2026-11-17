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
- POST import-scan / import-form   用本地导出的报表出一次日报（2026-11-16 起计算日变化）：不读不写 TDC
                                 共享快照、配置与长周期结论，只写手工导入自有的基线表
                                 （``manual_baseline.py``；表单字段 keepBaseline=0 时只读不写；
                                 baselineDate 指定基线，优先级 指定 > 基线文件 / 固定 > 自动）
- GET  manual-baselines          手工导入基线列表；POST manual-baselines/pin|unpin|delete 固定 / 取消 / 删除
                                 （pin 同时取消基线文件并删除其备份；视图里带 file：当前基线文件）
- GET  manual-baseline-file      当前基线文件 + 原文件/备份的实时状态 + 备份目录（含本机路径，所以也过 local_guard）
- POST manual-baseline-file      指定基线文件（multipart：file 上传或 path 完整路径，加 dataDate）；同时取消固定
- POST manual-baseline-file/clear   取消基线文件并删除备份
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
import hashlib
import io
import json
import re
import secrets
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from flask import Response, request
from werkzeug.datastructures import MultiDict
from werkzeug.formparser import FormDataParser

from core.time_rules import now_utc
from services import data_model_watchlist as W
from services import schedule_jobs
from services import schedule_policy as SP
from services.schedule_slots import SYNC_CONTROL_TABLE_PREFIX, SlotStore
from services.xlsx_preview import REASON_ENCRYPTED_CONTAINER, XLSXPreviewError, read_xlsx_preview_bytes

from . import excel_proxy as XP
from . import importer as IMP
from . import mail as M
from . import manual_baseline as MB
from . import rules as V
from . import scheduled as SCH
from . import service as S
from . import settings as SET

_TEXT_LIMIT = 20000
_LIST_LIMIT = 2000
_CSV_LIMIT = 2 * 1024 * 1024
_XLSX_LIMIT = 5 * 1024 * 1024
_IMPORT_MAX_ROWS = 5000
#: 本地报表导入的体积上限（官方导出件通常 < 5 MB）。
#: 上传上限：宿主 MAX_CONTENT_LENGTH=16MB，这里留 1MB 余量，避免插件分支永远走不到。
_FORM_FILE_LIMIT = 15 * 1024 * 1024
#: 扫描令牌签名密钥（进程内随机）：把「扫到的那个文件」绑成不透明句柄，前端不传路径。
_SCAN_SECRET = secrets.token_bytes(32)
#: 扫描时对最新文件的稳定性采样间隔（秒）。
_SCAN_SETTLE_SECONDS = 2.0
#: 目录句柄表：页面只拿到不透明 dirId，绝对路径不出服务端（进程内有效，重启后重新扫描即可）。
_SCAN_DIRS: dict[str, Path] = {}
#: 目录句柄表上限（超出淘汰最久未使用的，避免无界增长）。
_SCAN_DIRS_LIMIT = 64
#: 数据日期换算用的时区；None 取本机时区（测试里固定）。
_DATA_TZ = None

#: 页面导入遇到受终端加密的 xlsx、而这次没走 Excel 代读时的提示：给出页面上的两条出路。
ENCRYPTED_PAGE_TEXT = (
    "文件受公司终端加密保护，本功能读不到内容，文件本身没有损坏。两种办法：① 用 Excel 打开它，另存为"
    "「Unicode 文本(*.txt)」，再导入这份 .txt；② 勾选「加密的 xlsx 由本机 Excel 代读」，把文件放进扫描目录，"
    "点「扫描目录」再生成（「选择文件」上传的不会代读）。"
)
#: 基线文件受终端加密、而 Excel 代读没开时的提示（与导入区的「另存为 txt」指引同一口径）。
ENCRYPTED_BASELINE_TEXT = (
    "文件受公司终端加密保护，本功能读不到内容，文件本身没有损坏。请用 Excel 打开它，「另存为」选"
    "「Unicode 文本(*.txt)」，再把这份 .txt 指定为基线文件；或先开启「加密的 xlsx 由本机 Excel 代读」。"
)

_DEFAULT_THRESHOLDS = {"warnDays": 7, "overdueDays": 14, "baselineMaxGapDays": S.BASELINE_MAX_GAP_DAYS}
_DEFAULT_REGION = SCH.DEFAULT_REGION

#: 与定时生成（scheduled.py）共用的纯函数：路由与作业只能有一套口径。
scope_key = SCH.scope_key
preferences_for = SCH.preferences_for
sync_failure_message = SCH.sync_failure_message


def _today() -> date:
    return date.today()


def _import_today() -> date:
    """手工导入校验「数据截至日期不晚于今天」用的日历日（单独一个钩子：与日报的 ``_today`` 互不影响）。"""
    return date.today()


#: 三张图的默认配色（与 static/chart.js 的 PALETTES 必须一致，测试钉住）：图 -> {普通柱, 特殊组柱}。
DEFAULT_CHART_COLORS: dict[str, dict[str, str]] = {
    "external": {"bar": "#3370ff", "special": "#3370ff"},  # 图1 强调色
    "sections": {"bar": "#8f959e", "special": "#c9cdd4"},  # 图2 中性色，特殊组浅色
    "approval": {"bar": "#8f959e", "special": "#8f959e"},  # 图3 中性色
}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _chart_colors(stored: Any) -> dict[str, dict[str, str]]:
    """生效配色：存储值逐图、逐项叠加在默认值上；缺项或坏值一律回落默认，绝不缺键。"""
    result = {chart: dict(colors) for chart, colors in DEFAULT_CHART_COLORS.items()}
    if not isinstance(stored, Mapping):
        return result
    for chart, colors in stored.items():
        if chart not in result or not isinstance(colors, Mapping):
            continue
        for slot in ("bar", "special"):
            value = colors.get(slot)
            if isinstance(value, str) and _HEX_COLOR.match(value):
                result[chart][slot] = value.lower()
    return result


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
        # 发送门禁（TDC-20261029）：状态列仍是数字码时禁止导出，单开关回滚。
        "statusGateEnabled": True,
        # Excel 代读（2026-11-12）：用户开关，默认关（2026-11-17 起不再需要部署授权文件）。
        "excelProxyEnabled": False,
        # 图表配色（2026-11-16）：图 -> {bar, special}，只影响前端出图。
        "chartColors": _chart_colors(None),
        "form": {"projects": [], "departments": [], "watchlistOnly": False, "region": _DEFAULT_REGION},
        # v1 的「范围 key -> {to, cc}」，只读兜底（同范围的收件人带到 v2）
        "recipients": {},
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
        "greeting": _str(value.get("greeting"), "称呼", 200).strip() or SCH.DEFAULT_GREETING,
        "planText": _str(value.get("planText"), "计划/超期说明"),
        "feishuLink": _str(value.get("feishuLink"), "飞书链接", 2000),
    }


def _memory_stream(*_args: Any, **_kwargs: Any) -> io.BytesIO:
    return io.BytesIO()


def _memory_form() -> tuple[MultiDict, MultiDict]:
    """把 multipart 请求体**全程在内存里**解析成 (form, files)。

    不能用 ``request.form`` / ``request.files``：Werkzeug 默认把超过 500KB 的文件部分
    spool 到临时文件，导入的报表就会在磁盘上留一份。这里换成内存流工厂，其余限制
    （请求体总大小、表单字段内存、分片数）沿用宿主在 request 上的配置。
    """
    parser = FormDataParser(
        stream_factory=_memory_stream,
        max_form_memory_size=request.max_form_memory_size,
        max_content_length=request.max_content_length,
        max_form_parts=request.max_form_parts,
    )
    _stream, form, files = parser.parse(
        request.stream, request.mimetype, request.content_length, request.mimetype_params
    )
    return form, files


def _form_list(form: Mapping[str, Any], name: str) -> Any:
    """multipart 表单里的数组字段：前端以 JSON 文本传，缺省/空串视为空数组。"""
    raw = form.get(name)
    if raw is None or not str(raw).strip():
        return []
    try:
        return json.loads(raw)
    except ValueError:
        raise _Invalid(f"{name} 不是合法的 JSON 数组") from None


def _iso_date(raw: Any, name: str) -> date:
    """严格的 YYYY-MM-DD（不接受 20261106、2026-11-6 之类的变体）。"""
    text = str(raw or "").strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise _Invalid(f"{name}格式应为 YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _Invalid(f"{name}格式应为 YYYY-MM-DD") from None


def _form_bool(form: Mapping[str, Any], name: str, *, default: bool) -> bool:
    """multipart 表单里的开关：1/0/true/false（不分大小写），缺省或空串取默认值。"""
    raw = str(form.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true"):
        return True
    if raw in ("0", "false"):
        return False
    raise _Invalid(f"{name} 只能是 1/0/true/false")


def _validate_request(value: Any) -> tuple[S.Scope, bool, dict[str, str]]:
    if not isinstance(value, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    scope = S.Scope(_str_list(value.get("projects"), "项目/车型"), _str_list(value.get("departments"), "归属科室"))
    watchlist_only = value.get("watchlistOnly", False)
    if not isinstance(watchlist_only, bool):
        raise _Invalid("只统计关注清单 必须是布尔值")
    return scope, watchlist_only, _texts(value)


def _validate_config_patch(patch: Any) -> dict[str, Any]:
    if not isinstance(patch, Mapping):
        raise _Invalid("请求体必须是 JSON 对象")
    allowed = {
        "personAreas", "areaNames", "addressBook", "thresholds", "preferences", "statusGateEnabled",
        "excelProxyEnabled", "chartColors",
    }
    unknown = set(patch) - allowed
    if unknown:
        raise _Invalid("未知配置项：" + "、".join(sorted(unknown)))
    clean: dict[str, Any] = {}
    if "excelProxyEnabled" in patch:
        if not isinstance(patch["excelProxyEnabled"], bool):
            raise _Invalid("Excel 代读开关必须是布尔值")
        clean["excelProxyEnabled"] = patch["excelProxyEnabled"]
    if "chartColors" in patch:
        clean["chartColors"] = _validate_chart_colors(patch["chartColors"])
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
    if "statusGateEnabled" in patch:
        enabled = patch["statusGateEnabled"]
        if not isinstance(enabled, bool):
            raise _Invalid("发送门禁开关必须是布尔值")
        clean["statusGateEnabled"] = enabled
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


def _validate_chart_colors(value: Any) -> dict[str, dict[str, str]]:
    """部分更新：只认三张图、只认 bar/special、只认 #RRGGBB（统一小写）；其余一律拒绝。"""
    if not isinstance(value, Mapping):
        raise _Invalid("图表配色必须是对象")
    unknown = set(value) - set(DEFAULT_CHART_COLORS)
    if unknown:
        raise _Invalid("未知的图：" + "、".join(sorted(str(k) for k in unknown)))
    clean: dict[str, dict[str, str]] = {}
    for chart, colors in value.items():
        if not isinstance(colors, Mapping):
            raise _Invalid("图表配色必须是对象")
        bad = set(colors) - {"bar", "special"}
        if bad:
            raise _Invalid("配色只能改 bar、special：" + "、".join(sorted(str(k) for k in bad)))
        clean[chart] = {}
        for slot, color in colors.items():
            if not isinstance(color, str) or not _HEX_COLOR.match(color):
                raise _Invalid("颜色必须是 #RRGGBB 形式")
            clean[chart][slot] = color.lower()
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
        config["chartColors"] = _chart_colors(config.get("chartColors"))
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


# ── 数据 ────────────────────────────────────────────────────────────


def import_rows(value: Mapping[str, Any]) -> str | list[list[Any]]:
    """导入来源：CSV 原文，或 base64 的 xlsx（宿主自带的无依赖读取器，只读第一个工作表，§7）。"""
    if value.get("xlsx") is not None:
        raw = _str(value.get("xlsx"), "xlsx", _XLSX_LIMIT * 4 // 3 + 4)
        try:
            data = base64.b64decode(raw.split(",", 1)[1] if raw.startswith("data:") else raw, validate=True)
        except (binascii.Error, ValueError):
            raise _Invalid("xlsx 文件不是有效的 base64") from None
        try:
            # 在内存里读（不写临时文件）。
            preview = read_xlsx_preview_bytes(data, max_rows=_IMPORT_MAX_ROWS + 1, max_columns=20)
        except XLSXPreviewError as exc:
            # 与 /import-form 用同一条文案：受终端加密与「打不开」必须分开说。
            reason = str(getattr(exc, "reason", "") or "")
            raise _Invalid(
                IMP.ENCRYPTED_TEXT if reason == REASON_ENCRYPTED_CONTAINER else IMP.DAMAGED_TEXT
            ) from None
        if preview.truncated:
            raise _Invalid(f"文件超过 {_IMPORT_MAX_ROWS} 行，请拆分后导入")
        return [list(row) for row in preview.rows]
    return _str(value.get("csv"), "CSV", _CSV_LIMIT)


# ── 路由 ────────────────────────────────────────────────────────────


def register(host):
    ctx = host.context
    bp = host.blueprint
    store = Store(ctx.db, host.table_prefix)
    snapshots = S.SnapshotStore(ctx.db, host.table_prefix)
    settings = SET.SettingsStore(ctx.db, host.table_prefix, S.seed_roster(), S.seed_rule_rows())
    reports = SCH.ScheduledReportStore(ctx.db, host.table_prefix)
    manual_baselines = MB.ManualBaselineStore(ctx.db, host.table_prefix)
    baseline_file = MB.BaselineFileStore(ctx.db, host.table_prefix)
    host.migrate([
        *store.migrations(),
        snapshots.migration(),
        settings.migration(),
        reports.migration(),
        manual_baselines.migration(),
        baseline_file.migration(),
    ])
    settings.reconcile()
    # 调度器的槽/绑定表由 sync-control 插件建（同一 services 层前缀），这里只读写。
    slot_store = SlotStore(ctx.db, SYNC_CONTROL_TABLE_PREFIX, clock=now_utc)

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

    # 工作日 08:30 日报作业（DSH-V2-23）：唯一调度器按 jobId 查注册表调用。
    # 处理器在调度线程运行，只依赖注入的 db/存储与宿主服务，不碰 Flask 上下文。
    daily_job = SCH.DailyReportJob(
        db=ctx.db,
        store=store,
        snapshots=snapshots,
        reports=reports,
        effective=effective,
        runner_factory=lambda: ctx.service("crawl_task_runner"),
        archive_factory=lambda: ctx.service("scheduled_archive_admin"),
        data_tz=lambda: _DATA_TZ,
    )
    schedule_jobs.register_job(
        SP.DAILY_REPORT_JOB_ID,
        make_binding=lambda project_id, times, paused: SP.daily_report_binding(
            project_id, times=tuple(times or ()), paused=bool(paused)
        ),
        handler=daily_job.handle,
    )

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
            source = S.load_source(ctx.db, SCH.headers_for, _DATA_TZ, watchlist_only=full is None)
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
            "excelProxy": XP.status(config.get("excelProxyEnabled")),
            # 默认扫描目录的完整路径：数据根随部署形态变化，必须让用户直接看到，不能靠猜。
            # 注意目录名是插件 id（sign-daily），不是源码包名（sign_daily）。
            "importDir": str((ctx.plugin_data_dir(host.manifest.id) / IMP.DEFAULT_SUBDIR).resolve()),
            "legacyRecipients": config.get("recipients") or {},
            "thresholds": config["thresholds"], "addressBook": config.get("addressBook") or "",
            "personAreas": config.get("personAreas") or {},
            "areaNames": {**V.AREA_DISPLAY, **(config.get("areaNames") or {})},
            "externalColumns": [c for c in V.COUNTERSIGN_COLUMNS if c not in V.INTERNAL_COLUMNS],
            "watchlist": watchlist_state(), "seedVersion": S.seed_version(),
            "chartColors": config["chartColors"],
        })

    @bp.post("/config")
    @guarded
    def save_config():
        patch = _validate_config_patch(body())
        if "chartColors" in patch:
            # 部分更新：只改传来的图与项，其余沿用当前生效值。
            merged_colors = store.config()["chartColors"]
            for chart, colors in patch["chartColors"].items():
                merged_colors[chart].update(colors)
            patch["chartColors"] = merged_colors
        if "preferences" in patch:
            merged = dict(store.config().get("preferences") or {})
            merged.update(patch["preferences"])
            patch["preferences"] = merged
        store.save_config(patch)
        return ctx.json_ok({"saved": sorted(patch)})

    def compose(payload: Any, *, save: bool) -> tuple[dict[str, Any] | None, Any]:
        """路由层适配：校验请求体 + 把 compose 业务失败映射成既有 HTTP 错误。

        业务核心在 ``scheduled.build_report``，与工作日 08:30 定时生成共用同一套
        计算与落快照逻辑（路由行为与响应保持不变）。
        """
        scope, watchlist_only, texts = _validate_request(payload)
        try:
            result = SCH.build_report(
                db=ctx.db, store=store, snapshots=snapshots, effective=effective,
                scope=scope, watchlist_only=watchlist_only, texts=texts,
                save=save, today=_today(), tz=_DATA_TZ,
            )
        except SCH.ReportFailure as exc:
            return None, ctx.json_error(exc.status, exc.code, exc.message)
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

    def import_error(exc: IMP.ManualImportError):
        """手工导入失败的唯一出口：code、文案与白名单 diagnostic（reason/sizeBucket/colIndex）一起回页面。"""
        message = exc.message
        if (
            exc.code == "E_ENCRYPTED_WORKBOOK" and message == IMP.ENCRYPTED_TEXT
            and (exc.diagnostic or {}).get("reason") == IMP.REASON_ENCRYPTED_CONTAINER
            and not XP.ready(store.config())
        ):
            # 共用文案（与离线 CLI 同一份）只说「改用一键生成」；代读没开时页面上其实有两条出路，直接说出来。
            # 代读开着却没读成的情况（reason 是 Excel 那边的原因）保持原文案，由页面补充那条原因。
            message = ENCRYPTED_PAGE_TEXT
        return ctx.json_error(422, exc.code, message, diagnostic=exc.diagnostic or None)

    def _manual_report(source, scope, texts, *, name: str, digest: str, source_format: str,
                       keep_baseline: bool = True, baseline_date: date | None = None):
        """手工导入出报（2026-11-16 起计算日变化）。

        边界：TDC 共享快照、配置、长周期结论一律不读不写（``ReadOnlyStore`` + ``save_config=False``，
        基线库 ``ManualBaselineStore`` 的结论读写恒空/抛错）；只读写手工导入自有的基线表。
        基线挑选、旧数据判定、最长间隔与括号里的变化全部复用 ``S.compose``，与一键生成同一套口径。
        """
        baselines = manual_baselines.bind(source_name=name, sha256=digest)
        compare_store: Any = baselines
        file_info: dict[str, Any] | None = None
        # 基线日期：本次指定 > 基线文件 / 固定（二者互斥）> 自动（compose 里的 _pick_baseline）。
        if baseline_date is not None:
            requested_mode = "explicit"
        else:
            loaded = load_file_baseline()
            if loaded is not None:
                file_info, records = loaded
                requested_mode = "file"
                baseline_date = date.fromisoformat(file_info["date"])
                # compose 不改：基线文件的内容以「那一天的全量快照」出现；备份不可用时 records 为 None，
                # 那一天对任何项目都不覆盖 → 不显示日变化，也不退回自动挑选。
                compare_store = MB.FileBaselineAdapter(baselines, baseline_date, records, source.data_date)
            else:
                baseline_date = baselines.pinned_date()
                requested_mode = "pinned" if baseline_date is not None else "auto"
        try:
            result = SCH.build_report(
                db=ctx.db, store=IMP.ReadOnlyStore(store), snapshots=compare_store,
                effective=effective, scope=scope, watchlist_only=False, texts=texts,
                save=keep_baseline, save_config=False, today=source.data_date, tz=_DATA_TZ, source=source,
                baseline_date=baseline_date,
            )
        except SCH.ReportFailure as exc:
            return ctx.json_error(exc.status, exc.code, exc.message)
        baseline = None
        if result["baseDate"]:
            projects = sorted({
                V.cell_text(r.get("项目/车型")) for r in source.records if V.cell_text(r.get("项目/车型"))
            })
            projects = [p for p in projects if not scope.projects or p in scope.projects]
            if requested_mode == "file" and file_info is not None:
                baseline = {"mode": "file", **file_info}
            else:
                found = baselines.source_of(projects, date.fromisoformat(result["baseDate"])) or {}
                baseline = {
                    "mode": requested_mode,
                    "date": result["baseDate"],
                    "sourceName": found.get("sourceName", ""),
                    "sha256": str(found.get("sha256") or "")[:12],
                }
        # compose 的 snapshotSaved 在这里指「手工基线已写」；对外 snapshotSaved 仍只指 TDC 共享快照（恒 False）。
        baseline_saved = bool(result["snapshotSaved"])
        result["snapshotSaved"] = False
        meta = IMP.import_meta(
            Path(name), source, name=name, digest=digest, source_format=source_format,
            baseline=baseline, baseline_saved=baseline_saved, stale=bool(result["stale"]),
            requested=result.get("baselineRequested"), requested_mode=requested_mode,
            file_baseline=file_info,
        )
        banner = (
            f"手工导入｜{meta['sourceName']}｜数据截至日期 {meta['dataDate']}"
            "（用户确认，未经系统核验）｜参与计算 %d 行｜%s"
            % (meta["rowCount"], meta["baselineStatement"])
        )
        # 正文指纹：只对「不含来源声明、不含日变化」的正文取摘要。来源声明不进指纹，所以同一份数据
        # 换一种导入方式（明文 xlsx / TXT / Excel 代读）指纹相同；日变化（汇总段括号、间隔说明行、
        # 每日进展段）也不进指纹，所以同一份数据有没有基线指纹都相同——真机验收靠它一眼对上。
        plain_lines = S._summary_lines(result["projectLabel"], texts["region"], result["summary"], None)
        digest_text = M.render_text({**result, "summaryLines": plain_lines}, texts)
        report_digest = hashlib.sha256(digest_text.encode("utf-8")).hexdigest()[:12]
        # 复制正文是唯一出口（.eml 已禁），来源声明必须进正文本身，而不只是页面徽标；
        # 每日进展紧跟在来源声明之后。
        progress = result.get("progress")
        result["html"] = f'<p><b>{M._e(banner)}</b></p>' + M.progress_html(progress) + result["html"]
        result["text"] = banner + "\n" + M.progress_text(progress) + result["text"]
        return ctx.json_ok({
            **result, "mode": "manual",
            "importMeta": {**meta, "banner": banner, "reportDigest": report_digest},
        })

    # ── 手工导入的对比基线（列表 / 固定 / 取消固定 / 删除）────────────

    def baseline_day(value: Any) -> date:
        if not isinstance(value, Mapping):
            raise _Invalid("请求体必须是 JSON 对象")
        return _iso_date(_str(value.get("date"), "日期", 20), "基线日期")

    def baselines_view(*, with_paths: bool = True) -> dict[str, Any]:
        items = manual_baselines.list_baselines()
        pinned = next((item["date"] for item in items if item["pinned"]), None)
        file_view = baseline_file_view()
        if file_view is not None and not with_paths:
            # 列表 GET 不过 local_guard：非本机来源只给不含本机路径的摘要。
            file_view = {key: value for key, value in file_view.items()
                         if key not in ("originalPath", "backupPath")}
            file_view["pathsHidden"] = True
        return {"items": items, "pinned": pinned, "file": file_view}

    @bp.get("/manual-baselines")
    def manual_baselines_list():
        return ctx.json_ok(baselines_view(with_paths=ctx.local_guard() is None))

    @bp.post("/manual-baselines/pin")
    @guarded
    def manual_baselines_pin():
        day = baseline_day(body())
        try:
            manual_baselines.pin(day)
        except LookupError:
            return ctx.json_error(404, "NotFound", f"没有 {day.isoformat()} 的手工导入基线")
        # 固定与基线文件互斥：固定成功后取消基线文件并删除它的备份（页面已先请用户确认）。
        clear_baseline_file()
        return ctx.json_ok(baselines_view())

    @bp.post("/manual-baselines/unpin")
    @guarded
    def manual_baselines_unpin():
        manual_baselines.unpin()
        return ctx.json_ok(baselines_view())

    @bp.post("/manual-baselines/delete")
    @guarded
    def manual_baselines_delete():
        day = baseline_day(body())
        if not manual_baselines.delete(day):
            return ctx.json_error(404, "NotFound", f"没有 {day.isoformat()} 的手工导入基线")
        return ctx.json_ok(baselines_view())

    # ── 基线文件：指定一份本地报表为固定基线（备份在插件数据目录，对比只读备份）──────

    def backup_dir() -> Path:
        return (ctx.plugin_data_dir(host.manifest.id) / MB.BACKUP_SUBDIR).resolve()

    def clear_baseline_file() -> bool:
        """删记录，再只删记录里的那份备份（白名单名字、备份目录的直接子项）。"""
        previous = baseline_file.clear()
        if previous is None:
            return False
        MB.remove_backup(backup_dir(), previous["backup_name"])
        return True

    def backup_state(record: Mapping[str, Any]) -> tuple[str, bytes | None]:
        """备份在、读得了、内容摘要与指定时一致才算 ok。"""
        data = MB.read_backup(backup_dir(), record["backup_name"], _FORM_FILE_LIMIT)
        if data is None or hashlib.sha256(data).hexdigest() != record["sha256"]:
            return MB.BACKUP_MISSING, None
        return MB.BACKUP_OK, data

    def file_info_of(record: Mapping[str, Any], backup_status: str) -> dict[str, Any]:
        target = MB.backup_path(backup_dir(), record["backup_name"])
        return {
            "date": record["data_date"],
            "sourceName": record["original_name"],
            "sha256": str(record["sha256"])[:12],
            "size": int(record["size"]),
            "originalPath": record["original_path"] or None,
            "backupPath": str(target) if target is not None else "",
            "originalStatus": MB.probe_original(
                record["original_path"], record["sha256"], record["size"], _FORM_FILE_LIMIT
            ),
            "backupStatus": backup_status,
            "setAt": record["set_at"],
        }

    def baseline_file_view() -> dict[str, Any] | None:
        record = baseline_file.get()
        if record is None:
            return None
        return file_info_of(record, backup_state(record)[0])

    def parse_baseline_bytes(data: bytes, day: date, name: str, target: Path | None):
        """解析基线文件的字节（与导入同一套官方表头校验）；受终端加密的 xlsx 在代读开着时让 Excel 读备份。"""
        try:
            return IMP.source_from_bytes(data, day, name=name)
        except IMP.ManualImportError as exc:
            if not (
                exc.code == "E_ENCRYPTED_WORKBOOK" and IMP.source_format(data, name) == "xlsx"
                and target is not None and XP.ready(store.config())
            ):
                raise
        parsed = IMP.source_from_excel(target, day)
        # Excel 是按路径另开的：读完再核对一次备份的内容摘要，期间被换过就作废。
        again = MB.read_backup(target.parent, target.name, _FORM_FILE_LIMIT)
        if again is None or hashlib.sha256(again).hexdigest() != hashlib.sha256(data).hexdigest():
            raise IMP.ManualImportError("E_SCAN_STALE", "基线备份在读取过程中被改动过，请重新指定")
        return parsed

    def load_file_baseline() -> tuple[dict[str, Any], list[dict[str, Any]] | None] | None:
        """生成时用：(文件与状态, 备份解析出的行)；备份不在或认不出时行为 None；没有基线文件返回 None。"""
        record = baseline_file.get()
        if record is None:
            return None
        status, data = backup_state(record)
        records = None
        if data is not None:
            try:
                parsed = parse_baseline_bytes(
                    data, date.fromisoformat(record["data_date"]), record["backup_name"],
                    MB.backup_path(backup_dir(), record["backup_name"]),
                )
                records = list(parsed.records)
            except IMP.ManualImportError:
                status = MB.BACKUP_MISSING
        return file_info_of(record, status), records

    def baseline_file_payload() -> dict[str, Any]:
        return {"file": baseline_file_view(), "backupDir": str(backup_dir())}

    @bp.get("/manual-baseline-file")
    def manual_baseline_file_get():
        # 响应里有本机路径：读也只允许本机（与写路由同一道 local_guard）。
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        return ctx.json_ok(baseline_file_payload())

    @bp.post("/manual-baseline-file")
    @guarded
    def manual_baseline_file_set():
        """指定基线文件：选择文件（上传）或粘贴完整路径，二选一；校验通过才备份、记录，并取消固定。"""
        form, files = _memory_form()
        upload = files.get("file")
        has_upload = upload is not None and bool(upload.filename)
        raw_path = _str(form.get("path"), "路径", 4096).strip()
        if has_upload and raw_path:
            raise _Invalid("「选择文件」和「粘贴完整路径」只能用一种，请清掉其中一个")
        if not has_upload and not raw_path:
            raise _Invalid("请选择基线文件，或粘贴它的完整路径")
        raw_date = str(form.get("dataDate") or "").strip()
        if not raw_date:
            raise _Invalid("请填写这份基线文件的数据截至日期（就是导出它的那一天）")
        day = _iso_date(raw_date, "数据截至日期")
        if day > _import_today():
            raise _Invalid(f"数据截至日期 {day.isoformat()} 晚于今天，请检查是否填错")
        original_path: str | None
        if has_upload:
            name = re.split(r"[\\/]", str(upload.filename))[-1].strip()
            suffix = Path(name).suffix.lower()
            if suffix not in IMP.SUFFIXES:
                raise _Invalid("基线文件只接受 .xlsx（TDC 官方导出）或 .txt（Excel 另存为 Unicode 文本）")
            data = upload.stream.read(_FORM_FILE_LIMIT + 1)
            if len(data) > _FORM_FILE_LIMIT:
                raise _Invalid(f"文件超过 {_FORM_FILE_LIMIT // (1024 * 1024)} MB 上限")
            if not data:
                raise _Invalid("上传的文件是空的")
            original_path = None  # 浏览器不给真实路径：备份就是唯一依据
        else:
            try:
                resolved, data = MB.read_designated(raw_path, _FORM_FILE_LIMIT)
            except IMP.ManualImportError as exc:
                return import_error(exc)
            name, suffix, original_path = resolved.name, resolved.suffix.lower(), str(resolved)
        digest = hashlib.sha256(data).hexdigest()
        new_backup = MB.backup_name_for(digest, suffix)
        current = baseline_file.get()
        encrypted = False
        try:
            IMP.source_from_bytes(data, day, name=name)
        except IMP.ManualImportError as exc:
            if exc.code != "E_ENCRYPTED_WORKBOOK" or IMP.source_format(data, name) != "xlsx":
                return import_error(exc)
            if not XP.ready(store.config()):
                return ctx.json_error(422, exc.code, ENCRYPTED_BASELINE_TEXT, diagnostic=exc.diagnostic or None)
            encrypted = True
        target = MB.write_backup(backup_dir(), new_backup, data)
        if encrypted:
            # 代读只读插件数据目录里的这份备份（本机磁盘上的普通 .xlsx），原文件不交给 Excel。
            try:
                parse_baseline_bytes(data, day, new_backup, target)
            except IMP.ManualImportError as exc:
                if current is None or current["backup_name"] != new_backup:
                    MB.remove_backup(backup_dir(), new_backup)
                return import_error(exc)
        baseline_file.set(
            original_path=original_path, original_name=name, data_date=day, sha256=digest,
            size=len(data), backup_name=new_backup,
        )
        if current is not None and current["backup_name"] != new_backup:
            MB.remove_backup(backup_dir(), current["backup_name"])  # 只留一份备份
        # 基线文件与固定互斥：设了基线文件就取消固定。
        manual_baselines.unpin()
        return ctx.json_ok(baseline_file_payload())

    @bp.post("/manual-baseline-file/clear")
    @guarded
    def manual_baseline_file_clear():
        cleared = clear_baseline_file()
        return ctx.json_ok({**baseline_file_payload(), "cleared": cleared})

    @bp.post("/import-scan")
    @guarded
    def import_scan():
        """扫描监控目录，返回候选清单与「最后修改时间最新」的那个（不合格就转人工）。"""
        value = body() if isinstance(body(), Mapping) else {}
        default_dir = ctx.plugin_data_dir(host.manifest.id) / IMP.DEFAULT_SUBDIR
        default_dir.mkdir(parents=True, exist_ok=True)
        try:
            directory = IMP.resolve_scan_dir(value.get("dir"), default_dir=default_dir)
        except IMP.ManualImportError as exc:
            return import_error(exc)
        try:
            result = IMP.scan_directory(
                directory, settle_seconds=_SCAN_SETTLE_SECONDS,
                # Excel 代读开着时，最新那份是加密 xlsx 也可以选中。
                allow_encrypted=XP.ready(store.config()),
            )
        except IMP.ManualImportError as exc:
            return import_error(exc)
        dir_id = IMP.make_scan_token(_SCAN_SECRET, directory, "", (0, 0))[:16]
        _SCAN_DIRS.pop(dir_id, None)
        _SCAN_DIRS[dir_id] = directory
        while len(_SCAN_DIRS) > _SCAN_DIRS_LIMIT:
            _SCAN_DIRS.pop(next(iter(_SCAN_DIRS)), None)
        selected = None
        if result.selected:
            target = directory / result.selected
            signature = IMP.stat_signature(target)
            try:
                # 扫描时就把内容摘要绑进令牌：之后即使同 size 覆盖写 + 复原 mtime，导入也会被拒。
                digest = hashlib.sha256(IMP.read_verified_bytes(target, signature)).hexdigest()
            except IMP.ManualImportError as exc:
                return import_error(exc)
            selected = {
                "name": result.selected,
                "mtime": next((e.mtime for e in result.entries if e.name == result.selected), ""),
                "size": signature[0],
                "sha256": digest[:12],
                "viaExcel": bool(result.via_excel),
                "token": IMP.make_scan_token(
                    _SCAN_SECRET, directory, result.selected, signature, digest
                ),
            }
        return ctx.json_ok({
            "dir": directory.name,
            # 实际扫描的完整路径与允许根：文件放错目录树时，用户能自己对上。
            "dirPath": str(directory),
            "dirId": dir_id,
            "roots": [root.name for root in IMP.allowed_roots(default_dir)],
            "rootPaths": [str(root) for root in IMP.allowed_roots(default_dir)],
            "entries": [
                {"name": e.name, "mtime": e.mtime, "size": e.size, "ok": e.ok, "reason": e.reason}
                for e in result.entries
            ],
            "selected": selected,
            "reason": result.reason,
            "hint": "只认最后修改时间最新的那份；它不合格或时间并列就转人工，不会退回更旧的文件",
        })

    @bp.post("/import-form")
    @guarded
    def import_form():
        """用本地导出的 TDC 数模表单出一次日报（零临时文件；与此前的手工导入比日变化）。

        接受官方 .xlsx，或 Excel「另存为文本」得到的 .txt（TAB 分隔）。可选字段 keepBaseline
        （默认 1）：0 时照样读基线做比较，但不把本次留作下次的基线。
        """
        form, files = _memory_form()
        upload = files.get("file")
        scan_name = str(form.get("scanName") or "").strip()
        if upload is None or not upload.filename:
            if not scan_name:
                raise _Invalid("请选择要导入的报表文件（TDC 数模官方导出的 .xlsx，或 Excel 另存的 .txt）")
        raw_date = str(form.get("dataDate") or "").strip()
        if not raw_date:
            raise _Invalid("请填写这份报表的数据截至日期（不会用导入时间代替）")
        data_date = _iso_date(raw_date, "数据截至日期")
        if data_date > _import_today():
            # 日期是用户手填的，而它决定基线的保留期清理（早于「该日期 − 90 天」的基线会被删）和旧数据判定：
            # 手滑填成未来日期会删掉旧基线，并让之后每次正常导入都被当成旧数据。直接拒绝。
            raise _Invalid(f"数据截至日期 {data_date.isoformat()} 晚于今天，请检查是否填错")
        keep_baseline = _form_bool(form, "keepBaseline", default=True)
        raw_baseline = str(form.get("baselineDate") or "").strip()
        baseline_date = _iso_date(raw_baseline, "对比基线日期") if raw_baseline else None
        scope = S.Scope(
            _str_list(_form_list(form, "projects"), "项目/车型"),
            _str_list(_form_list(form, "departments"), "归属科室"),
        )
        texts = _texts({
            "region": form.get("region") or "",
            "greeting": form.get("greeting") or "",
            "planText": form.get("planText") or "",
        })
        if scan_name:
            # 扫描句柄：前端只回传名字与令牌，真实路径由服务端重新解析并校验。
            key = str(form.get("scanDirId") or "").strip()
            directory = _SCAN_DIRS.get(key)
            if directory is None:
                return ctx.json_error(409, "E_SCAN_EXPIRED", "扫描结果已失效（程序重启过），请重新扫描")
            default_dir = ctx.plugin_data_dir(host.manifest.id) / IMP.DEFAULT_SUBDIR
            try:
                # 每次访问都重新解析并重查允许根（不信任扫描时缓存的路径）
                directory = IMP.resolve_scan_dir(str(directory), default_dir=default_dir)
            except IMP.ManualImportError as exc:
                return import_error(exc)
            candidate = directory / scan_name
            try:
                IMP.ensure_direct_child(candidate, directory)
                signature = IMP.stat_signature(candidate)
            except IMP.ManualImportError as exc:
                return import_error(exc)
            except OSError:
                return ctx.json_error(422, "E_FILE_GONE", "扫描到的文件已经不见了，请重新扫描")
            try:
                # 校验与解析必须是同一份字节：读一次句柄，之后只解析这份内容。
                payload_bytes = IMP.read_verified_bytes(candidate, signature)
            except IMP.ManualImportError as exc:
                return import_error(exc)
            digest = hashlib.sha256(payload_bytes).hexdigest()
            if not IMP.verify_scan_token(
                _SCAN_SECRET, form.get("scanToken") or "", directory, scan_name, signature, digest
            ):
                return ctx.json_error(
                    409, "E_SCAN_STALE", "文件在扫描之后被改动或替换过，请重新扫描后再生成"
                )
            source_name = scan_name
            proxy_target: tuple[Path, tuple[int, int]] | None = (candidate, signature)
        else:
            proxy_target = None
            # 上传：整份读进内存（multipart 也在内存里），不写任何临时文件。
            payload_bytes = upload.stream.read(_FORM_FILE_LIMIT + 1)
            if len(payload_bytes) > _FORM_FILE_LIMIT:
                raise _Invalid(f"文件超过 {_FORM_FILE_LIMIT // (1024 * 1024)} MB 上限")
            if not payload_bytes:
                raise _Invalid("上传的文件是空的")
            digest = hashlib.sha256(payload_bytes).hexdigest()
            source_name = Path(upload.filename).name
        source_format = IMP.source_format(payload_bytes, source_name)
        try:
            parsed = IMP.source_from_bytes(payload_bytes, data_date, name=source_name)
        except IMP.ManualImportError as exc:
            # Excel 代读：只对「扫描目录里、受终端加密的 xlsx」生效，且代读开关要开着。
            # 上传来的密文不落盘，所以上传入口不走代读。
            if not (
                exc.code == "E_ENCRYPTED_WORKBOOK"
                and proxy_target is not None
                and source_format == "xlsx"
                and XP.ready(store.config())
            ):
                if (
                    exc.code == "E_ENCRYPTED_WORKBOOK" and proxy_target is None
                    and source_format == "xlsx" and XP.ready(store.config())
                ):
                    # 代读已开启，但这份是页面上传来的：正确动作是放进扫描目录，而不是「一键生成」。
                    return ctx.json_error(
                        422, exc.code, IMP.ENCRYPTED_UPLOAD_TEXT, diagnostic=exc.diagnostic or None
                    )
                return import_error(exc)
            target, target_signature = proxy_target
            try:
                parsed = IMP.source_from_excel(target, data_date)
                # Excel 是按路径另开的：读完再核对一次本进程视图下的内容摘要，
                # 期间文件被替换或改动过就整份作废。
                again = hashlib.sha256(IMP.read_verified_bytes(target, target_signature)).hexdigest()
            except IMP.ManualImportError as proxy_exc:
                return import_error(proxy_exc)
            if again != digest:
                return ctx.json_error(
                    409, "E_SCAN_STALE", "文件在扫描之后被改动或替换过，请重新扫描后再生成"
                )
            source_format = IMP.FORMAT_EXCEL_PROXY
        return _manual_report(
            parsed, scope, texts, name=source_name, digest=digest, source_format=source_format,
            keep_baseline=keep_baseline, baseline_date=baseline_date,
        )

    @bp.post("/eml")
    @guarded
    def eml():
        payload = body()
        if not isinstance(payload, Mapping):
            raise _Invalid("请求体必须是 JSON 对象")
        if str(payload.get("mode") or "") == "manual":
            # 手工导入的报告没有服务端快照，/eml 只会重算归档数据；直接拒绝，避免发出与页面不一致的草稿。
            return ctx.json_error(
                409, "EmlUnavailableForManual", "手工导入的报告不提供 .eml 草稿；请复制正文后手动发送"
            )
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
        if result["statusGate"]["blocked"]:
            # TDC-20261029：状态列是数字码时份数与签单率都不可信，宁可不出报。
            return ctx.json_error(409, "StatusGateBlocked", result["statusGate"]["text"])
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

    # ── 定时生成（DSH-V2-23）─────────────────────────────────────────

    def schedule_payload() -> dict[str, Any]:
        """定时生成状态：开关/时刻/暂停、下次执行、当天槽、最近一次成功生成摘要。"""
        binding = slot_store.get_binding(SCH.DAILY_PROJECT_ID, SP.DAILY_REPORT_JOB_ID)
        enabled = bool(binding and binding["mode"] == SP.JOB_KIND_FIXED)
        paused = bool(binding["paused"]) if binding else False
        times = list(binding["times"]) if enabled else []
        configured = times[0] if times else SP.DEFAULT_DAILY_REPORT_TIME.strftime("%H:%M")
        now = now_utc()
        next_run_at: str | None = None
        if enabled and not paused:
            policy_binding = SP.daily_report_binding(
                SCH.DAILY_PROJECT_ID,
                times=times or (SP.DEFAULT_DAILY_REPORT_TIME,),
                paused=paused,
            )
            moment = SP.next_slot_at(policy_binding, now=now)
            next_run_at = moment.isoformat() if moment is not None else None
        return {
            "enabled": enabled,
            "time": configured,
            "paused": paused,
            "nextRunAt": next_run_at,
            # 租约 token / owner 是收尾 fencing 凭据，只读路由不外露。
            "today": [
                {
                    "jobId": row["jobId"],
                    "scheduledTime": row["scheduledTime"],
                    "status": row["status"],
                    "attempt": row["attempt"],
                    "lastErrorCode": row["lastErrorCode"],
                    "nextAttemptAt": row["nextAttemptAt"],
                }
                # 业务日期与 /generate 的「今天」同一口径（测试可注入），不用 UTC 日期。
                for row in slot_store.list_slots(SCH.DAILY_PROJECT_ID, _today())
            ],
            "latest": SCH.report_summary(reports.latest()),
        }

    @bp.get("/schedule")
    def schedule_read():
        return ctx.json_ok(schedule_payload())

    @bp.put("/schedule")
    @guarded
    def schedule_write():
        payload = body()
        if not isinstance(payload, Mapping):
            raise _Invalid("请求体必须是 JSON 对象")
        enabled = payload.get("enabled", False)
        paused = payload.get("paused", False)
        if not isinstance(enabled, bool):
            raise _Invalid("enabled 必须是布尔值")
        if not isinstance(paused, bool):
            raise _Invalid("paused 必须是布尔值")
        raw_time = payload.get("time", SP.DEFAULT_DAILY_REPORT_TIME.strftime("%H:%M"))
        if not isinstance(raw_time, str):
            raise _Invalid("time 必须是 'HH:MM' 文本")
        try:
            times = SP.daily_report_binding(SCH.DAILY_PROJECT_ID, times=(raw_time,)).times
        except (TypeError, ValueError) as exc:
            raise _Invalid(f"time {exc}") from None
        if enabled:
            slot_store.set_binding(
                SCH.DAILY_PROJECT_ID,
                SP.DAILY_REPORT_JOB_ID,
                SP.JOB_KIND_FIXED,
                [item.strftime("%H:%M") for item in times],
                paused,
            )
        else:
            # 关闭定时生成 = interval 绑定（日报没有 interval 语义，只是「不排槽」）。
            slot_store.set_binding(
                SCH.DAILY_PROJECT_ID, SP.DAILY_REPORT_JOB_ID, SP.JOB_KIND_INTERVAL, [], paused
            )
        return ctx.json_ok(schedule_payload())

    @bp.get("/scheduled/latest")
    def scheduled_latest():
        latest = reports.latest()
        if latest is None:
            return ctx.json_error(404, "NotFound", "还没有定时生成的日报")
        return ctx.json_ok(latest)

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
        blocker = SCH.refresh_scope_blocker(ctx.db, watchlist_only)
        if blocker is not None:
            # 开关关：日报只认全量快照，一键生成要触发全量抓取；同步范围由交付物明细页维护。
            return ctx.json_error(409, "WatchlistScope", blocker)
        view, reused = SCH.start_refresh(
            runner=runner, archive=archive, db=ctx.db, watchlist_only=watchlist_only
        )
        return ctx.json_ok({**view, "reused": reused})

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
