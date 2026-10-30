# -*- coding: utf-8 -*-
"""专家模式自检插件后端（聚合只读系统状态与环境自检）。

本插件提供只读自检能力，聚合以下四大关键状态：
1. 统一账号会话状态（Aras / TDC 企业域账号会话有效性）；
2. Excel 本机运行环境（安装、主版本与激活状态，服务异常时回落 need_check）；
3. 插件更新通道状态（签名包更新服务与可信密钥配置，不可用时声明 unknown）；
4. 项目注册表状态（多项目管理配置与当前项目，未托管时声明 unknown）。

全程只读，不新增任何修改或写操作路由，所有响应载荷受到严格键白名单保护，
且对任何敏感内容（凭据、令牌、Cookie、内网地址等）进行脱敏或排除。
"""

from __future__ import annotations

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
        ]
        return ctx.json_ok({"items": items})
