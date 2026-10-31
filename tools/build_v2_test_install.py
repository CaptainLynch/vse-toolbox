# -*- coding: utf-8 -*-
"""Build a v2 test install in dist/v2-test/ (development and acceptance testing only).

    python tools/build_v2_test_install.py [--skip-exe] [--out DIR]

The output root defaults to dist/v2-test/ and can be overridden with ``--out DIR``
or the ``VSE_TEST_INSTALL_ROOT`` environment variable (the argument wins). A
relative root is resolved against the current working directory.

Produces (under the output root):
    <out>/keys/                 a TEST-ONLY signing key (never use for real releases)
    <out>/VSE-Toolbox/          launcher + runtime, with vse-app-2.3.0.vsepkg next to the exe
    <out>/updates/              vse-app-2.3.1.vsepkg (good) and vse-app-2.3.2.vsepkg (fails at start)
    <out>/测试步骤.txt
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
OUT_ENV = "VSE_TEST_INSTALL_ROOT"


class StalePackageError(Exception):
    """旧包清理失败：保留现场，由 main() 报告路径、错误类型和下一步后非零退出。"""

    def __init__(self, path: Path, error: OSError) -> None:
        super().__init__(f"{path}: {type(error).__name__}: {error}")
        self.path = path
        self.error = error


def resolve_out_root(value: str | None = None) -> Path:
    """解析输出根：``--out`` 优先，其次 ``VSE_TEST_INSTALL_ROOT``，默认 ``dist/v2-test``。

    默认值保持与历史行为一致（仓库内 ``dist/v2-test``）；显式给出的相对路径
    按当前工作目录解析，这样测试可以把输出完全指到临时目录。
    """
    raw = value if value is not None else os.environ.get(OUT_ENV, "")
    raw = (raw or "").strip()
    if not raw:
        return OUT
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def remove_stale_packages(*directories: Path) -> list[Path]:
    """删除上次构建留下的 ``*.vsepkg``，只保留本次构建的包。

    任何 OSError（例如 Windows 上文件被占用时的 PermissionError/WinError 5）都
    包装成 StalePackageError 向上抛，不静默跳过：旧包原样保留，调用方据此
    打印路径、错误类型和下一步并以非零码退出。不修改 ACL、不结束进程。
    """
    removed: list[Path] = []
    for directory in directories:
        for old in sorted(directory.glob("*.vsepkg")):
            try:
                old.unlink()
            except OSError as exc:
                raise StalePackageError(old, exc) from exc
            removed.append(old)
    return removed


def report_stale_package_error(exc: StalePackageError, out_root: Path) -> int:
    """打印旧包清理失败的诊断信息并返回非零退出码（不吞掉任何 OSError）。"""
    print("错误：无法删除旧更新包，本次构建已停止（旧包保留在原处）。", file=sys.stderr)
    print(f"  文件：{exc.path}", file=sys.stderr)
    print(f"  错误类型：{type(exc.error).__name__}：{exc.error}", file=sys.stderr)
    print(f"  输出根：{out_root}", file=sys.stderr)
    print("  下一步：关闭可能占用该文件的程序（正在运行的 VSE-Toolbox、资源管理器预览、", file=sys.stderr)
    print("          杀毒扫描等），确认文件可删除后重试；或用 --out 指定新的输出根。", file=sys.stderr)
    return 2


STEPS = r"""VSE Toolbox v2 测试安装（仅供测试；签名密钥是测试专用的）
================================================================

0. 已经装过 2.0.x / 2.1.x / 2.2.x 测试版？
   双击 updatesse-app-2.3.0.vsepkg → 提示"校验通过，现在重启吗" → 是 → 约 10 秒后变成新界面
   （或者：工具 → 程序与插件更新 → 从文件安装）
   注意：「多项目切换」需要新的启动器——请用这次的整个 VSE-Toolbox 文件夹替换旧的（data 文件夹保留即可）；
   只装更新包也能用其他新功能，只是项目切换器不会出现。

1. 首次安装
   双击 VSE-Toolbox\VSE-Toolbox.exe
   → 自动安装旁边的 vse-app-2.3.0.vsepkg，打开 Edge 应用窗口（没有地址栏）
   → 右下角出现 V 字托盘图标；关掉窗口程序仍在后台，点托盘图标重新打开
   → 再双击一次 exe：不会启动第二份，只会把窗口再打开一次

2. 在程序里更新（推荐的日常方式）
   把 updates\vse-app-2.3.1.vsepkg 复制到「下载」文件夹（模拟飞书下载）
   → 程序里打开「工具 → 程序与插件更新」，顶部「程序更新」会显示"发现新版本 2.3.1"
   → 点「安装并重启」，约 10 秒后页面自动刷新，版本变成 2.3.1

3. 双击更新包安装
   第一次运行 exe 后，.vsepkg 已关联到本程序（只写当前用户的注册表，不需要管理员）
   → 双击 updates\vse-app-2.3.2.vsepkg → 提示"校验通过，现在重启吗" → 是
   → 2.3.2 故意启动失败，程序自动回到 2.3.1，托盘弹出提示，窗口照常可用

4. 回滚与记录
   「程序更新」卡片里可以「回到上一版本」，下面列着安装/生效/回滚记录
   托盘菜单：打开 / 检查更新 / 重新启动 / 退出（退出后不再自动同步）

5. 多项目
   「今天」或「项目」页右上角「项目 ▾」→「＋ 新建项目」→ 填车型、勾科室 → 新建并切换过去
   → 约 10 秒后自动刷新，进入新项目（交付物、主计划、同步记录各项目分开；公司账号共用）
   → 「项目」页「⚡ 一键开启自动同步」：确认车型和科室 → 全部开启（需要先登录并保存密码）

日志：VSE-Toolbox\state\launcher.log、state\app-last-run.log
数据：VSE-Toolbox\data\（与程序版本无关，升级和回滚都不会动它）
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


def build_exe(trusted: Path, out_root: Path) -> Path:
    env = dict(os.environ, VSE_TRUSTED_KEYS_FILE=str(trusted))
    build = out_root / "build"
    log = out_root / "pyinstaller.log"
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
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help=f"输出根目录（默认 {OUT}，也可用环境变量 {OUT_ENV} 指定；命令行优先）",
    )
    args = parser.parse_args(argv)
    out_root = resolve_out_root(args.out)
    install = out_root / "VSE-Toolbox"
    updates = out_root / "updates"
    install.mkdir(parents=True, exist_ok=True)
    updates.mkdir(parents=True, exist_ok=True)
    try:
        # 只保留本次构建的包，避免新旧版本混在一起；失败时保留旧包并非零退出。
        remove_stale_packages(install, updates)
    except StalePackageError as exc:
        return report_stale_package_error(exc, out_root)

    pem, trusted = ensure_test_key(out_root / "keys")
    if not args.skip_exe:
        built = build_exe(trusted, out_root)
        shutil.rmtree(install, ignore_errors=True)
        shutil.copytree(built, install, dirs_exist_ok=True)

    first = release.build_app(version="2.3.0", key_pem=pem, notes="多项目切换、一键开启自动同步、交付物详情简洁视图、取消「子系统开发策略」", out_dir=install)
    # 已经装过 2.0.x 测试版的电脑：直接用这个包升级到新界面。
    shutil.copy2(first, updates / first.name)
    release.build_app(version="2.3.1", key_pem=pem, notes="正常更新：演示用", out_dir=updates)
    broken = release.collect_app_files()
    broken["webui.py"] = b"raise RuntimeError('demo: this build fails at start')\n"
    name, data = build_app_package(broken, version="2.3.2", private_key_pem=pem, notes="故意启动失败，用来演示自动回滚")
    (updates / name).write_bytes(data)

    # 测试安装用便携模式：数据留在测试目录里，不碰本机 %LOCALAPPDATA%\VSE-Toolbox。
    (install / "portable.flag").write_text("test install", encoding="utf-8")
    (install / "安装更新包.cmd").write_bytes(STAGE_CMD.encode("utf-8"))
    (install / "查看状态.cmd").write_bytes(STATUS_CMD.encode("utf-8"))
    (out_root / "测试步骤.txt").write_text(STEPS, encoding="utf-8-sig")
    print(f"测试安装已生成：{install}")
    for path in sorted([*install.glob("*.vsepkg"), *updates.glob("*.vsepkg")]):
        print(f"  {path.relative_to(out_root)}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
