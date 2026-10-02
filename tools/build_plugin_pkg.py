# -*- coding: utf-8 -*-
"""Build a signed plugin package (.vsepkg) for distribution via Feishu.

Usage::

    python tools/build_plugin_pkg.py plugins/deliverable_forms --key D:\\vse-signing\\plugin-signing.pem

输出 ``dist/plugins/<id>-<version>.vsepkg``。同事在“设置 → 插件更新”导入，重启后生效。
发包前记得把 plugin.json 的 version 调高，宿主拒绝不高于当前版本的包。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from host.updates import PackageError, build_package  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建签名插件包 .vsepkg")
    parser.add_argument("plugin_dir", type=Path, help="插件目录，例如 plugins/deliverable_forms")
    parser.add_argument("--key", type=Path, required=True, help="Ed25519 私钥 PEM（tools/plugin_keys.py init 生成）")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "dist" / "plugins", help="输出目录")
    args = parser.parse_args(argv)
    try:
        name, data = build_package(args.plugin_dir, args.key.read_bytes())
    except (PackageError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / name
    target.write_bytes(data)
    print(f"created {target} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
