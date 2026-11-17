# -*- coding: utf-8 -*-
"""Excel 本机运行环境检测服务。

根据 docs/refactor-v2/CONTRACTS.md C10 契约与 W12 规格：
1. 检查本机是否已安装表格软件（支持注册表查询与标准安装位置探测）；
2. 检查授权激活状态——无法可靠确认时一律返回 {'state': 'need_check', 'text': '需要检查'}，绝不伪报通过；
3. 检测属于本工具拥有的残留进程（进程名匹配 + 启动命令行包含本工具可执行程序位置，
   绝不将用户自己打开的 Excel 进程纳入计算）；
4. 接口返回字段白名单，且所有可能包含敏感信息的字段均支持脱敏。

面向用户的所有文案均采用通俗中文，不出现任何内部术语。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]

try:
    from core.redaction import redact_sensitive_text
except ImportError:
    def redact_sensitive_text(text: str) -> str:  # type: ignore[misc]
        return text


# Excel 标准进程名集合（小写）
EXCEL_PROCESS_NAMES = frozenset({"excel.exe", "excel"})


def _query_registry_app_path() -> tuple[str | None, str | None]:
    """从 Windows 注册表查询 Excel 安装位置与版本信息。

    Returns:
        (可执行文件绝对路径或 None, 版本号字符串或 None)
    """
    if winreg is None:
        return None, None

    # 1. 尝试从 App Paths 读取 excel.exe 注册位置
    candidate_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
    ]

    excel_path: str | None = None
    for hkey, sub_key in candidate_keys:
        try:
            with winreg.OpenKey(hkey, sub_key) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and isinstance(val, str) and Path(val).exists():
                    excel_path = val
                    break
        except (OSError, FileNotFoundError):
            continue

    # 2. 尝试从 ProgID 读取版本号（如 Excel.Application.16 -> 16.0）
    version: str | None = None
    curver_keys = [
        (winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CurVer"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Excel.Application\CurVer"),
    ]
    for hkey, sub_key in curver_keys:
        try:
            with winreg.OpenKey(hkey, sub_key) as key:
                curver_val, _ = winreg.QueryValueEx(key, "")
                if curver_val and isinstance(curver_val, str):
                    # 匹配后缀数字，例如 Excel.Application.16 -> 16.0
                    m = re.search(r"(\d+)$", curver_val.strip())
                    if m:
                        version = f"{m.group(1)}.0"
                        break
        except (OSError, FileNotFoundError):
            continue

    return excel_path, version


def _detect_common_excel_paths() -> str | None:
    """在常见默认安装目录中探测 Excel 可执行文件。"""
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    candidate_dirs = [
        Path(program_files) / "Microsoft Office" / "root" / "Office16",
        Path(program_files_x86) / "Microsoft Office" / "root" / "Office16",
        Path(program_files) / "Microsoft Office" / "Office16",
        Path(program_files_x86) / "Microsoft Office" / "Office16",
        Path(program_files) / "Microsoft Office" / "Office15",
        Path(program_files_x86) / "Microsoft Office" / "Office15",
        Path(program_files) / "Microsoft Office" / "Office14",
        Path(program_files_x86) / "Microsoft Office" / "Office14",
    ]

    for c_dir in candidate_dirs:
        target = c_dir / "EXCEL.EXE"
        if target.exists() and target.is_file():
            return str(target)
    return None


def detect_excel_installation(
    *,
    registry_prober: Callable[[], tuple[str | None, str | None]] | None = None,
    path_prober: Callable[[], str | None] | None = None,
) -> tuple[bool, str | None, str | None]:
    """检测本机是否安装 Excel。

    Returns:
        (is_installed, excel_path, version)
    """
    reg_fn = registry_prober or _query_registry_app_path
    excel_path, version = reg_fn()

    if not excel_path:
        path_fn = path_prober or _detect_common_excel_paths
        excel_path = path_fn()

    if excel_path and not version:
        # 从安装路径猜测主版本号，例如包含 Office16
        m = re.search(r"Office(\d+)", excel_path, re.IGNORECASE)
        if m:
            version = f"{m.group(1)}.0"

    installed = bool(excel_path)
    return installed, excel_path, version


def _probe_windows_office_license(excel_path: str | None = None) -> str:
    """非阻塞尝试探测 Windows 下 Office 授权状态。

    返回:
        'licensed' (明确授权) / 'unlicensed' (明确未授权) / 'unknown' (不确定)
    """
    if sys.platform != "win32":
        return "unknown"

    # 寻找 OSPP.VBS 脚本位置
    script_candidates: list[Path] = []
    if excel_path:
        parent = Path(excel_path).parent
        script_candidates.extend([parent / "OSPP.VBS", parent.parent / "Office16" / "OSPP.VBS"])

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    script_candidates.extend([
        Path(program_files) / "Microsoft Office" / "Office16" / "OSPP.VBS",
        Path(program_files_x86) / "Microsoft Office" / "Office16" / "OSPP.VBS",
        Path(program_files) / "Microsoft Office" / "root" / "Office16" / "OSPP.VBS",
    ])

    ospp_script: Path | None = None
    for cand in script_candidates:
        if cand.exists() and cand.is_file():
            ospp_script = cand
            break

    if not ospp_script:
        return "unknown"

    try:
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
        res = subprocess.run(
            ["cscript", "//nologo", str(ospp_script), "/dstatus"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=flags,
        )
        stdout = res.stdout.upper()
        if "---LICENSED---" in stdout:
            return "licensed"
        if any(term in stdout for term in ["---NOTICES---", "---OOB_GRACE---", "UNLICENSED"]):
            return "unlicensed"
    except Exception:
        pass

    return "unknown"


def check_excel_activation(
    *,
    excel_path: str | None = None,
    activation_prober: Callable[..., dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """检查 Excel 激活状态。

    契约规定：无法可靠确认激活状态时，返回 {'state': 'need_check', 'text': '需要检查'}，绝不伪报通过。
    """
    need_check_result = {
        "state": "need_check",
        "text": "需要检查",
        "detail": "无法可靠确认激活状态，请在软件账户信息中核对",
    }

    if activation_prober is not None:
        try:
            custom_res = activation_prober(excel_path=excel_path)
            if isinstance(custom_res, dict):
                state = custom_res.get("state")
                if state == "activated":
                    return {
                        "state": "activated",
                        "text": custom_res.get("text") or "已激活",
                        "detail": custom_res.get("detail", "软件授权正常"),
                    }
                elif state == "unlicensed":
                    return {
                        "state": "unlicensed",
                        "text": custom_res.get("text") or "未激活",
                        "detail": custom_res.get("detail", "软件尚未激活或授权已过期"),
                    }
                elif state == "need_check":
                    return {
                        "state": "need_check",
                        "text": "需要检查",
                        "detail": custom_res.get("detail", need_check_result["detail"]),
                    }
        except Exception:
            return need_check_result

    # 真实系统环境下的非侵入探测
    try:
        status = _probe_windows_office_license(excel_path)
        if status == "licensed":
            return {
                "state": "activated",
                "text": "已激活",
                "detail": "软件授权正常",
            }
        elif status == "unlicensed":
            return {
                "state": "unlicensed",
                "text": "未激活",
                "detail": "软件尚未激活或授权已过期",
            }
    except Exception:
        pass

    # 无法确认一律落入 need_check，绝不伪报通过
    return need_check_result


def _enumerate_processes() -> list[dict[str, Any]]:
    """枚举当前系统正在运行的进程列表（Windows 下安全调用）。"""
    if sys.platform != "win32":
        return []

    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)

    # 1. 优先尝试 WMIC
    try:
        res = subprocess.run(
            ["wmic", "process", "get", "ProcessId,Name,CommandLine", "/format:csv"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=flags,
        )
        if res.returncode == 0 and res.stdout:
            procs: list[dict[str, Any]] = []
            for line in res.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                # CSV 顺序：Node,CommandLine,Name,ProcessId
                if len(parts) >= 4 and parts[-1].isdigit():
                    procs.append({
                        "pid": int(parts[-1]),
                        "name": parts[-2],
                        "command_line": parts[1],
                    })
            if procs:
                return procs
    except Exception:
        pass

    # 2. 备用尝试 PowerShell
    try:
        ps_cmd = "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
        )
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                procs = []
                for item in data:
                    if isinstance(item, dict):
                        procs.append({
                            "pid": int(item.get("ProcessId", 0)),
                            "name": str(item.get("Name", "")),
                            "command_line": str(item.get("CommandLine", "") or ""),
                        })
                return procs
    except Exception:
        pass

    return []


def find_residual_excel_processes(
    *,
    app_exe: str | Path | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """查找属于本工具的残留 Excel 进程。

    判定规则：
    1. 进程名匹配 Excel（如 excel.exe）；
    2. 启动命令行中包含本工具的可执行程序位置；
    3. 严禁将用户自行打开的 Excel 进程算作残留。

    Returns:
        包含脱敏字段的残留进程信息字典列表。
    """
    # 确定本工具的可执行文件路径基准
    if app_exe is None:
        target_app = Path(sys.executable).resolve()
    else:
        target_app = Path(app_exe).resolve()

    app_exe_str = str(target_app).strip().lower().replace("/", "\\")

    lister_fn = process_lister or _enumerate_processes
    raw_processes = lister_fn()

    residual_processes: list[dict[str, Any]] = []
    for proc in raw_processes:
        if not isinstance(proc, dict):
            continue

        raw_name = str(proc.get("name") or "").strip().lower()
        if raw_name not in EXCEL_PROCESS_NAMES:
            continue

        # 获取启动命令行
        raw_cmd = proc.get("command_line") or proc.get("cmdline") or ""
        if isinstance(raw_cmd, (list, tuple)):
            cmd_text = " ".join(str(c) for c in raw_cmd)
        else:
            cmd_text = str(raw_cmd)

        norm_cmd = cmd_text.lower().replace("/", "\\")

        # 核心判定：命令行中必须包含本工具的程序位置
        # 如果不包含，说明是用户自己打开的 Excel，绝不纳入！
        if app_exe_str and app_exe_str in norm_cmd:
            residual_processes.append({
                "pid": int(proc.get("pid", 0)),
                "name": str(proc.get("name", "")),
                "command_line": redact_sensitive_text(cmd_text),
            })

    return residual_processes


def check_excel_environment(
    *,
    app_exe: str | Path | None = None,
    registry_prober: Callable[[], tuple[str | None, str | None]] | None = None,
    path_prober: Callable[[], str | None] | None = None,
    activation_prober: Callable[..., dict[str, Any] | None] | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """执行完整的 Excel 本机运行环境检测。

    接口返回严格受限于字段白名单，且所有数据均脱敏输出：
    - installed: 是否已安装（布尔值）
    - install_state: 'installed' 或 'not_installed'
    - excel_path: 安装位置（字符串或 None，已脱敏）
    - version: 主版本号（字符串或 None）
    - activation: 激活状态字典 {'state': ..., 'text': ..., 'detail': ...}
    - residual_processes: 残留进程白名单列表
    - residual_count: 残留进程数量
    """
    installed, excel_path, version = detect_excel_installation(
        registry_prober=registry_prober,
        path_prober=path_prober,
    )

    if installed:
        activation_info = check_excel_activation(
            excel_path=excel_path,
            activation_prober=activation_prober,
        )
    else:
        # 未安装时激活状态必然落入 need_check
        activation_info = {
            "state": "need_check",
            "text": "需要检查",
            "detail": "未检测到可用的表格软件",
        }

    residual_procs = find_residual_excel_processes(
        app_exe=app_exe,
        process_lister=process_lister,
    )

    # 严格白名单结构输出
    return {
        "installed": installed,
        "install_state": "installed" if installed else "not_installed",
        "excel_path": redact_sensitive_text(excel_path) if excel_path else None,
        "version": str(version) if version else None,
        "activation": activation_info,
        "residual_processes": residual_procs,
        "residual_count": len(residual_procs),
    }
