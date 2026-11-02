# -*- coding: utf-8 -*-
"""专家模式自检插件后端（聚合只读系统状态与环境自检）。

本插件提供只读自检能力，聚合以下六大关键状态：
1. 统一账号会话状态（Aras / TDC 企业域账号会话有效性）；
2. Excel 本机运行环境（安装、主版本与激活状态，服务异常时回落 need_check）；
3. 插件更新通道状态（签名包更新服务与可信密钥配置，不可用时声明 unknown）；
4. 项目注册表状态（多项目管理配置与当前项目，未托管时声明 unknown）；
5. 同步连接器状态（启用同步绑定、凭据配置布尔、最近成功时间与失败枚举）；
6. 后台同步调度状态（调度器是否运行、间隔、固定时刻模式与今日槽状态计数）。

全程只读，不新增任何修改或写操作路由，所有响应载荷受到严格键白名单保护，
且对任何敏感内容（凭据、令牌、Cookie、内网地址等）进行脱敏或排除。
新两项检查使用 ``not_run`` / ``unable`` / ``fail`` 三态区分「未执行」「无法检查」
「失败」，任何异常都不会写成 ok。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.redaction import redact_sensitive_text


def _utc_now() -> str:
    """生成标准化 UTC 时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_summary(text: str) -> str:
    """脱敏并确保文本不含敏感标识。"""
    if not text:
        return ""
    return redact_sensitive_text(str(text))


# ── DSH-V2-31：新两项检查的取值与载荷白名单 ────────────────────────────────

#: 新两项检查的取值闭集；既有 4 项继续使用 ok/warn/need_check/unknown（不改名）。
_STATE_OK = "ok"
_STATE_WARN = "warn"
_STATE_NOT_RUN = "not_run"
_STATE_UNABLE = "unable"
_STATE_FAIL = "fail"

#: 单项导出键闭集：任何新增字段都必须先在此登记，否则 :func:`_finalize_item` 丢弃。
_ITEM_FIELDS = ("name", "state", "detail", "checkedAt", "facts")

#: 连接器 facts 的扁平白名单（计数 / 布尔 / 枚举 / 时间）。
_CONNECTOR_FACT_FIELDS = frozenset(
    {
        "bindingCount",
        "credentialConfiguredCount",
        "sourceTypeCount",
        "sourceTypes",
        "lastSuccessAt",
        "lastFailureState",
    }
)

#: 调度 facts 的扁平白名单（计数 / 布尔 / 枚举 / 时间）。
_SCHEDULER_FACT_FIELDS = frozenset(
    {
        "paused",
        "intervalSeconds",
        "fixedMode",
        "fixedBindings",
        "nextRunSeconds",
        "slotCheck",
        "slotPending",
        "slotLeased",
        "slotSucceeded",
        "slotFailed",
        "slotExpired",
        "slotPausedSkipped",
    }
)

#: 既有 sync_state 枚举闭集；闭集外的值折叠为 unknown，绝不原样导出。
_SYNC_STATE_ENUM = frozenset(
    {"idle", "running", "success", "needs_attention", "failed", "expired", "partial", "unknown"}
)

#: 视为同步失败的 sync_state 枚举值（只导出枚举，不读取错误原文）。
_SYNC_FAILURE_STATES = frozenset({"failed", "needs_attention"})

#: 槽状态 -> facts 键（与 ``services.schedule_slots.STATUSES`` 对齐，只读消费）。
_SLOT_STATUS_FIELDS = (
    ("pending", "slotPending"),
    ("leased", "slotLeased"),
    ("succeeded", "slotSucceeded"),
    ("failed", "slotFailed"),
    ("expired", "slotExpired"),
    ("paused_skipped", "slotPausedSkipped"),
)

#: last_success_at 的既有写入格式；不匹配的值不导出，避免把任意文本当时间透出。
_SYNC_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
#: source_type 只允许小写标识符；其余折叠为 other（不外露任意连接器配置文本）。
_SOURCE_TYPE_RE = re.compile(r"^[a-z0-9_]{1,32}$")
#: detail 摘要上限：只读摘要，不承载业务原文。
_DETAIL_LIMIT = 300


def _safe_detail(text: str) -> str:
    """新检查项 detail 的唯一出口：脱敏 + 截断。"""
    return redact_sensitive_text(str(text), limit=_DETAIL_LIMIT)


def _finalize_item(item: dict[str, Any], fact_fields: frozenset[str]) -> dict[str, Any]:
    """按显式键闭集裁剪单项载荷；facts 再按显式键闭集过滤。"""
    allowed: dict[str, Any] = {key: item[key] for key in _ITEM_FIELDS if key in item}
    facts = allowed.get("facts")
    if not isinstance(facts, dict):
        facts = {}
    allowed["facts"] = {key: facts[key] for key in sorted(facts) if key in fact_fields}
    return allowed


def _safe_int(value: Any) -> int | None:
    """只接受真正的整数（布尔不是计数），其余返回 None。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _enum_text(value: Any, allowed: frozenset[str], default: str) -> str:
    """把任意值折叠到显式枚举闭集内。"""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _safe_time_text(value: Any) -> str | None:
    """只接受既有 last_success_at 格式的时间文本。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _SYNC_TIME_RE.match(text) else None


def _time_sort_key(text: str | None) -> datetime | None:
    """把 last_success_at 文本解析为可比较的 UTC 时间；无法解析返回 None。"""
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _resolve_session_registry(ctx: Any) -> Any:
    """从上下文、数据库或当前应用中获取会话注册表。"""
    # 1. 优先从 host.context.services 获取
    if hasattr(ctx, "services") and ctx.services:
        reg = ctx.services.get("domain_sessions") or ctx.services.get("session_registry")
        if reg is not None:
            return reg
    # 2. 尝试从 host.context.db 注入的属性中获取
    if hasattr(ctx, "db") and ctx.db is not None:
        reg = getattr(ctx.db, "domain_sessions", None) or getattr(ctx.db, "session_registry", None)
        if reg is not None:
            return reg
    # 3. 尝试从 Flask current_app.extensions 获取
    try:
        from flask import current_app

        if current_app and hasattr(current_app, "extensions"):
            reg = current_app.extensions.get("domain_sessions") or current_app.extensions.get("session_registry")
            if reg is not None:
                return reg
    except Exception:
        pass
    return None


def _check_unified_sessions(ctx: Any) -> dict[str, Any]:
    """检查统一账号会话状态。"""
    reg = _resolve_session_registry(ctx)
    if reg is None:
        return {
            "name": "统一账号会话",
            "state": "unknown",
            "detail": "统一账号会话服务未注册或不可用",
            "checkedAt": _utc_now(),
        }

    try:
        if hasattr(reg, "payload") and callable(reg.payload):
            sessions = reg.payload()
        elif isinstance(reg, dict):
            sessions = reg
        elif hasattr(reg, "get_sessions") and callable(reg.get_sessions):
            sessions = reg.get_sessions()
        else:
            sessions = {}

        if not sessions:
            return {
                "name": "统一账号会话",
                "state": "unknown",
                "detail": "暂未记录任何系统会话",
                "checkedAt": _utc_now(),
            }

        active: list[str] = []
        expired_or_missing: list[str] = []
        for key, val in sessions.items():
            if isinstance(val, dict):
                is_auth = bool(val.get("authenticated"))
                is_exp = bool(val.get("expired"))
                if is_auth and not is_exp:
                    active.append(str(key).upper())
                else:
                    expired_or_missing.append(str(key).upper())
            else:
                expired_or_missing.append(str(key).upper())

        if not active:
            state = "need_check"
            detail = "统一账号未登录或会话已失效，部分在线功能受限"
        elif expired_or_missing:
            state = "warn"
            detail = f"部分系统会话有效（已连接 {', '.join(active)}；需重新登录 {', '.join(expired_or_missing)}）"
        else:
            state = "ok"
            detail = f"所有系统会话正常（已连接 {', '.join(active)}）"

        return {
            "name": "统一账号会话",
            "state": state,
            "detail": _safe_summary(detail),
            "checkedAt": _utc_now(),
        }
    except Exception as exc:
        return {
            "name": "统一账号会话",
            "state": "need_check",
            "detail": _safe_summary(f"读取会话状态异常：{exc}"),
            "checkedAt": _utc_now(),
        }


def _check_excel_environment() -> dict[str, Any]:
    """检查本机 Excel 运行环境。"""
    try:
        import services.excel_env_check as env_check

        res = env_check.check_excel_environment()
        installed = bool(res.get("installed"))
        activation = res.get("activation") or {}
        act_state = activation.get("state")
        version = res.get("version")

        if not installed:
            return {
                "name": "表格环境",
                "state": "need_check",
                "detail": "未检测到本机安装的表格软件",
                "checkedAt": _utc_now(),
            }

        if act_state == "activated":
            state = "ok"
            ver_text = f"（版本 {version}）" if version else ""
            detail = f"表格软件已就绪{ver_text}，授权正常"
        elif act_state == "unlicensed":
            state = "need_check"
            detail = "表格软件未激活或授权已失效"
        else:
            state = "need_check"
            act_detail = activation.get("detail") or "需要确认软件授权状态"
            detail = f"表格软件已安装，{act_detail}"

        return {
            "name": "表格环境",
            "state": state,
            "detail": _safe_summary(detail),
            "checkedAt": _utc_now(),
        }
    except Exception as exc:
        # 服务抛错时绝不伪报通过，严格返回 need_check 并附可读原因
        return {
            "name": "表格环境",
            "state": "need_check",
            "detail": _safe_summary(f"检测表格环境失败：{exc}"),
            "checkedAt": _utc_now(),
        }


def _resolve_plugin_updates(ctx: Any) -> Any:
    """获取插件更新通道服务对象。"""
    if hasattr(ctx, "services") and ctx.services:
        updates = ctx.services.get("plugin_updates")
        if updates is not None:
            return updates
    try:
        from flask import current_app

        if current_app and hasattr(current_app, "extensions"):
            return current_app.extensions.get("plugin_updates")
    except Exception:
        pass
    return None


def _check_update_channel(ctx: Any) -> dict[str, Any]:
    """检查插件更新通道状态。"""
    updates = _resolve_plugin_updates(ctx)
    if updates is None:
        return {
            "name": "更新通道",
            "state": "unknown",
            "detail": "更新通道未启用或不可用",
            "checkedAt": _utc_now(),
        }

    try:
        trusted_keys = getattr(updates, "trusted_keys", None)
        if trusted_keys is not None:
            if not trusted_keys:
                return {
                    "name": "更新通道",
                    "state": "warn",
                    "detail": "未配置可信公钥，暂无法接收新更新",
                    "checkedAt": _utc_now(),
                }
            count = len(trusted_keys)
            pending = updates.pending() if hasattr(updates, "pending") else []
            if pending:
                detail = f"更新通道正常（配置 {count} 个可信公钥，有 {len(pending)} 个待生效更新）"
            else:
                detail = f"更新通道正常（配置 {count} 个可信公钥，已是最新状态）"
            return {
                "name": "更新通道",
                "state": "ok",
                "detail": _safe_summary(detail),
                "checkedAt": _utc_now(),
            }

        return {
            "name": "更新通道",
            "state": "ok",
            "detail": "更新通道服务就绪",
            "checkedAt": _utc_now(),
        }
    except Exception as exc:
        return {
            "name": "更新通道",
            "state": "need_check",
            "detail": _safe_summary(f"读取更新通道异常：{exc}"),
            "checkedAt": _utc_now(),
        }


def _check_project_registry() -> dict[str, Any]:
    """检查项目注册表状态。"""
    try:
        from vse_boot import api, projects

        layout = api.managed_layout() if api else None
        if layout is None or projects is None:
            return {
                "name": "项目注册表",
                "state": "unknown",
                "detail": "单项目模式运行，未由启动器管理",
                "checkedAt": _utc_now(),
            }

        reg = projects.ProjectRegistry(layout)
        active_id = reg.active_id
        all_projs = reg.projects()
        active_info = reg.get(active_id) or {}
        name = active_info.get("name") or active_id
        return {
            "name": "项目注册表",
            "state": "ok",
            "detail": _safe_summary(f"当前项目为「{name}」（共 {len(all_projs)} 个项目）"),
            "checkedAt": _utc_now(),
        }
    except ImportError:
        return {
            "name": "项目注册表",
            "state": "unknown",
            "detail": "多项目管理模块不可用",
            "checkedAt": _utc_now(),
        }
    except Exception as exc:
        return {
            "name": "项目注册表",
            "state": "need_check",
            "detail": _safe_summary(f"读取项目注册表异常：{exc}"),
            "checkedAt": _utc_now(),
        }


def _empty_connector_facts() -> dict[str, Any]:
    """连接器 facts 的零值形态（所有键都在显式白名单内）。"""
    return {
        "bindingCount": 0,
        "credentialConfiguredCount": 0,
        "sourceTypeCount": 0,
        "sourceTypes": "",
        "lastSuccessAt": None,
        "lastFailureState": None,
    }


def _connector_item(state: str, detail: str, facts: dict[str, Any]) -> dict[str, Any]:
    """组装连接器单项（唯一键集合出口）。"""
    return _finalize_item(
        {
            "name": "同步连接器",
            "state": state,
            "detail": _safe_detail(detail),
            "checkedAt": _utc_now(),
            "facts": facts,
        },
        _CONNECTOR_FACT_FIELDS,
    )


def _check_sync_connectors(ctx: Any) -> dict[str, Any]:
    """检查同步连接器：只读启用绑定，按 source_type 汇总，不读取业务原文。

    读取口径复用既有 ``db.list_eligible_sync_bindings(None)``：只用
    ``source_type`` / ``sync_state`` / ``last_success_at`` / ``credential_configured``
    四个既有字段，不读取 external_key、匹配规则、映射、错误原文。
    """
    db = getattr(ctx, "db", None)
    list_bindings = getattr(db, "list_eligible_sync_bindings", None)
    if db is None or not callable(list_bindings):
        return _connector_item(
            _STATE_UNABLE,
            "同步绑定数据源不可用，无法检查连接器状态",
            _empty_connector_facts(),
        )

    try:
        bindings = list(list_bindings(None))
    except Exception as exc:
        # 只报异常类型（枚举口径），不导出异常原文。
        return _connector_item(
            _STATE_UNABLE,
            f"读取同步绑定失败（{type(exc).__name__}），无法检查连接器状态",
            _empty_connector_facts(),
        )

    total = 0
    configured = 0
    sources: dict[str, dict[str, Any]] = {}
    last_success: str | None = None
    last_success_key: datetime | None = None
    failure_state: str | None = None

    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        total += 1
        if bool(binding.get("credential_configured")):
            configured += 1

        raw_source = str(binding.get("source_type") or "").strip().lower()
        source_key = raw_source if _SOURCE_TYPE_RE.match(raw_source) else "other"
        bucket = sources.setdefault(
            source_key,
            {"count": 0, "lastSuccessAt": None, "lastSuccessKey": None, "failureState": None},
        )
        bucket["count"] += 1

        success_text = _safe_time_text(binding.get("last_success_at"))
        success_key = _time_sort_key(success_text)
        if success_key is not None:
            if bucket["lastSuccessKey"] is None or success_key > bucket["lastSuccessKey"]:
                bucket["lastSuccessKey"] = success_key
                bucket["lastSuccessAt"] = success_text
            if last_success_key is None or success_key > last_success_key:
                last_success_key = success_key
                last_success = success_text

        sync_state = _enum_text(binding.get("sync_state"), _SYNC_STATE_ENUM, "unknown")
        if sync_state in _SYNC_FAILURE_STATES:
            bucket["failureState"] = sync_state
            failure_state = sync_state

    if total == 0:
        return _connector_item(
            _STATE_NOT_RUN,
            "尚未配置启用的同步连接器绑定（未执行过同步）",
            _empty_connector_facts(),
        )

    source_names = sorted(sources)
    source_types_text = ",".join(source_names[:12])
    if len(source_names) > 12:
        source_types_text = ",".join(source_names[:12] + ["other"])

    breakdown = "；".join(
        f"{name} {bucket['count']} 个"
        + (f"（最近成功 {bucket['lastSuccessAt']}）" if bucket["lastSuccessAt"] else "")
        for name, bucket in sorted(sources.items())
    )

    facts = {
        "bindingCount": total,
        "credentialConfiguredCount": configured,
        "sourceTypeCount": len(sources),
        "sourceTypes": source_types_text,
        "lastSuccessAt": last_success,
        "lastFailureState": failure_state,
    }

    if failure_state is not None:
        state = _STATE_FAIL
        detail = f"启用同步绑定 {total} 个；存在同步失败（枚举 {failure_state}）。{breakdown}"
    elif last_success is None:
        state = _STATE_NOT_RUN
        detail = f"启用同步绑定 {total} 个，但从未成功同步过。{breakdown}"
    elif configured < total:
        state = _STATE_WARN
        detail = (
            f"启用同步绑定 {total} 个，其中 {total - configured} 个未配置凭据，"
            f"暂不能执行同步。{breakdown}"
        )
    else:
        state = _STATE_OK
        detail = f"启用同步绑定 {total} 个，凭据均已配置；最近成功同步于 {last_success}。{breakdown}"

    return _connector_item(state, detail, facts)


def _scheduler_item(state: str, detail: str, facts: dict[str, Any]) -> dict[str, Any]:
    """组装调度单项（唯一键集合出口）。"""
    return _finalize_item(
        {
            "name": "同步调度",
            "state": state,
            "detail": _safe_detail(detail),
            "checkedAt": _utc_now(),
            "facts": facts,
        },
        _SCHEDULER_FACT_FIELDS,
    )


def _today_fixed_slot_counts(ctx: Any) -> tuple[dict[str, int] | None, str]:
    """只读统计北京时间当天固定时刻槽状态；返回 (计数, 失败原因枚举)。

    经 ``services.schedule_slots.SlotStore`` 与 ``SYNC_CONTROL_TABLE_PREFIX``
    只读 ``list_bindings('fixed')`` / ``list_slots(project, today)``；槽表不存在
    或读取异常时返回 ``None``（调用方据此声明「无法检查」），绝不建表、不迁移。
    """
    db = getattr(ctx, "db", None)
    if db is None or not hasattr(db, "get_connection"):
        return None, "db_unavailable"
    try:
        from core.time_rules import now_utc, to_beijing
        from services.schedule_slots import SYNC_CONTROL_TABLE_PREFIX, SlotStore

        store = SlotStore(db, SYNC_CONTROL_TABLE_PREFIX, clock=now_utc)
        business_date = to_beijing(now_utc()).date()
        counts = {status: 0 for status, _ in _SLOT_STATUS_FIELDS}
        for binding in store.list_bindings("fixed"):
            project_id = str(binding.get("projectId") or "").strip()
            if not project_id:
                continue
            for slot in store.list_slots(project_id, business_date):
                status = str(slot.get("status") or "").strip().lower()
                if status in counts:
                    counts[status] += 1
        return counts, ""
    except Exception as exc:
        # 槽表不存在（插件未加载/未迁移）或读取异常：只报异常类型枚举。
        return None, type(exc).__name__


def _check_sync_scheduler(ctx: Any) -> dict[str, Any]:
    """检查后台同步调度器：只读 ``get_status()`` 与今日固定槽计数。"""
    empty_facts = {
        "paused": False,
        "intervalSeconds": 0,
        "fixedMode": "off",
        "fixedBindings": 0,
        "nextRunSeconds": None,
        "slotCheck": "off",
    }
    try:
        from services.project_status_scheduler import get_global_scheduler
    except Exception as exc:
        return _scheduler_item(
            _STATE_UNABLE,
            f"同步调度服务不可用（{type(exc).__name__}），无法检查",
            empty_facts,
        )

    try:
        scheduler = get_global_scheduler()
    except Exception as exc:
        return _scheduler_item(
            _STATE_UNABLE,
            f"读取调度器实例失败（{type(exc).__name__}），无法检查",
            empty_facts,
        )

    if scheduler is None:
        return _scheduler_item(
            _STATE_NOT_RUN,
            "后台同步调度器未启动（未执行）",
            empty_facts,
        )

    try:
        status = scheduler.get_status()
    except Exception as exc:
        return _scheduler_item(
            _STATE_UNABLE,
            f"读取调度器状态失败（{type(exc).__name__}），无法检查",
            empty_facts,
        )
    if not isinstance(status, dict):
        return _scheduler_item(
            _STATE_UNABLE,
            "调度器状态格式不可识别，无法检查",
            empty_facts,
        )

    if not bool(status.get("running")):
        return _scheduler_item(
            _STATE_NOT_RUN,
            "后台同步调度器已停止（未执行）",
            empty_facts,
        )

    paused = bool(status.get("paused"))
    interval = _safe_int(status.get("intervalSeconds"))
    fixed_bindings = _safe_int(status.get("fixedBindings"))
    next_run = _safe_int(status.get("nextRunSeconds"))
    fixed_mode = "on" if status.get("fixedMode") == "on" else "off"

    facts: dict[str, Any] = {
        "paused": paused,
        "intervalSeconds": interval if interval is not None else 0,
        "fixedMode": fixed_mode,
        "fixedBindings": fixed_bindings if fixed_bindings is not None else 0,
        "nextRunSeconds": next_run,
        "slotCheck": "off",
    }
    parts = [
        "后台同步调度器运行中（{}），间隔 {} 秒".format(
            "已暂停" if paused else "已启用",
            facts["intervalSeconds"],
        )
    ]
    if next_run is not None and not paused:
        parts.append(f"约 {next_run} 秒后执行下一次同步")

    if fixed_mode != "on":
        parts.append("固定时刻模式关闭")
        state = _STATE_WARN if paused else _STATE_OK
        return _scheduler_item(state, "；".join(parts), facts)

    parts.append(f"固定时刻模式：{facts['fixedBindings']} 个绑定")
    counts, error_name = _today_fixed_slot_counts(ctx)
    if counts is None:
        facts["slotCheck"] = "unable"
        parts.append(f"固定时刻槽表不可用（{error_name or 'unknown'}），无法检查今日槽状态")
        return _scheduler_item(_STATE_UNABLE, "；".join(parts), facts)

    facts["slotCheck"] = "checked"
    for status_name, fact_key in _SLOT_STATUS_FIELDS:
        facts[fact_key] = counts[status_name]
    parts.append(
        "今日固定槽：待执行 {pending}、执行中 {leased}、成功 {succeeded}、失败 {failed}、"
        "已过期 {expired}、暂停跳过 {pausedSkipped}".format(
            pending=counts["pending"],
            leased=counts["leased"],
            succeeded=counts["succeeded"],
            failed=counts["failed"],
            expired=counts["expired"],
            pausedSkipped=counts["paused_skipped"],
        )
    )
    if counts["failed"] > 0:
        state = _STATE_FAIL
    elif counts["expired"] > 0 or counts["paused_skipped"] > 0 or paused:
        state = _STATE_WARN
    else:
        state = _STATE_OK
    return _scheduler_item(state, "；".join(parts), facts)


def register(host: Any) -> None:
    """注册自检插件路由。"""
    ctx = host.context
    bp = host.blueprint

    @bp.get("/self-check")
    def self_check() -> Any:
        items = [
            _check_unified_sessions(ctx),
            _check_excel_environment(),
            _check_update_channel(ctx),
            _check_project_registry(),
            _check_sync_connectors(ctx),
            _check_sync_scheduler(ctx),
        ]
        return ctx.json_ok({"items": items})
