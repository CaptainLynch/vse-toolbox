# -*- coding: utf-8 -*-
"""为部署目录生成/校验 `MANIFEST.json`（第 0 期部署自检的构建侧）。

用法::

    python tools/build_deploy_manifest.py --root dist/VSE-WebUI --version 2.4.3
    python tools/build_deploy_manifest.py --root dist/VSE-WebUI --check

口径（docs/PLAN_20261111_SIGNDAILY_ENCRYPTED.md §2.4）：

- 清单只收录**部署后由 Python 直接读取**的文件（`plugins/`、`web/static/`、
  `web/templates/`、`core/report_headers.json`、`host/trusted_keys.json`），
  不含 exe/运行时 DLL。
- 清单是确定性的（无时间戳）：同一内容两次生成逐字节一致，便于复核 diff。
- `--check` 以**当前进程视图**校验：哈希不符再嗅探容器头，区分「被改动」与
  「被终端容器化」。退出码 0=通过，1=不通过，2=用法错误。

禁止：本工具不解密、不剥容器头、不修复文件；发现问题只报告。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.deploy_manifest import (  # noqa: E402
    build_manifest,
    deploy_root,
    verify_manifest,
    write_manifest,
)
from core.version import get_app_version_info  # noqa: E402


def _default_version() -> str:
    info = get_app_version_info()
    raw = info.get("rawVersion")
    if raw:
        return str(raw)
    return "0.0.0-dev"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_deploy_manifest",
        description="为部署目录生成或校验 MANIFEST.json（部署自检）",
    )
    parser.add_argument("--root", default=None, help="部署根目录（默认：源码仓库根 / 冻结包 exe 目录）")
    parser.add_argument("--version", default="", help="写进清单的版本号（默认取运行时版本信息）")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser() if args.root else deploy_root()
    if not root.is_dir():
        print(f"部署根目录不存在：{root}", file=sys.stderr)
        return 2

    if args.check:
        check = verify_manifest(root)
        print(f"status={check.status} ok={check.ok} checked={check.checked}")
        print(check.message)
        for label, items in (
            ("容器化", check.containerized),
            ("被改动", check.mismatched),
            ("缺失", check.missing),
            ("未入清单的插件源文件", check.extra_plugins),
        ):
            for item in items[:20]:
                print(f"  {label}: {item}")
            if len(items) > 20:
                print(f"  {label}: 另有 {len(items) - 20} 项未列出")
        return 0 if check.ok else 1

    version = args.version.strip() or _default_version()
    target = write_manifest(root, version=version)
    payload = build_manifest(root, version=version)
    print(f"已写出：{target}")
    print(f"version={version} files={payload['fileCount']}")
    check = verify_manifest(root)
    print(f"自检：status={check.status} ok={check.ok} {check.message}")
    return 0 if check.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
