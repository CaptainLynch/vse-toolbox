# -*- coding: utf-8 -*-
"""签署日报「Excel 代读」通道：父进程拉起自己的一次性子进程，由子进程让 Excel 只读取数。

背景：公司终端加密的 xlsx，本进程（非受信）读到的是密文；Excel（受信）读得到内容。
代读 = 子进程用独立 Excel 实例只读打开文件，把第一张工作表的值经 stdout 管道交回父进程。
**不解密、不剥文件头、不产生任何明文文件**；值只在内存与匿名管道里出现。

是否允许走这条路由调用方决定（部署授权 + 用户开关，见 plugins/sign_daily/excel_proxy.py）；
本模块只管「安全地读一次」：

- 子进程：``<本程序> --sign-daily-read-child <路径> <最大行> <最大列>``。启动即把
  ``sys.stdout`` 改道到 stderr（杂项输出不得污染帧），帧只经文件描述符 1 写出。
- 帧：4 字节大端长度 + UTF-8 JSON（不用 pickle）。顺序固定为
  ``hello``（子进程 PID、Excel 的 PID 与创建时间）→ ``meta``（行列数）→ ``data`` 或 ``error``。
  hello 在打开工作簿**之前**发出，这样即使随后卡死，父进程也知道该清理哪个 Excel。
- 父进程：读线程 + 总字节上限 + 总超时；全局单并发（占用时立刻返回 ``busy``）。
  子进程的 stderr 直接丢弃、绝不进日志（异常文本可能带单元格内容）。
- 清理：Excel 由 DCOM 启动，不在子进程的进程树里，杀树杀不到它。父进程按
  「PID + 映像名 EXCEL.EXE + 创建时间」三项都与 hello 一致才结束它——绝不按进程名
  枚举，绝不动用户自己开着的 Excel。

失败只用闭集 reason 表达（``READ_REASONS``），不带单元格内容、路径或异常原文。
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

#: 子进程哨兵（webui.py 在加载 Flask 之前识别它）。
CHILD_FLAG = "--sign-daily-read-child"

DEFAULT_TIMEOUT_SECONDS = 120.0
#: 管道总字节上限：5000 行 × 47 列的 JSON 远小于它，超过只可能是异常输入。
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
#: 超时/结束后等待回收的宽限（秒）。
_REAP_SECONDS = 10.0
_EXCEL_IMAGE = "EXCEL.EXE"

REASON_EXCEL_UNAVAILABLE = "excel_unavailable"
REASON_CANNOT_OPEN = "excel_cannot_open"
REASON_HAS_FORMULA = "has_formula"
REASON_NOT_AT_A1 = "range_not_at_a1"
REASON_TOO_LARGE = "too_large"
REASON_CELL_ERROR = "cell_error"
REASON_TIMEOUT = "timeout"
REASON_BUSY = "busy"
REASON_PROTOCOL = "worker_protocol_error"
REASON_PATH_REJECTED = "path_rejected"
#: 子进程允许在 error 帧里报的词（其余一律当协议错误）。
_CHILD_REASONS = (
    REASON_EXCEL_UNAVAILABLE,
    REASON_CANNOT_OPEN,
    REASON_HAS_FORMULA,
    REASON_NOT_AT_A1,
    REASON_TOO_LARGE,
    REASON_CELL_ERROR,
)
READ_REASONS = (*_CHILD_REASONS, REASON_TIMEOUT, REASON_BUSY, REASON_PROTOCOL, REASON_PATH_REJECTED)

_HEADER = struct.Struct(">I")
_LOCK = threading.Lock()


class ExcelReadError(RuntimeError):
    """代读失败；reason 是 READ_REASONS 之一。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"excel read failed: {reason}")
        self.reason = reason


# ── 帧 ──────────────────────────────────────────────────────────────


def encode_frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _HEADER.pack(len(body)) + body


def decode_frames(raw: bytes) -> list[dict[str, Any]]:
    """把管道字节切成帧；任何不完整/不是 JSON 对象的内容都抛 ``worker_protocol_error``。"""
    frames: list[dict[str, Any]] = []
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < _HEADER.size:
            raise ExcelReadError(REASON_PROTOCOL)
        (length,) = _HEADER.unpack_from(raw, offset)
        offset += _HEADER.size
        if length <= 0 or length > len(raw) - offset:
            raise ExcelReadError(REASON_PROTOCOL)
        try:
            payload = json.loads(raw[offset:offset + length].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ExcelReadError(REASON_PROTOCOL) from None
        if not isinstance(payload, dict):
            raise ExcelReadError(REASON_PROTOCOL)
        frames.append(payload)
        offset += length
    return frames


# ── Windows 进程信息（只用标准库 ctypes）────────────────────────────


def _process_identity(pid: int) -> tuple[str, int] | None:
    """(映像文件名, 创建时间 FILETIME 整数)；查不到返回 None。"""
    if sys.platform != "win32" or pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value != 259:
                return None  # 已退出（259 = STILL_ACTIVE）
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return None
            stamp = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return Path(buffer.value).name, stamp
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - 查不到就当不存在，绝不因此误杀
        return None


def terminate_process_if_same(pid: int, image: str, created: int) -> bool:
    """只有 PID、映像名、创建时间三项都对得上才结束该进程；返回是否真的结束了它。"""
    identity = _process_identity(pid)
    if identity is None or not image or created <= 0:
        return False
    if identity[0].lower() != image.lower() or identity[1] != created:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = kernel32.OpenProcess(0x0001 | 0x1000, False, int(pid))  # TERMINATE | QUERY_LIMITED
        if not handle:
            return False
        try:
            # 打开句柄后再核对一次：防止在两次调用之间 PID 被复用。
            again = _process_identity(pid)
            if again is None or again[0].lower() != image.lower() or again[1] != created:
                return False
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return False


# ── 子进程 ──────────────────────────────────────────────────────────


def _write_frame(payload: dict[str, Any]) -> None:
    data = encode_frame(payload)
    view = memoryview(data)
    while view:
        written = os.write(1, view[:65536])
        view = view[written:]


def child_main(argv: list[str]) -> int:
    """子进程入口：``[路径, 最大行, 最大列]``。只经 fd 1 写帧，其余输出改道 stderr。"""
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    sys.stdout = sys.stderr
    if sys.platform == "win32":
        try:
            import msvcrt

            msvcrt.setmode(1, os.O_BINARY)
        except Exception:  # noqa: BLE001
            pass
    try:
        path = Path(argv[0])
        max_rows, max_cols = int(argv[1]), int(argv[2])
    except (IndexError, ValueError):
        return 2

    from services.excel_toolbox import SHEET_REASONS, SheetReadError, read_sheet_matrix

    def announce(app: Any) -> None:
        excel_pid = int(getattr(app, "pid", 0) or 0)
        identity = _process_identity(excel_pid)
        _write_frame({
            "type": "hello",
            "pid": os.getpid(),
            "excelPid": excel_pid,
            "excelCreated": identity[1] if identity and identity[0].lower() == _EXCEL_IMAGE.lower() else 0,
        })

    try:
        matrix = read_sheet_matrix(path, max_rows=max_rows, max_cols=max_cols, on_app_started=announce)
    except SheetReadError as exc:
        reason = exc.reason if exc.reason in SHEET_REASONS else REASON_CANNOT_OPEN
        _write_frame({"type": "error", "reason": reason})
        return 1
    except Exception:  # noqa: BLE001 - 任何意外都只报枚举
        _write_frame({"type": "error", "reason": REASON_CANNOT_OPEN})
        return 1
    _write_frame({"type": "meta", "rows": len(matrix), "cols": len(matrix[0]) if matrix else 0})
    _write_frame({"type": "data", "matrix": matrix})
    return 0


# ── 父进程 ──────────────────────────────────────────────────────────


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0


def _child_command(path: Path, max_rows: int, max_cols: int) -> list[str]:
    """用 sys.executable 自调起：冻结态是同一个 exe，源码态是 webui.py。"""
    extra = [CHILD_FLAG, str(path), str(int(max_rows)), str(int(max_cols))]
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "webui.py"), *extra]


def check_path(path: Path) -> Path:
    """拉子进程之前的路径门：本机磁盘上的普通 .xlsx，不接受 UNC、链接与重解析点。"""
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        raise ExcelReadError(REASON_PATH_REJECTED)
    candidate = Path(text)
    if not candidate.is_absolute() or candidate.suffix.lower() != ".xlsx":
        raise ExcelReadError(REASON_PATH_REJECTED)
    try:
        info = candidate.lstat()
    except OSError:
        raise ExcelReadError(REASON_PATH_REJECTED) from None
    import stat as _stat

    reparse = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        _stat.S_ISLNK(info.st_mode)
        or not _stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & reparse
    ):
        raise ExcelReadError(REASON_PATH_REJECTED)
    return candidate


def _kill_tree(pid: int) -> None:
    """结束我们自己拉起的子进程（及其子进程）；不涉及 Excel。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(), timeout=15, check=False,
        )
    except Exception:  # noqa: BLE001
        pass


def _hello_from(raw: bytes) -> dict[str, Any] | None:
    """尽力从（可能不完整的）管道字节里取出第一帧 hello，用于超时后的清理。"""
    if len(raw) < _HEADER.size:
        return None
    (length,) = _HEADER.unpack_from(raw, 0)
    if length <= 0 or length > len(raw) - _HEADER.size or length > 4096:
        return None
    try:
        payload = json.loads(raw[_HEADER.size:_HEADER.size + length].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("type") == "hello" else None


def _cleanup_excel(hello: dict[str, Any] | None, terminate: Callable[[int, str, int], bool]) -> bool:
    if not hello:
        return False
    try:
        pid, created = int(hello.get("excelPid") or 0), int(hello.get("excelCreated") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or created <= 0:
        return False
    return terminate(pid, _EXCEL_IMAGE, created)


def _validate(frames: list[dict[str, Any]], max_rows: int, max_cols: int) -> list[list[Any]]:
    kinds = [frame.get("type") for frame in frames]
    if not frames or kinds[0] != "hello":
        # 没起得了 Excel 时子进程不会发 hello，只发一帧 error。
        if kinds == ["error"] and frames[0].get("reason") in _CHILD_REASONS:
            raise ExcelReadError(str(frames[0]["reason"]))
        raise ExcelReadError(REASON_PROTOCOL)
    hello_pid = frames[0].get("pid")
    if not isinstance(hello_pid, int) or isinstance(hello_pid, bool) or hello_pid <= 0:
        # 不要求等于 Popen 的 PID：venv 的 python.exe 是转发器，真正的解释器是它的子进程。
        raise ExcelReadError(REASON_PROTOCOL)
    if kinds == ["hello", "error"]:
        reason = frames[1].get("reason")
        raise ExcelReadError(str(reason) if reason in _CHILD_REASONS else REASON_PROTOCOL)
    if kinds != ["hello", "meta", "data"]:
        raise ExcelReadError(REASON_PROTOCOL)
    rows, cols, matrix = frames[1].get("rows"), frames[1].get("cols"), frames[2].get("matrix")
    if (
        not isinstance(rows, int) or isinstance(rows, bool)
        or not isinstance(cols, int) or isinstance(cols, bool)
        or not 0 < rows <= max_rows or not 0 < cols <= max_cols
        or not isinstance(matrix, list) or len(matrix) != rows
    ):
        raise ExcelReadError(REASON_PROTOCOL)
    for row in matrix:
        if not isinstance(row, list) or len(row) != cols:
            raise ExcelReadError(REASON_PROTOCOL)
        for value in row:
            if value is None or isinstance(value, str):
                continue
            if isinstance(value, bool) or not isinstance(value, float) or not math.isfinite(value):
                raise ExcelReadError(REASON_PROTOCOL)
    return matrix


def read_via_excel(
    path: Path,
    *,
    max_rows: int,
    max_cols: int,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[list[Any]]:
    """让 Excel 代读 ``path`` 的第一张工作表，返回值矩阵（只含 str / float / None）。

    失败抛 ``ExcelReadError(reason)``。路径不合格、通道被占用时**不会**拉起子进程。
    """
    target = check_path(Path(path))
    if not _LOCK.acquire(blocking=False):
        raise ExcelReadError(REASON_BUSY)
    try:
        return _read_locked(target, max_rows, max_cols, timeout, max_bytes)
    finally:
        _LOCK.release()


def _read_locked(path: Path, max_rows: int, max_cols: int, timeout: float, max_bytes: int) -> list[list[Any]]:
    try:
        proc = subprocess.Popen(
            _child_command(path, max_rows, max_cols),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # 不进日志：异常文本可能带单元格内容
            creationflags=_creation_flags(),
        )
    except OSError:
        raise ExcelReadError(REASON_EXCEL_UNAVAILABLE) from None

    chunks: list[bytes] = []
    state = {"bytes": 0, "overflow": False}

    def pump() -> None:
        stream = proc.stdout
        try:
            while True:
                chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)  # type: ignore[union-attr]
                if not chunk:
                    return
                state["bytes"] += len(chunk)
                if state["bytes"] > max_bytes:
                    state["overflow"] = True
                    return
                chunks.append(chunk)
        except (OSError, ValueError):
            return

    reader = threading.Thread(target=pump, name="sign-daily-excel-read", daemon=True)
    reader.start()
    deadline = time.monotonic() + max(0.1, float(timeout))
    timed_out = False
    while reader.is_alive():
        reader.join(timeout=0.1)
        if state["overflow"]:
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break

    failed_early = timed_out or state["overflow"]
    if failed_early:
        _kill_tree(proc.pid)
    try:
        proc.wait(timeout=_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    reader.join(timeout=_REAP_SECONDS)
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except OSError:
        pass

    raw = b"".join(chunks)
    # 无论成败：子进程登记过的那个 Excel 若还活着（且三项一致），由父进程收尾。
    _cleanup_excel(_hello_from(raw), terminate_process_if_same)

    if timed_out:
        raise ExcelReadError(REASON_TIMEOUT)
    if state["overflow"]:
        raise ExcelReadError(REASON_PROTOCOL)
    return _validate(decode_frames(raw), max_rows, max_cols)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == CHILD_FLAG:
        args = args[1:]
    return child_main(args)


__all__ = [
    "CHILD_FLAG",
    "ExcelReadError",
    "READ_REASONS",
    "check_path",
    "child_main",
    "decode_frames",
    "encode_frame",
    "main",
    "read_via_excel",
    "terminate_process_if_same",
]
