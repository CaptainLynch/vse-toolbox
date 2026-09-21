# -*- coding: utf-8 -*-
"""VSE Toolbox WebUI 启动入口（源码运行与 PyInstaller 冻结共用）。

用法:
    python webui.py                     # 127.0.0.1:5000，服务就绪后自动打开浏览器
    python webui.py --no-browser        # 不自动打开浏览器（无头测试/计划任务）
    python webui.py --host 0.0.0.0      # 允许局域网访问（写操作仅限本机回环）
    python webui.py --port 8000

冻结构建: pyinstaller --noconfirm webui.spec
"""

from __future__ import annotations

import argparse
import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser

#: 就绪探测的最长等待（秒）：超时说明服务未能监听，放弃唤起浏览器。
_READINESS_PROBE_TIMEOUT_SECONDS = 30.0
#: 单次探测间隔（秒）。
_READINESS_PROBE_INTERVAL_SECONDS = 0.25


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webui",
        description="VSE Toolbox WebUI（本地 Web 控制台；写操作仅接受本机回环地址）",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址，默认 127.0.0.1（0.0.0.0 允许局域网访问，写接口仍仅限本机）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口；缺省读取环境变量 VSE_TOOLBOX_PORT，再缺省 5000",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="服务启动后不自动打开浏览器（用于无头测试与后台计划任务）",
    )
    parser.add_argument("--diagnostics", action="store_true", help="开启30分钟安全诊断录制（不启用Flask调试器）")
    parser.add_argument(
        "--no-sync-scheduler",
        action="store_true",
        help="不启动项目状态常驻同步调度线程（默认启动；定时同步由交付物绑定的新鲜度门控节流）",
    )
    return parser


def _start_sync_scheduler() -> None:
    """以 daemon 线程启动项目状态同步调度器（仿 webui-browser-probe 模式）。

    仅 WebUI 入口调用；CLI（main.py）与 pytest 不启动。调度器内部的
    单绑定异常均已隔离记录，线程顶层兜底同样只记录不外抛。
    """
    from core.db_manager import DatabaseManager
    from services.project_status_scheduler import ProjectStatusSyncScheduler
    from services.project_status_sync_runner import (
        ProjectStatusSyncRunner,
        create_production_registry,
    )
    from services.project_status_updates import ProjectStatusUpdateService

    try:
        db = DatabaseManager()
        db.init_database()
        service = ProjectStatusUpdateService(db)
        runner = ProjectStatusSyncRunner(db, service, create_production_registry())
        scheduler = ProjectStatusSyncScheduler(db, runner)
    except Exception:
        print("项目状态同步调度器启动失败，将在下次启动 WebUI 时重试。")
        return
    threading.Thread(
        target=_run_sync_scheduler_safely,
        args=(scheduler,),
        name="project-status-sync-scheduler",
        daemon=True,
    ).start()


def _run_sync_scheduler_safely(scheduler) -> None:
    """线程顶层兜底：调度循环的未预期异常只记录，不影响 Flask 主进程。"""
    try:
        scheduler.run_forever()
    except Exception:
        print("项目状态同步调度线程已退出（见运行日志）。")


def _open_browser_when_ready(url: str, timeout: float = _READINESS_PROBE_TIMEOUT_SECONDS) -> None:
    """readiness probe：仅在 HTTP 服务真正监听就绪后唤起默认浏览器。

    探测 /api/version（只读、无副作用）；连接被拒说明尚未监听，继续等待，
    超时则放弃（不重试、不报错退出——浏览器唤起是尽力而为的体验增强）。
    """
    probe_url = f"{url.rstrip('/')}/api/version"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe_url, timeout=1.5) as response:
                if 200 <= response.status < 500:
                    # 服务已响应（即使返回错误码也说明端口已监听）
                    webbrowser.open_new_tab(url)
                    return
        except urllib.error.HTTPError:
            # HTTP 错误同样证明服务已监听
            webbrowser.open_new_tab(url)
            return
        except OSError:
            pass
        time.sleep(_READINESS_PROBE_INTERVAL_SECONDS)


def _resolve_port(raw_port: int | None) -> int:
    """端口解析优先级：--port 参数 > VSE_TOOLBOX_PORT 环境变量 > 默认 5000。"""
    if raw_port is not None:
        selected = raw_port
    else:
        raw_env = os.environ.get("VSE_TOOLBOX_PORT", "").strip()
        try:
            selected = int(raw_env) if raw_env else 5000
        except ValueError:
            selected = 5000
    if not 1 <= selected <= 65535:
        return 5000
    return selected


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    port = _resolve_port(args.port)
    # 延迟导入：--help 无需加载应用；冻结后模块由打包器收集。
    from core.runtime_paths import app_root
    from web.app import create_app

    app = create_app()
    if args.diagnostics:
        try:
            app.extensions["diagnostic_recorder"].start()
        except Exception:
            print("诊断录制未能开启，请在页面诊断控件中检查状态。")
    url = f"http://{args.host}:{port}/"
    print(f"VSE Toolbox WebUI: {url}  (Ctrl+C 退出)")
    print(f"数据目录: {app_root() / 'data'}")
    if not args.no_sync_scheduler:
        # 项目状态常驻同步调度（C）：在 Flask 启动前以 daemon 线程拉起；
        # 新鲜绑定按 last_success_at 零网络跳过，陈旧绑定补偿同步。
        _start_sync_scheduler()
    if not args.no_browser:
        # 仅回环地址自动唤起浏览器；0.0.0.0 等对外监听不代开远端浏览器
        browser_host = args.host in ("127.0.0.1", "localhost")
        if browser_host:
            threading.Thread(
                target=_open_browser_when_ready,
                args=(url,),
                name="webui-browser-probe",
                daemon=True,
            ).start()
        else:
            print("非回环监听地址：跳过自动打开浏览器。")
    app.run(host=args.host, port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
