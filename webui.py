# -*- coding: utf-8 -*-
"""VSE Toolbox WebUI 启动入口（源码运行与 PyInstaller 冻结共用）。

用法:
    python webui.py                     # 127.0.0.1:5000
    python webui.py --host 0.0.0.0      # 允许局域网访问（写操作仅限本机回环）
    python webui.py --port 8000

冻结构建: pyinstaller --noconfirm webui.spec
"""

from __future__ import annotations

import argparse


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
    parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # 延迟导入：--help 无需加载应用；冻结后模块由打包器收集。
    from core.runtime_paths import app_root
    from web.app import create_app

    app = create_app()
    print(f"VSE Toolbox WebUI: http://{args.host}:{args.port}/  (Ctrl+C 退出)")
    print(f"数据目录: {app_root() / 'data'}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
