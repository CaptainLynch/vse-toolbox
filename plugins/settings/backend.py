# -*- coding: utf-8 -*-
"""Settings plugin backend.

页面直接调用宿主已有的 /api/settings、/api/settings/folders/native、
/api/settings/domain-login、/api/settings/sessions 与 /api/version，
这些接口（含本机写保护、凭据与会话处理）保留在 web/app.py，不在插件内复制。

插件自有路由：
1.「程序更新」（v2 启动器下的 app 版本）：
GET  app-updates            当前/上一/试用版本、待生效版本、下载文件夹里发现的新版本、记录
POST app-updates/install    {file}：安装一个已发现的更新包（只接受发现列表里的文件）
POST app-updates/upload     multipart：安装上传的更新包
POST app-updates/restart    请启动器重启程序，让待生效版本生效
POST app-updates/rollback   下次启动回到上一版本，并立即重启
不由 v2 启动器运行时（源码直接运行），GET 返回 managed=false，其余返回 409。

2.「开机自启」（HKCU Run 项）：
GET  autostart              获取当前用户开机自启状态（enabled: bool）
POST autostart              修改当前用户开机自启（{enabled: bool}）
"""

from __future__ import annotations

from typing import Any

from flask import request

_MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def _api():  # type: ignore[no-untyped-def]
    """vse_boot belongs to the runtime layer; it is absent in old frozen builds."""
    try:
        from vse_boot import api
    except ImportError:
        return None
    return api


def register(host):
    ctx = host.context
    bp = host.blueprint

    def managed():  # type: ignore[no-untyped-def]
        api = _api()
        layout = api.managed_layout() if api else None
        return api, layout

    def candidates_payload(api, layout) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        return [
            {"file": c.path.name, "folder": str(c.path.parent), "version": c.version, "notes": c.notes, "sizeKb": round(c.size / 1024)}
            for c in api.available_updates(layout)
        ]

    def mutation(handler):  # type: ignore[no-untyped-def]
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            guard = ctx.local_guard()
            if guard is not None:
                return guard
            api, layout = managed()
            if layout is None:
                return ctx.json_error(409, "NotManaged", "当前不是通过 VSE Toolbox 启动器运行，无法在这里安装程序更新")
            from vse_boot.packages import PackageError

            try:
                return handler(api, layout, *args, **kwargs)
            except PackageError as exc:
                return ctx.json_error(400, "PackageRejected", str(exc))
            except OSError as exc:
                return ctx.json_error(500, "IOError", f"读写更新包失败：{exc.strerror or exc}")
        wrapper.__name__ = handler.__name__
        return wrapper

    @bp.get("/app-updates")
    def app_updates():  # type: ignore[no-untyped-def]
        api, layout = managed()
        if layout is None:
            return ctx.json_ok({"managed": False})
        payload = api.status(layout)
        payload["managed"] = True
        payload["available"] = candidates_payload(api, layout)
        payload["watchDirs"] = [str(p) for p in api.watch_dirs(layout)]
        return ctx.json_ok(payload)

    @bp.post("/app-updates/install")
    @mutation
    def app_updates_install(api, layout):  # type: ignore[no-untyped-def]
        body = request.get_json(silent=True) or {}
        name = str(body.get("file") or "")
        # 只接受发现列表里的文件：页面不能借此读取任意路径。
        match = next((c for c in api.available_updates(layout) if c.path.name == name), None)
        if match is None:
            return ctx.json_error(404, "NotFound", "没有找到这个更新包，请刷新后再试")
        version = api.stage_file(layout, match.path)
        return ctx.json_ok({"version": version, "message": f"{version} 已校验，重启后生效"})

    @bp.post("/app-updates/upload")
    @mutation
    def app_updates_upload(api, layout):  # type: ignore[no-untyped-def]
        upload = request.files.get("file")
        if upload is None:
            return ctx.json_error(400, "ValidationError", "请选择 .vsepkg 更新包")
        data = upload.read(_MAX_UPLOAD_BYTES + 1)
        if len(data) > _MAX_UPLOAD_BYTES:
            return ctx.json_error(400, "ValidationError", "更新包过大")
        version = api.stage_bytes(layout, data)
        return ctx.json_ok({"version": version, "message": f"{version} 已校验，重启后生效"})

    @bp.post("/app-updates/restart")
    @mutation
    def app_updates_restart(api, layout):  # type: ignore[no-untyped-def]
        api.request_restart(layout)
        return ctx.json_ok({"message": "正在重新启动，大约 10 秒后自动刷新"})

    @bp.post("/app-updates/rollback")
    @mutation
    def app_updates_rollback(api, layout):  # type: ignore[no-untyped-def]
        from vse_boot.state import BootState, BootStateError

        try:
            version = BootState(layout).rollback()
        except BootStateError as exc:
            return ctx.json_error(409, "NoPrevious", str(exc))
        api.request_restart(layout)
        return ctx.json_ok({"version": version, "message": f"正在回到 {version} 并重新启动"})

    def _autostart_mod():  # type: ignore[no-untyped-def]
        try:
            from vse_boot import autostart

            return autostart
        except ImportError:
            return None

    @bp.get("/autostart")
    def autostart_status():  # type: ignore[no-untyped-def]
        mod = _autostart_mod()
        if mod is None:
            return ctx.json_ok({"enabled": False, "available": False})
        return ctx.json_ok({"enabled": mod.enabled(), "available": True})

    @bp.post("/autostart")
    def autostart_toggle():  # type: ignore[no-untyped-def]
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        mod = _autostart_mod()
        if mod is None:
            return ctx.json_error(501, "NotSupported", "当前运行环境不支持开机自启设置")
        body = request.get_json(silent=True) or {}
        should_enable = bool(body.get("enabled"))
        try:
            if should_enable:
                mod.enable()
            else:
                mod.disable()
        except OSError as exc:
            return ctx.json_error(500, "RegistryError", f"修改开机启动项失败：{exc}")
        return ctx.json_ok({"enabled": mod.enabled()})

    return None

