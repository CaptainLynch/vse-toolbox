# -*- coding: utf-8 -*-
"""Build a v2 test install in dist/v2-test/ (development and acceptance testing only).

    python tools/build_v2_test_install.py [--skip-exe]

Produces:
    dist/v2-test/keys/                 a TEST-ONLY signing key (never use for real releases)
    dist/v2-test/VSE-Toolbox/          launcher + runtime, with vse-app-2.0.0.vsepkg next to the exe
    dist/v2-test/updates/              vse-app-2.0.1.vsepkg (good) and vse-app-2.0.2.vsepkg (fails at start)
    dist/v2-test/测试步骤.txt
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import release  # noqa: E402

from vse_boot.packages import build_app_package, key_id_for  # noqa: E402

OUT = REPO / "dist" / "v2-test"

STEPS = """VSE Toolbox v2 测试安装（仅供测试；签名密钥是测试专用的）
================================================================

1. 首次安装
   双击 VSE-Toolbox\\VSE-Toolbox.exe
   → 自动安装旁边的 vse-app-2.0.0.vsepkg，打开 Edge 应用窗口（没有地址栏）
   → 再双击一次 exe：不会启动第二份，只会把已有窗口再打开一次

2. 正常更新
   把 updates\\vse-app-2.0.1.vsepkg 拖到 VSE-Toolbox\\安装更新包.cmd 上（或在命令行运行
   VSE-Toolbox.exe stage ..\\updates\\vse-app-2.0.1.vsepkg）
   → 关闭程序（结束 VSE-Toolbox.exe 进程）后重新双击 exe → 版本变成 2.0.1

3. 坏更新自动回滚
   同样安装 updates\\vse-app-2.0.2.vsepkg（这个版本故意启动失败）
   → 重新启动：先试 2.0.2，失败后自动回到 2.0.1，窗口照常打开

4. 查看状态 / 手动回滚
   VSE-Toolbox\\查看状态.cmd     当前版本、上一版本、安装与回滚记录
   VSE-Toolbox.exe rollback      下次启动回到上一版本

日志：VSE-Toolbox\\state\\launcher.log、state\\app-last-run.log
数据：VSE-Toolbox\\data\\（与程序版本无关，升级和回滚都不会动它）
"""

STAGE_CMD = '@echo off\r\nchcp 65001 >nul\r\n"%~dp0VSE-Toolbox.exe" stage "%~1"\r\npause\r\n'
STATUS_CMD = '@echo off\r\nchcp 65001 >nul\r\n"%~dp0VSE-Toolbox.exe" status\r\npause\r\n'


def ensure_test_key(keys_dir: Path) -> tuple[bytes, Path]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    keys_dir.mkdir(parents=True, exist_ok=True)
    pem_path = keys_dir / "TEST-ONLY-signing.pem"
    if not pem_path.exists():
        private = Ed25519PrivateKey.generate()
        pem_path.write_bytes(
            private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        )
    private = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    trusted = keys_dir / "trusted_keys.json"
    trusted.write_text(
        json.dumps({"keys": [{"keyId": key_id_for(public), "publicKey": base64.b64encode(public).decode(), "label": "TEST ONLY"}]}, indent=2),
        encoding="utf-8",
    )
    return pem_path.read_bytes(), trusted


def build_exe(trusted: Path) -> Path:
    env = dict(os.environ, VSE_TRUSTED_KEYS_FILE=str(trusted))
    build = OUT / "build"
    log = OUT / "pyinstaller.log"
    with open(log, "wb") as handle:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(build / "dist"),
             "--workpath", str(build / "work"), str(REPO / "VSE-Launcher.spec")],
            cwd=REPO, env=env, stdout=handle, stderr=subprocess.STDOUT,
        )
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller 失败，见 {log}")
    return build / "dist" / "VSE-Toolbox"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-exe", action="store_true", help="只重建更新包，不重新打 exe")
    args = parser.parse_args(argv)
    pem, trusted = ensure_test_key(OUT / "keys")
    install = OUT / "VSE-Toolbox"
    updates = OUT / "updates"
    if not args.skip_exe:
        built = build_exe(trusted)
        shutil.rmtree(install, ignore_errors=True)
        shutil.copytree(built, install, dirs_exist_ok=True)
    install.mkdir(parents=True, exist_ok=True)
    updates.mkdir(parents=True, exist_ok=True)

    release.build_app(version="2.0.0", key_pem=pem, notes="首个 v2 版本", out_dir=install)
    release.build_app(version="2.0.1", key_pem=pem, notes="正常更新：演示用", out_dir=updates)
    broken = release.collect_app_files()
    broken["webui.py"] = b"raise RuntimeError('demo: this build fails at start')\n"
    name, data = build_app_package(broken, version="2.0.2", private_key_pem=pem, notes="故意启动失败，用来演示自动回滚")
    (updates / name).write_bytes(data)

    # 测试安装用便携模式：数据留在测试目录里，不碰本机 %LOCALAPPDATA%\VSE-Toolbox。
    (install / "portable.flag").write_text("test install", encoding="utf-8")
    (install / "安装更新包.cmd").write_bytes(STAGE_CMD.encode("utf-8"))
    (install / "查看状态.cmd").write_bytes(STATUS_CMD.encode("utf-8"))
    (OUT / "测试步骤.txt").write_text(STEPS, encoding="utf-8-sig")
    print(f"测试安装已生成：{install}")
    for path in sorted([*install.glob("*.vsepkg"), *updates.glob("*.vsepkg")]):
        print(f"  {path.relative_to(OUT)}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
