# -*- coding: utf-8 -*-
"""签署日报第 1 期探针：受信进程（Excel）能否在 VSE 拉起的子进程里代读。

只回答一个问题，不做任何代读管道：VSE-WebUI.exe --sign-daily-probe <样本.xlsx>
（源码态 python webui.py --sign-daily-probe <样本.xlsx>）先自检参数，再用
sys.executable 自调起 --sign-daily-probe-child **自己的子进程**，由子进程用
独立 Excel 实例只读打开样本，取 UsedRange 行列数与第一行表头，与
services.tdc_official_rows.official_contract_headers("data_model") **逐字**比较
（不 strip、不做 Unicode 归一），父进程带总超时（默认 90 秒）并打印一行 JSON。

安全边界（照抄 docs/PLAN_20261111_SIGNDAILY_ENCRYPTED.md 第 3.2 节）：

- 独立 Application 实例（不附着用户已开的 Excel），DisplayAlerts=False、
  AutomationSecurity=3（禁用宏）；
- books.open(..., read_only=True, update_links=False, notify=False, add_to_mru=False)；
- 工作表取 book.sheets[0]（与 zip 路一致，禁用 ActiveSheet）；
- 关闭工作簿 SaveChanges=False、quit() 全在 finally 里，只 quit 自己创建的实例；
- 报告只有行列数、表头是否逐字一致、耗时、异常类名与进程谱系：
  **不打印单元格内容、不打印文件路径（连 basename 也不打印，只用 sizeBytes）、
  不打印堆栈、不打印十六进制**；
- 不写文件、不落临时文件、不建目录、不 import web.*、不 import 任何插件。

报告字段（父进程只透传这些键，子进程多出的键一律丢弃）：
ok / rows / cols / headerCount / headerMatch / elapsedMs / errorType
（异常类名或 excel_unavailable / timeout / worker_protocol_error，成功时为空串）/
sizeBytes（唯一的文件身份信息）/ lineage（pid / parentImage / selfImage / frozen）。

退出码：0 读取成功（ok=true）；1 读取失败（有明确 errorType）；2 参数错误。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: 父进程哨兵（VSE-WebUI.exe --sign-daily-probe <样本>）。
PROBE_FLAG = "--sign-daily-probe"
#: 子进程哨兵：唯一做 Excel COM 读取的进程，由父进程用 sys.executable 自调起。
CHILD_FLAG = "--sign-daily-probe-child"
#: 结果帧前缀：子进程只打一帧，父进程按前缀认帧（其余输出都当噪声丢掉）。
FRAME_PREFIX = "@@VSE_SIGN_DAILY_PROBE@@"

#: 父进程总超时（秒）。
DEFAULT_TIMEOUT_SECONDS = 90.0
#: --timeout 上限（秒）：再长就不像一次探针了。
MAX_TIMEOUT_SECONDS = 600.0
#: 超时杀树后等回收输出的宽限（秒）。
_REAP_TIMEOUT_SECONDS = 10.0

EXIT_OK = 0
EXIT_READ_FAILED = 1
EXIT_USAGE = 2

ERROR_EXCEL_UNAVAILABLE = "excel_unavailable"
ERROR_TIMEOUT = "timeout"
ERROR_WORKER_PROTOCOL = "worker_protocol_error"

#: 表头比对基准：签署日报数据表。
REPORT_TYPE = "data_model"

#: 父进程允许透传的顶层键；其余一律丢弃，防止任何内容经控制台漏出。
_RECORD_KEYS = (
    "ok",
    "rows",
    "cols",
    "headerCount",
    "headerMatch",
    "elapsedMs",
    "errorType",
    "sizeBytes",
)
_LINEAGE_KEYS = ("pid", "parentImage", "selfImage", "frozen")
#: 谱系字符串的截断长度（映像名很短，不可能是路径全文）。
_TEXT_LIMIT = 64


class _UsageError(ValueError):
    """参数错误（退出码 2）。消息里绝不回显文件路径。"""


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _image_name(executable: str | None = None) -> str:
    """可执行映像名（只取文件名：探针不打印任何完整路径）。"""
    raw = sys.executable if executable is None else executable
    name = Path(str(raw or "")).name
    return name[:_TEXT_LIMIT]


def _parent_image_name() -> str:
    """查父进程映像名：证明本进程确实挂在 VSE 拉起的父进程下。

    只用标准库 ctypes（kernel32），不引入 psutil/pywin32；失败只返回空串。
    """
    if not _is_windows():
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        # PROCESS_QUERY_LIMITED_INFORMATION：只需要读映像名，不要满权限。
        handle = kernel32.OpenProcess(0x1000, False, int(os.getppid()))
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return Path(buffer.value).name[:_TEXT_LIMIT]
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - 谱系只是证据，查不到不该让探针失败
        return ""


def _lineage(
    *,
    pid: int | None = None,
    parent_image: str | None = None,
    self_image: str | None = None,
    frozen: bool | None = None,
) -> dict:
    return {
        "pid": int(os.getpid() if pid is None else pid),
        "parentImage": _parent_image_name() if parent_image is None else str(parent_image)[:_TEXT_LIMIT],
        "selfImage": _image_name() if self_image is None else str(self_image)[:_TEXT_LIMIT],
        "frozen": _is_frozen() if frozen is None else bool(frozen),
    }


def _record(
    *,
    ok: bool,
    rows: int = 0,
    cols: int = 0,
    header_count: int = 0,
    header_match: bool = False,
    elapsed_ms: int = 0,
    error_type: str = "",
    size_bytes: int = 0,
    lineage: dict | None = None,
) -> dict:
    """构造一份只含白名单字段的报告。"""
    return {
        "ok": bool(ok),
        "rows": int(rows),
        "cols": int(cols),
        "headerCount": int(header_count),
        "headerMatch": bool(header_match),
        "elapsedMs": int(elapsed_ms),
        "errorType": str(error_type)[:_TEXT_LIMIT],
        "sizeBytes": int(size_bytes),
        "lineage": dict(lineage) if lineage is not None else _lineage(),
    }


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.monotonic() - started) * 1000)))


def _close_quietly(book, app) -> None:
    """finally 收尾：只关自己打开的簿、只 quit 自己创建的实例，异常一律吞掉。"""
    if book is not None:
        try:
            book.api.Close(SaveChanges=False)
        except Exception:  # noqa: BLE001 - 关闭失败只能兜底，不能掩盖读取结论
            try:
                book.close()
            except Exception:  # noqa: BLE001
                pass
    if app is not None:
        try:
            app.quit()
        except Exception:  # noqa: BLE001 - quit 失败时释放实例，避免残留隐身 Excel
            kill = getattr(app, "kill", None)
            if callable(kill):
                try:
                    kill()
                except Exception:  # noqa: BLE001
                    pass


def _read_workbook_probe(path: Path) -> dict:
    """子进程主体：只读打开样本，取行列数与第一行表头是否逐字一致。"""
    started = time.monotonic()
    size = _file_size(path)
    lineage = _lineage()

    def failed(error_type: str, *, rows: int = 0, cols: int = 0, header_count: int = 0) -> dict:
        return _record(
            ok=False,
            rows=rows,
            cols=cols,
            header_count=header_count,
            elapsed_ms=_elapsed_ms(started),
            error_type=error_type,
            size_bytes=size,
            lineage=lineage,
        )

    if not _is_windows():
        return failed(ERROR_EXCEL_UNAVAILABLE)

    # 表头基准来自只读常量（core.report_contracts），不读任何样本内容。
    try:
        from services.tdc_official_rows import official_contract_headers

        expected = list(official_contract_headers(REPORT_TYPE))
    except Exception as exc:  # noqa: BLE001 - 连基准都取不到时只报异常类名
        return failed(type(exc).__name__)

    try:
        import xlwings as xw
    except Exception:  # noqa: BLE001 - xlwings 没进包 = 本机不能代读
        return failed(ERROR_EXCEL_UNAVAILABLE)

    try:
        # 独立实例：不附着、不复用用户已打开的 Excel。
        app = xw.App(visible=False, add_book=False)
    except Exception:  # noqa: BLE001 - 起不了 Excel 就是本机没有可用的 Excel
        return failed(ERROR_EXCEL_UNAVAILABLE)

    book = None
    rows = 0
    cols = 0
    header_cells: list = []
    try:
        try:
            app.api.DisplayAlerts = False
        except Exception:  # noqa: BLE001
            pass
        try:
            # msoAutomationSecurityForceDisable：不执行任何宏。
            app.api.AutomationSecurity = 3
        except Exception:  # noqa: BLE001
            pass
        book = app.books.open(
            str(path),
            read_only=True,
            update_links=False,
            notify=False,
            add_to_mru=False,
        )
        sheet = book.sheets[0]  # 与 zip 路一致：第一张工作表，禁用 ActiveSheet
        used = sheet.api.UsedRange
        rows = int(used.Rows.Count or 0)
        cols = int(used.Columns.Count or 0)
        compare_cols = max(0, min(cols, len(expected)))
        if compare_cols:
            raw = sheet.range((1, 1), (1, compare_cols)).value
            # 单格返回标量、单行返回一维：两种都要接住。
            header_cells = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    except Exception as exc:  # noqa: BLE001 - 只报异常类名，绝不打印堆栈
        return failed(type(exc).__name__, rows=rows, cols=cols, header_count=len(header_cells))
    finally:
        _close_quietly(book, app)

    header_count = len(header_cells)
    header_match = (
        cols >= len(expected)
        and header_count == len(expected)
        and all(
            isinstance(value, str) and value == expected[index]
            for index, value in enumerate(header_cells)
        )
    )
    return _record(
        ok=True,
        rows=rows,
        cols=cols,
        header_count=header_count,
        header_match=header_match,
        elapsed_ms=_elapsed_ms(started),
        error_type="",
        size_bytes=size,
        lineage=lineage,
    )


def _child_main(path: Path) -> int:
    """子进程：做完读取后只向 stdout 打一帧，其余输出全部改道 stderr。"""
    try:
        sys.stdout.flush()
        private_stdout = sys.stdout
    except Exception:  # noqa: BLE001
        private_stdout = None
    # 在算之前就把 sys.stdout 接到 stderr：xlwings/COM 的杂项输出不得污染结果帧。
    try:
        sys.stdout = sys.stderr
    except Exception:  # noqa: BLE001
        pass

    record = _read_workbook_probe(path)
    payload = (FRAME_PREFIX + json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        os.write(1, payload)
    except OSError:
        if private_stdout is None:
            return EXIT_READ_FAILED
        try:
            private_stdout.write(payload.decode("utf-8"))
            private_stdout.flush()
        except Exception:  # noqa: BLE001
            return EXIT_READ_FAILED
    return EXIT_OK if record["ok"] else EXIT_READ_FAILED


def _creation_flags() -> int:
    if _is_windows():
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _self_command(extra: list[str]) -> list[str]:
    """用 sys.executable 自调起：冻结态是同一个 exe，源码态是同一个入口脚本。"""
    if _is_frozen():
        return [sys.executable, *extra]
    script = Path(__file__).resolve().parent.parent / "webui.py"
    if not script.is_file():
        argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
        if argv0 is not None and argv0.suffix == ".py" and argv0.is_file():
            script = argv0
    return [sys.executable, str(script), *extra]


def _kill_process_tree(pid: int) -> None:
    """超时后杀子进程树。

    注意：Excel 由 DCOM 启动，不在 worker 的进程树里（方案第 3.3 节）——探针不杀、
    也不动用户自己开着的 Excel；可能的隐身实例需人工确认。
    """
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(),
            timeout=15,
            check=False,
        )
    except Exception:  # noqa: BLE001 - 杀不掉也要继续报 timeout
        pass


def _extract_frames(raw: bytes) -> list[dict]:
    """从子进程 stdout 里认出结果帧（其余噪声行忽略）。"""
    frames: list[dict] = []
    for line in raw.splitlines():
        text = line.decode("utf-8", "replace").strip()
        if not text.startswith(FRAME_PREFIX):
            continue
        try:
            payload = json.loads(text[len(FRAME_PREFIX):])
        except ValueError:
            frames.append({})
            continue
        frames.append(payload if isinstance(payload, dict) else {})
    return frames


def _parent_lineage(child_pid: int | None) -> dict:
    """父侧补出的谱系：pid 是子进程，parentImage 是本进程（父）的映像名。"""
    return _lineage(
        pid=child_pid if child_pid is not None else os.getpid(),
        parent_image=_image_name(),
        self_image=_image_name(),
        frozen=_is_frozen(),
    )


def _failure_record(child_pid: int | None, error_type: str, started: float, size_bytes: int) -> dict:
    return _record(
        ok=False,
        elapsed_ms=_elapsed_ms(started),
        error_type=error_type,
        size_bytes=size_bytes,
        lineage=_parent_lineage(child_pid),
    )


def _sanitize(payload: dict, child_pid: int, started: float, size_bytes: int) -> dict:
    """按白名单重建报告：字段缺失、类型不对、pid 不符一律转 worker_protocol_error。"""
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict):
        return _failure_record(child_pid, ERROR_WORKER_PROTOCOL, started, size_bytes)
    if any(key not in payload for key in _RECORD_KEYS):
        return _failure_record(child_pid, ERROR_WORKER_PROTOCOL, started, size_bytes)
    if any(key not in lineage for key in _LINEAGE_KEYS):
        return _failure_record(child_pid, ERROR_WORKER_PROTOCOL, started, size_bytes)
    try:
        pid = int(lineage["pid"])
    except (TypeError, ValueError):
        return _failure_record(child_pid, ERROR_WORKER_PROTOCOL, started, size_bytes)
    if pid != child_pid:
        # 帧不是这个子进程发的：宁可报协议错误，也不采信。
        return _failure_record(child_pid, ERROR_WORKER_PROTOCOL, started, size_bytes)
    return _record(
        ok=bool(payload["ok"]),
        rows=_as_int(payload["rows"]),
        cols=_as_int(payload["cols"]),
        header_count=_as_int(payload["headerCount"]),
        header_match=bool(payload["headerMatch"]),
        elapsed_ms=_as_int(payload["elapsedMs"]),
        error_type=str(payload["errorType"])[:_TEXT_LIMIT],
        size_bytes=_as_int(payload["sizeBytes"]) or size_bytes,
        lineage={
            "pid": pid,
            "parentImage": str(lineage["parentImage"])[:_TEXT_LIMIT],
            "selfImage": str(lineage["selfImage"])[:_TEXT_LIMIT],
            "frozen": bool(lineage["frozen"]),
        },
    )


def _run_child(path: Path, timeout: float) -> dict:
    """父进程：拉起自己的子进程、带总超时收帧。"""
    started = time.monotonic()
    size = _file_size(path)
    try:
        proc = subprocess.Popen(
            _self_command([CHILD_FLAG, str(path)]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_creation_flags(),
        )
    except OSError as exc:
        return _record(
            ok=False,
            elapsed_ms=_elapsed_ms(started),
            error_type=type(exc).__name__,
            size_bytes=size,
            lineage=_parent_lineage(None),
        )

    child_pid = proc.pid
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(child_pid)
        try:
            proc.communicate(timeout=_REAP_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - 回收失败不影响报 timeout
            pass
        return _failure_record(child_pid, ERROR_TIMEOUT, started, size)

    frames = _extract_frames(out or b"")
    if len(frames) != 1:
        return _failure_record(child_pid, ERROR_WORKER_PROTOCOL, started, size)
    return _sanitize(frames[0], child_pid, started, size)


def _usage_text() -> str:
    return (
        "用法: VSE-WebUI.exe --sign-daily-probe <加密样本.xlsx> [--timeout 秒]\n"
        "源码态: python webui.py --sign-daily-probe <加密样本.xlsx> [--timeout 秒]\n"
        "探针只读 UsedRange 行列数与第一行表头是否逐字一致，不输出任何表格内容，"
        "不生成任何文件。"
    )


def _parse_options(argv: list[str]) -> tuple[Path, float]:
    """父进程自检参数（不打开文件、不启动 Excel）。路径一律不回显。"""
    raw_path = ""
    timeout = DEFAULT_TIMEOUT_SECONDS
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--timeout":
            index += 1
            if index >= len(argv):
                raise _UsageError("参数错误：--timeout 后面要跟秒数（例如 --timeout 120）。")
            try:
                timeout = float(argv[index])
            except ValueError as exc:
                raise _UsageError("参数错误：--timeout 只接受秒数（例如 --timeout 120）。") from exc
            if not 0 < timeout <= MAX_TIMEOUT_SECONDS:
                raise _UsageError(
                    f"参数错误：--timeout 必须在 0 到 {int(MAX_TIMEOUT_SECONDS)} 秒之间。"
                )
        elif arg.startswith("-"):
            raise _UsageError(f"参数错误：不认识的选项 {arg}。")
        elif raw_path:
            raise _UsageError("参数错误：只接受一个文件路径（路径含空格时请用英文双引号包住）。")
        else:
            raw_path = arg
        index += 1
    if not raw_path:
        raise _UsageError("参数错误：缺少加密样本文件路径。")
    if raw_path.startswith("\\\\"):
        raise _UsageError("参数错误：不支持网络路径（双反斜杠开头），请用本机磁盘上的文件。")
    path = Path(raw_path)
    if not path.is_file():
        raise _UsageError("参数错误：找不到这个文件（请确认路径存在、文件没有被移动）。")
    if path.suffix.lower() != ".xlsx":
        raise _UsageError("参数错误：只接受 .xlsx 文件（请在 Excel 里另存为 .xlsx）。")
    return path, timeout


def _print_json(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    try:
        print(line)
    except UnicodeEncodeError:  # 控制台代码页非 UTF-8 时退回纯 ASCII 转义
        print(json.dumps(record, ensure_ascii=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    """探针入口：--sign-daily-probe（父）与 --sign-daily-probe-child（子）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == CHILD_FLAG:
        if len(args) < 2 or not args[1]:
            print(_usage_text(), file=sys.stderr)
            return EXIT_USAGE
        return _child_main(Path(args[1]))
    if args and args[0] == PROBE_FLAG:
        args = args[1:]

    try:
        path, timeout = _parse_options(args)
    except _UsageError as exc:
        # 参数错误只说人话，不打 JSON：本期没有 usage 类的 errorType。
        print(f"{exc}\n\n{_usage_text()}", file=sys.stderr)
        return EXIT_USAGE

    record = _run_child(path, timeout)
    _print_json(record)
    return EXIT_OK if record.get("ok") else EXIT_READ_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
