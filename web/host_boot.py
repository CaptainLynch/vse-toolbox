# -*- coding: utf-8 -*-
"""宿主专用路由：版本、设置、宿主更新与健康检查（W13-02 迁自 web/app.py）。

这些路由属于宿主本身，不依赖任何可禁用的业务插件（CONTRACTS.md C8）：把实现从
``web/app.py`` 挪到这里只是换位置——路径、方法、信封、错误类型、endpoint 名全部
不变（``tests/test_route_contract_snapshot.py`` 的 golden 零差异是硬门禁）。

状态ful依赖（settings_store、domain_sessions 等）由 ``create_app`` 显式注入；
无状态的认证客户端、常量在本模块直接导入，保持与原实现同一来源。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from flask import jsonify, request

from core.credential_provider import (
    CredentialProviderError,
    delete_windows_generic_credential,
    store_windows_generic_credential,
)
from core.domain_identity import RECOVERY_ERROR_CODES, CredentialVaultError
from core.native_folder_picker import NativeFolderPickerError, choose_native_folder
from core.settings_store import SettingsValidationError, validate_local_directory
from core.version import get_app_version_info
from host.updates import PackageError
from services.aras_auth import ArasECMAuthClient, DEFAULT_ARAS_BASE_URL
from services.tdc_auth import TDCPasswordAuthClient

logger = logging.getLogger(__name__)

#: 交付物同步凭据在 Windows 凭据管理器中的引用名（与统一域账号登录共享）。
SYNC_CREDENTIAL_REF = "domain"


@dataclass(frozen=True)
class HostRouteDeps:
    """宿主路由依赖包：create_app 组合根显式注入，host_boot 不自行构建任何服务。"""

    settings_store: Any
    domain_sessions: Any
    credential_vault: Any
    excel_admin_service: Any | None
    tdc_export_cache: Any
    #: web/app.py 的写保护与响应助手（经参数注入避免 web.app ↔ host_boot 循环导入）
    local_mutation_error: Callable[[], Any]
    json_ok: Callable[..., Any]
    json_error: Callable[..., Any]
    sanitize_error_message: Callable[[Exception], str]
    validation_error: Callable[[dict[str, str]], Any]
    #: 统一续期协调器（web/app.py 组合根装配；DSH-V2-16）。为 None 时退回注册表
    #: 直连语义，登录/清除的既有响应键与状态码不变。
    session_renewal: Any | None = None


# ── 会话恢复闭集码（DSH-V2-16，契约 §4.3 / §8.4）────────────────────────────


def _recovery_code(deps: HostRouteDeps, exc: BaseException, system: str) -> str | None:
    """把登录失败异常映射到 §4.3 闭集 code；协调器未装配时返回 None（不加键）。

    优先级：异常自带的 ``recovery_code``（登录客户端按契约 §4.2 登记的语义，
    如 ``credential_invalid`` / ``login_challenge`` / ``forbidden``）→ 协调器
    ``classify``（按 HTTP 状态与阶段兜底）。两者都只允许 §4.3 闭集值。
    """
    coordinator = deps.session_renewal
    if coordinator is None:
        return None
    declared = getattr(exc, "recovery_code", None)
    if isinstance(declared, str) and declared in RECOVERY_ERROR_CODES:
        return declared
    try:
        return coordinator.classify(exc, system=system).code
    except Exception:  # noqa: BLE001 - 归类失败不得改变既有错误响应
        logger.warning("session recovery classification failed for %s", system)
        return None


def _login_result(deps: HostRouteDeps, system: str, exc: BaseException) -> dict[str, object]:
    """失败结果项：既有 ``ok``/``message`` 不变，增量附 §4.3 闭集 ``code``。"""
    item: dict[str, object] = {"ok": False, "message": deps.sanitize_error_message(exc)}
    code = _recovery_code(deps, exc, system)
    if code is not None:
        item["code"] = code
    return item


def _clear_domain_sessions(deps: HostRouteDeps, system: str | None) -> None:
    """统一清除：经协调器 ``clear()``（代次 +1、取消在途续期）；未装配时退回注册表。"""
    coordinator = deps.session_renewal
    if coordinator is not None:
        coordinator.clear(system)
        return
    deps.domain_sessions.clear(system)


def _bump_vault_epoch(deps: HostRouteDeps) -> None:
    """凭据库写入/清除成功后递增 vaultEpoch（契约 §7.2-3）：作废在途续期结果。"""
    bump = getattr(deps.domain_sessions, "bump_vault_epoch", None)
    if callable(bump):
        bump()


def register_host_service_routes(app: Any, deps: HostRouteDeps) -> None:
    """版本与设置路由（原 create_app 内联实现，逐字迁移）。"""

    @app.get("/api/version")
    def api_version():
        info = app.config.get("APP_VERSION_INFO") or get_app_version_info()
        response = jsonify({"ok": True, "data": info})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/settings")
    def api_settings_get():
        response = jsonify(
            {
                "ok": True,
                "data": {
                    "settings": deps.settings_store.get(),
                    "sessions": deps.domain_sessions.payload(),
                    "credentialVaultConfigured": deps.credential_vault.is_configured(),
                    "excelService": {"configured": deps.excel_admin_service is not None},
                },
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.patch("/api/settings")
    def api_settings_update():
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return deps.json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = deps.settings_store.update(payload)
            response = jsonify({"ok": True, "data": {"settings": data}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except SettingsValidationError as exc:
            return deps.validation_error(exc.fields)

    @app.post("/api/settings/folders/native")
    def api_settings_native_folder():
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        if app.config.get("TESTING"):
            return deps.json_error(503, "NativeFolderPickerUnavailable", "测试环境不打开本机文件夹选择器")
        payload = request.get_json(silent=True) or {}
        initial_value = payload.get("path", "") if isinstance(payload, dict) else ""
        initial_path: Path | None = None
        if isinstance(initial_value, str) and initial_value.strip():
            try:
                initial_path = Path(validate_local_directory(initial_value))
            except ValueError:
                initial_path = None
        try:
            selected = choose_native_folder(initial_path)
            selected_path = None if selected is None else validate_local_directory(str(selected))
            response = jsonify({"ok": True, "data": {"path": selected_path, "cancelled": selected is None}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except NativeFolderPickerError as exc:
            return deps.json_error(503, "NativeFolderPickerUnavailable", deps.sanitize_error_message(exc))
        except ValueError as exc:
            return deps.validation_error({"path": deps.sanitize_error_message(exc)})

    @app.post("/api/settings/domain-login")
    def api_domain_login():
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return deps.json_error(400, "ValidationError", "JSON object body is required")
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            return deps.validation_error({"credentials": "域用户名和密码不能为空"})
        results: dict[str, object] = {}
        # 统一登录前的既有全清：经协调器清除 = 代次 +1 + 取消在途续期（§7.1/§7.2）。
        _clear_domain_sessions(deps, None)
        try:
            login_result = ArasECMAuthClient().login(username.strip(), password)
            deps.domain_sessions.mark_authenticated(
                "aras", login_result.session, principal=username.strip(), source_root=DEFAULT_ARAS_BASE_URL
            )
            results["aras"] = {"ok": True}
        except Exception as exc:
            results["aras"] = _login_result(deps, "aras", exc)
        try:
            login_result = TDCPasswordAuthClient().login(username.strip(), password)
            deps.domain_sessions.mark_authenticated("tdc", login_result.session)
            results["tdc"] = {"ok": True}
        except Exception as exc:
            results["tdc"] = _login_result(deps, "tdc", exc)
        if any(isinstance(item, dict) and item.get("ok") for item in results.values()):
            deps.tdc_export_cache.clear()
        if bool(payload.get("saveForScheduled")) and any(
            isinstance(item, dict) and item.get("ok") for item in results.values()
        ):
            # 先写 Windows 凭据管理器（失败更常见），再写 DPAPI 凭据库；
            # 任一步失败都不得出现「一侧已落盘」的半保存状态。
            try:
                store_windows_generic_credential(SYNC_CREDENTIAL_REF, username.strip(), password)
            except CredentialProviderError as exc:
                return deps.json_error(
                    503,
                    "CredentialVaultUnavailable",
                    f"登录会话已建立，但同步凭据保存失败：{deps.sanitize_error_message(exc)}",
                )
            try:
                deps.credential_vault.store(username.strip(), password)
            except CredentialVaultError as exc:
                # DPAPI 落库失败：回滚 Windows 凭据，保持两侧一致。
                try:
                    delete_windows_generic_credential(SYNC_CREDENTIAL_REF)
                except CredentialProviderError:
                    pass
                return deps.json_error(
                    503,
                    "CredentialVaultUnavailable",
                    f"登录会话已建立，但定时下载凭据保存失败：{deps.sanitize_error_message(exc)}",
                )
            # 凭据变更等价于清除（契约 §7.2-3）：在途续期结果作废。
            _bump_vault_epoch(deps)
        response = jsonify(
            {
                "ok": any(isinstance(item, dict) and item.get("ok") for item in results.values()),
                "data": {"results": results, "sessions": deps.domain_sessions.payload()},
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, (200 if response.get_json()["ok"] else 401)

    @app.delete("/api/settings/sessions")
    def api_domain_sessions_clear():
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True) or {}
        system = payload.get("system") if isinstance(payload, dict) else None
        if system not in (None, "aras", "tdc"):
            return deps.validation_error({"system": "仅支持 aras 或 tdc"})
        # 经协调器清除：代次 +1 → 取消在途续期 → 移除会话（契约 §7.2-1）。
        _clear_domain_sessions(deps, system)
        if system in (None, "tdc"):
            deps.tdc_export_cache.clear()
        if isinstance(payload, dict) and payload.get("clearCredentialVault"):
            # 先删 Windows 凭据，再清 DPAPI 凭据库；Windows 删除失败时 DPAPI
            # 保持原状，避免出现 Windows 侧孤儿凭据。
            try:
                delete_windows_generic_credential(SYNC_CREDENTIAL_REF)
            except CredentialProviderError as exc:
                return deps.json_error(503, "CredentialVaultUnavailable", deps.sanitize_error_message(exc))
            try:
                deps.credential_vault.clear()
            except CredentialVaultError as exc:
                return deps.json_error(503, "CredentialVaultUnavailable", deps.sanitize_error_message(exc))
            _bump_vault_epoch(deps)
        # 增量键（既有 ok/data.sessions 与 200 不变）：逐系统清除结果带 §4.3 闭集码。
        cleared = ("aras", "tdc") if system is None else (system,)
        results = {name: {"ok": True, "code": "session_cleared"} for name in cleared}
        response = jsonify(
            {
                "ok": True,
                "data": {"sessions": deps.domain_sessions.payload(), "results": results},
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response


def register_host_update_routes(
    app: Any,
    *,
    updates: Any,
    registry: Any,
    updates_payload: Callable[[], dict[str, Any]],
    deps: HostRouteDeps,
) -> None:
    """宿主更新路由（原 _install_plugin_host 内联实现，逐字迁移）。

    updates / registry / updates_payload 仍由插件宿主装配（_install_plugin_host）
    构建——迁移的是路由实现，不是装配关系。
    """

    @app.post("/api/host/updates/import")
    def api_host_updates_import():
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return deps.json_error(400, "ValidationError", "请选择 .vsepkg 插件包")
        data = upload.read()
        try:
            from host.updates import verify_package

            package = verify_package(data, updates.trusted_keys)
            record = registry.record_for(package.id)
            current = record.manifest.version if record and record.manifest and record.status == "loaded" else None
            updates.stage(data, current_version=current)
        except PackageError as exc:
            return deps.json_error(422, "PackageRejected", str(exc))
        except OSError as exc:
            logger.exception("staging plugin package failed")
            return deps.json_error(500, "ServerError", deps.sanitize_error_message(exc))
        return deps.json_ok({
            "id": package.id,
            "version": package.version,
            "previous": current,
            "message": "插件包已校验通过，重启 VSE Toolbox 后生效",
            "updates": updates_payload(),
        })

    @app.post("/api/host/updates/<plugin_id>/discard")
    def api_host_updates_discard(plugin_id: str):
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        if not updates.discard_pending(plugin_id):
            return deps.json_error(404, "NotFound", "没有待生效的插件包")
        return deps.json_ok(updates_payload())

    @app.post("/api/host/updates/<plugin_id>/rollback")
    def api_host_updates_rollback(plugin_id: str):
        local_error = deps.local_mutation_error()
        if local_error is not None:
            return local_error
        if plugin_id not in updates.read_state()["plugins"]:
            return deps.json_error(404, "NotFound", "该插件没有通过插件包安装的版本")
        previous = updates.rollback(plugin_id, reason="用户手动回滚")
        data = updates_payload()
        data["message"] = f"已切回 {previous or '随包内置版本'}，重启后生效"
        return deps.json_ok(data)
