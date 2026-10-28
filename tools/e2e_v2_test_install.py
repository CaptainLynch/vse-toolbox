# -*- coding: utf-8 -*-
"""End-to-end check of dist/v2-test (run tools/build_v2_test_install.py first).

    python tools/e2e_v2_test_install.py

Drives the real VSE-Toolbox.exe and the real app, without opening a window
(VSE_BOOT_NO_WINDOW=1): first install → second instance → update 2.0.1 →
broken 2.0.2 rolls back → killing the launcher leaves no orphan → manual rollback.
Wipes app/, state/ and data/ of the test install first.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "dist" / "v2-test"
INSTALL = OUT / "VSE-Toolbox"
EXE = INSTALL / "VSE-Toolbox.exe"
ENV = dict(os.environ, VSE_BOOT_NO_WINDOW="1")
ENV.pop("VSE_INSTALL_ROOT", None)
ENV.pop("VSE_DATA_ROOT", None)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def cli(*args: str) -> str:
    done = subprocess.run([str(EXE), *args], env=ENV, capture_output=True, timeout=60)
    return (done.stdout or b"").decode("utf-8", "replace")


def status() -> dict:
    return json.loads((INSTALL / "state" / "boot.json").read_text(encoding="utf-8"))


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def start(timeout: float = 120.0) -> tuple[subprocess.Popen, dict]:
    instance = INSTALL / "state" / "instance.json"
    instance.unlink(missing_ok=True)
    proc = subprocess.Popen([str(EXE)], env=ENV)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"launcher exited with {proc.returncode}")
        if instance.is_file():
            try:
                return proc, json.loads(instance.read_text(encoding="utf-8"))
            except ValueError:
                pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("launcher did not become ready")


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_version(info: dict, version: str, timeout: float = 120.0) -> dict:
    """After an in-app restart: same port, new version (instance.json is rewritten)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = json.loads((INSTALL / "state" / "instance.json").read_text(encoding="utf-8"))
            if current.get("version") == version and version in served_version(current):
                return current
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError(f"did not restart into {version}")


def served_version(info: dict) -> str:
    payload = get(info["url"] + "api/version")
    data = payload.get("data", payload)
    return str(data.get("version") or data.get("appVersion") or data)


def stop(proc: subprocess.Popen, info: dict) -> None:
    proc.kill()  # 模拟在任务管理器里结束 VSE-Toolbox.exe
    proc.wait(timeout=10)
    time.sleep(2)
    check("结束启动器后 app 子进程同时退出（无孤儿进程）", not pid_alive(int(info["pid"])), f"child pid {info['pid']}")


def main() -> int:
    if not EXE.is_file():
        print("先运行 python tools/build_v2_test_install.py")
        return 2
    for name in ("app", "state", "data"):
        shutil.rmtree(INSTALL / name, ignore_errors=True)

    # 1. 首次安装
    proc, info = start()
    version = served_version(info)
    check("首次安装并启动 2.0.0", "2.0.0" in version, version)
    home = urllib.request.urlopen(info["url"], timeout=10).status
    check("首页可访问", home == 200)
    check("数据目录在安装根下", (INSTALL / "data" / "vse_toolbox.db").is_file())

    # 2. 第二次启动：不再起第二份
    second = subprocess.run([str(EXE)], env=ENV, timeout=30)
    check("第二次启动直接返回（单实例）", second.returncode == 0 and len(list((INSTALL / "app").iterdir())) == 1)

    # 3. 在设置页里发现并安装 2.0.1，一键重启生效（不关程序）
    received = INSTALL / "vse-app-2.0.1.vsepkg"  # 模拟"收到的更新包放在了被监视的文件夹里"
    shutil.copy2(OUT / "updates" / "vse-app-2.0.1.vsepkg", received)
    page = get(info["url"] + "api/p/settings/app-updates")["data"]
    check("设置页显示受启动器管理、当前 2.0.0", page.get("managed") is True and page.get("current") == "2.0.0")
    check("设置页发现新版本 2.0.1（签名有效）", [a["version"] for a in page.get("available", [])] == ["2.0.1"])
    post(info["url"] + "api/p/settings/app-updates/install", {"file": received.name})
    post(info["url"] + "api/p/settings/app-updates/restart")
    restarted = wait_for_version(info, "2.0.1")
    state = status()["app"]
    check("页面内安装并重启后变成 2.0.1，端口不变", restarted["port"] == info["port"] and state["current"] == "2.0.1" and state["previous"] == "2.0.0")
    received.unlink()
    info = restarted

    # 3b. 用命令（托盘「退出」走同一条路）正常退出
    old_child = int(info["pid"])
    cli("quit")
    try:
        code = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    time.sleep(1)
    check("退出请求：启动器与 app 都正常退出", code == 0 and not pid_alive(old_child), f"exit={code}")

    # 4. 坏更新 2.0.2：自动回滚
    print(cli("stage", str(OUT / "updates" / "vse-app-2.0.2.vsepkg")).strip())
    proc, info = start(timeout=180)
    version = served_version(info)
    boot = status()
    kinds = [e["kind"] for e in boot["events"][:3]]
    check("坏版本 2.0.2 自动回滚到 2.0.1", "2.0.1" in version and boot["app"]["current"] == "2.0.1" and "rolledBack" in kinds, f"{version} {kinds}")
    check("坏版本目录已清理", not (INSTALL / "app" / "2.0.2").exists())
    check("失败原因保留在日志里", "demo: this build fails at start" in (INSTALL / "state" / "app-last-run.log").read_text(encoding="utf-8", errors="replace"))
    stop(proc, info)

    # 5. 手动回滚
    print(cli("rollback").strip())
    proc, info = start()
    version = served_version(info)
    check("手动回滚到 2.0.0", "2.0.0" in version, version)
    stop(proc, info)

    # 5b. 回滚后在页面里再次升级到 2.0.1（上一版本目录可以被覆盖）
    proc, info = start()
    received = INSTALL / "vse-app-2.0.1.vsepkg"
    shutil.copy2(OUT / "updates" / "vse-app-2.0.1.vsepkg", received)
    post(info["url"] + "api/p/settings/app-updates/install", {"file": received.name})
    post(info["url"] + "api/p/settings/app-updates/restart")
    info = wait_for_version(info, "2.0.1")
    check("回滚后再次升级到 2.0.1", status()["app"]["current"] == "2.0.1")
    received.unlink()
    stop(proc, info)

    # 6. 篡改的包被拒绝
    tampered = OUT / "tampered.vsepkg"
    data = bytearray((OUT / "updates" / "vse-app-2.0.1.vsepkg").read_bytes())
    data[len(data) // 2] ^= 0xFF
    tampered.write_bytes(bytes(data))
    done = subprocess.run([str(EXE), "stage", str(tampered)], env=ENV, capture_output=True, timeout=60)
    log = (INSTALL / "state" / "launcher.log").read_text(encoding="utf-8", errors="replace")
    reason = [line for line in log.splitlines() if "tampered" in line][-1:]
    check("篡改过的更新包被拒绝（不弹错误框、不卡住）", done.returncode == 1 and bool(reason), reason[0][-60:] if reason else "")
    tampered.unlink()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
