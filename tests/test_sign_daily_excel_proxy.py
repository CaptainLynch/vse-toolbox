# -*- coding: utf-8 -*-
"""签署日报「Excel 代读」（第 1 期，2026-11-12）：加密的 xlsx 由本机 Excel 只读取数。

全部打桩，不依赖真 Excel：

- ``services.excel_toolbox.read_sheet_matrix``：用假的 xlwings 对象；
- ``services.sign_daily_excel_reader``：用假的子进程脚本验证帧协议、超时与清理；
- 插件路由：把 ``read_via_excel`` 换成返回合成矩阵的函数。

真 Excel 的对照（明文样本两条路逐格一致）在 .runtime/ 的本地脚本里做，不进测试。
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from services import excel_toolbox
from services import sign_daily_excel_reader as reader
from services.xlsx_preview import ENCRYPTED_CONTAINER_SIGNATURES, SNIFF_BYTES
from tests import test_plugin_sign_daily as base
from tests.test_ewo_official_rows import write_workbook
from tests.test_plugin_sign_daily import API, HEADERS, _ok, _publish, _rows, _snapshot_counts

REPO = Path(__file__).resolve().parent.parent
SENTINEL = "哨兵串QW7ZP3"
COUNT_NAMES = ("应签人数", "已签人数", "未签人数")

client = base.client


# ── 假的 xlwings ────────────────────────────────────────────────────


class _Dim:
    def __init__(self, count: int) -> None:
        self.Count = count


class _Used:
    def __init__(self, rows: int, cols: int, *, row: int = 1, col: int = 1, has_formula: object = False) -> None:
        self.Row, self.Column = row, col
        self.Rows, self.Columns = _Dim(rows), _Dim(cols)
        self.HasFormula = has_formula


class _RangeApi:
    def __init__(self, value: object) -> None:
        self.Value2 = value


class _Range:
    def __init__(self, value: object) -> None:
        self.api = _RangeApi(value)


class _SheetApi:
    def __init__(self, used: _Used) -> None:
        self.UsedRange = used

    @property
    def ActiveSheet(self):  # pragma: no cover - 用到就是违反约定
        raise AssertionError("ActiveSheet must not be used")


class _Sheet:
    def __init__(self, used: _Used, value: object, log: list) -> None:
        self.api = _SheetApi(used)
        self._value, self._log = value, log

    def range(self, start, end):
        self._log.append(("range", start, end))
        return _Range(self._value)


class _BookApi:
    def __init__(self, log: list) -> None:
        self._log = log

    def Close(self, SaveChanges=None):  # noqa: N802,N803 - COM 命名
        self._log.append(("close", SaveChanges))


class _Sheets:
    def __init__(self, sheet: _Sheet, log: list) -> None:
        self._sheet, self._log = sheet, log

    def __getitem__(self, index):
        self._log.append(("sheet", index))
        return self._sheet


class _Book:
    def __init__(self, sheet: _Sheet, log: list) -> None:
        self.sheets = _Sheets(sheet, log)
        self.api = _BookApi(log)


class _Books:
    def __init__(self, book: _Book | None, log: list, error: Exception | None) -> None:
        self._book, self._log, self._error = book, log, error

    def open(self, path, **kwargs):
        self._log.append(("open", kwargs))
        if self._error is not None:
            raise self._error
        return self._book


class _AppApi:
    DisplayAlerts = True
    AutomationSecurity = 1


class _FakeXlwings:
    """``xw.App(...)`` 的替身：记录调用，按给定的 UsedRange 与 Value2 应答。"""

    def __init__(self, used: _Used | None = None, value: object = None, *,
                 app_error: Exception | None = None, open_error: Exception | None = None) -> None:
        self.log: list = []
        self.app_api = _AppApi()
        self._used, self._value = used, value
        self._app_error, self._open_error = app_error, open_error

    def App(self, **kwargs):  # noqa: N802 - xlwings 命名
        self.log.append(("app", kwargs))
        if self._app_error is not None:
            raise self._app_error
        owner = self

        class _App:
            pid = 4242
            api = owner.app_api
            books = _Books(
                _Book(_Sheet(owner._used, owner._value, owner.log), owner.log) if owner._used else None,
                owner.log, owner._open_error,
            )

            def quit(self):
                owner.log.append(("quit",))

        return _App()


def _read(fake: _FakeXlwings, monkeypatch, **kwargs):
    monkeypatch.setattr(excel_toolbox, "_get_xlwings", lambda: fake)
    return excel_toolbox.read_sheet_matrix(Path("C:/x/a.xlsx"), max_rows=100, max_cols=60, **kwargs)


def test_read_sheet_matrix_reads_once_with_safe_options(monkeypatch) -> None:
    fake = _FakeXlwings(_Used(2, 3), (("a", "b", "c"), ("x", 1.0, None)))
    started: list = []
    matrix = _read(fake, monkeypatch, on_app_started=started.append)

    assert matrix == [["a", "b", "c"], ["x", 1.0, None]]
    assert ("app", {"visible": False, "add_book": False}) in fake.log  # 独立实例
    opened = next(entry[1] for entry in fake.log if entry[0] == "open")
    assert opened == {"read_only": True, "update_links": False, "notify": False, "add_to_mru": False}
    assert fake.app_api.DisplayAlerts is False and fake.app_api.AutomationSecurity == 3
    assert ("sheet", 0) in fake.log  # 第一张工作表，不是 ActiveSheet
    assert ("range", (1, 1), (2, 3)) in fake.log
    assert sum(1 for entry in fake.log if entry[0] == "range") == 1  # 一次取值
    assert ("close", False) in fake.log and ("quit",) in fake.log  # 不保存、退出自己的实例
    assert len(started) == 1 and started[0].pid == 4242


@pytest.mark.parametrize(
    "used,value,expected",
    [
        (_Used(1, 1), "only", [["only"]]),  # 单格返回标量
        (_Used(1, 1), None, [[None]]),  # 空表
        (_Used(1, 3), ("a", "b", "c"), [["a", "b", "c"]]),  # 单行返回一维
        (_Used(1, 3), (("a", "b", "c"),), [["a", "b", "c"]]),
        (_Used(3, 1), ("a", "b", "c"), [["a"], ["b"], ["c"]]),  # 单列返回一维
    ],
)
def test_read_sheet_matrix_normalizes_shapes(monkeypatch, used, value, expected) -> None:
    assert _read(_FakeXlwings(used, value), monkeypatch) == expected


@pytest.mark.parametrize(
    "fake,reason",
    [
        (_FakeXlwings(_Used(2, 2, has_formula=True), (("a", "b"), ("c", "d"))), "has_formula"),
        (_FakeXlwings(_Used(2, 2, has_formula=None), (("a", "b"), ("c", "d"))), "has_formula"),  # 部分是公式
        (_FakeXlwings(_Used(2, 2, row=2), (("a", "b"), ("c", "d"))), "range_not_at_a1"),
        (_FakeXlwings(_Used(2, 2, col=3), (("a", "b"), ("c", "d"))), "range_not_at_a1"),
        (_FakeXlwings(_Used(101, 2), None), "too_large"),
        (_FakeXlwings(_Used(2, 61), None), "too_large"),
        (_FakeXlwings(_Used(2, 2), (("a", "b"), ("c", True))), "cell_error"),
        (_FakeXlwings(_Used(2, 2), (("a", "b"), ("c", -2146826281))), "cell_error"),  # Excel 错误码是 int
        (_FakeXlwings(_Used(2, 2), (("a", "b"), ("c", float("nan")))), "cell_error"),
        (_FakeXlwings(_Used(2, 2), (("a", "b"),)), "cell_error"),  # 形状与 UsedRange 不符
        (_FakeXlwings(_Used(2, 2), None, open_error=RuntimeError(SENTINEL)), "excel_cannot_open"),
    ],
)
def test_read_sheet_matrix_fails_closed_and_still_quits(monkeypatch, fake, reason) -> None:
    with pytest.raises(excel_toolbox.SheetReadError) as caught:
        _read(fake, monkeypatch)
    assert caught.value.reason == reason
    assert reason in excel_toolbox.SHEET_REASONS
    assert SENTINEL not in str(caught.value)
    assert ("quit",) in fake.log  # 失败也要退出自己创建的实例


def test_read_sheet_matrix_without_excel(monkeypatch) -> None:
    with pytest.raises(excel_toolbox.SheetReadError) as no_app:
        _read(_FakeXlwings(app_error=RuntimeError("no excel")), monkeypatch)
    assert no_app.value.reason == "excel_unavailable"

    def missing():
        raise ImportError("xlwings is not installed")

    monkeypatch.setattr(excel_toolbox, "_get_xlwings", missing)
    with pytest.raises(excel_toolbox.SheetReadError) as no_module:
        excel_toolbox.read_sheet_matrix(Path("C:/x/a.xlsx"), max_rows=10, max_cols=10)
    assert no_module.value.reason == "excel_unavailable"


# ── 帧与父进程通道 ──────────────────────────────────────────────────


def test_frames_roundtrip_and_reject_garbage() -> None:
    frames = [{"type": "hello", "pid": 1}, {"type": "data", "matrix": [["甲", 1.5, None]]}]
    raw = b"".join(reader.encode_frame(frame) for frame in frames)
    assert reader.decode_frames(raw) == frames
    for broken in (raw[:-3], raw + b"\x00\x00", b"plain text noise\n" + raw, reader._HEADER.pack(4) + b"[1]x"):
        with pytest.raises(reader.ExcelReadError) as caught:
            reader.decode_frames(broken)
        assert caught.value.reason == "worker_protocol_error"


_FAKE_CHILD = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from services import sign_daily_excel_reader as reader

mode, excel_pid = sys.argv[2], int(sys.argv[3])
identity = reader._process_identity(excel_pid) if excel_pid else None
hello = {"type": "hello", "pid": os.getpid(), "excelPid": excel_pid, "excelCreated": identity[1] if identity else 0}
meta = {"type": "meta", "rows": 2, "cols": 2}
data = {"type": "data", "matrix": [["a", "b"], ["SECRET", 2.0]]}

def emit(*frames, raw=b""):
    os.write(1, b"".join(reader.encode_frame(f) for f in frames) + raw)

if mode == "ok":
    emit(hello, meta, data)
elif mode == "truncated":
    payload = b"".join(reader.encode_frame(f) for f in (hello, meta, data))
    os.write(1, payload[:-5])
elif mode == "noise":
    os.write(1, b"some library printed this\n")
    emit(hello, meta, data)
elif mode == "out_of_order":
    emit(hello, data, meta)
elif mode == "no_data":
    emit(hello, meta)
elif mode == "nothing":
    pass
elif mode == "error":
    emit(hello, {"type": "error", "reason": "has_formula"})
elif mode == "error_before_hello":
    emit({"type": "error", "reason": "excel_unavailable"})
elif mode == "bad_reason":
    emit(hello, {"type": "error", "reason": "SECRET leaked text"})
elif mode == "bad_cell":
    emit(hello, meta, {"type": "data", "matrix": [["a", "b"], ["c", True]]})
elif mode == "shape":
    emit(hello, meta, {"type": "data", "matrix": [["a", "b"]]})
elif mode == "overflow":
    emit(hello)
    os.write(1, b"x" * 200000)
elif mode == "sleep":
    emit(hello)
    time.sleep(120)
'''


@pytest.fixture()
def fake_child(tmp_path, monkeypatch):
    script = tmp_path / "fake_child.py"
    script.write_text(_FAKE_CHILD, encoding="utf-8")
    target = tmp_path / "book.xlsx"
    target.write_bytes(b"not read by the fake child")
    spawned: list[list[str]] = []

    def run(mode: str, *, excel_pid: int = 0, **kwargs):
        def command(path, max_rows, max_cols):
            argv = [sys.executable, str(script), str(REPO), mode, str(excel_pid)]
            spawned.append(argv)
            return argv

        monkeypatch.setattr(reader, "_child_command", command)
        kwargs.setdefault("timeout", 30)
        return reader.read_via_excel(target, max_rows=10, max_cols=10, **kwargs)

    run.spawned = spawned  # type: ignore[attr-defined]
    run.target = target  # type: ignore[attr-defined]
    return run


def test_reader_returns_matrix_from_child(fake_child) -> None:
    assert fake_child("ok") == [["a", "b"], ["SECRET", 2.0]]


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("truncated", "worker_protocol_error"),
        ("noise", "worker_protocol_error"),
        ("out_of_order", "worker_protocol_error"),
        ("no_data", "worker_protocol_error"),
        ("nothing", "worker_protocol_error"),
        ("bad_reason", "worker_protocol_error"),
        ("bad_cell", "worker_protocol_error"),
        ("shape", "worker_protocol_error"),
        ("error", "has_formula"),
        ("error_before_hello", "excel_unavailable"),
    ],
)
def test_reader_maps_child_failures_to_closed_reasons(fake_child, mode, reason) -> None:
    with pytest.raises(reader.ExcelReadError) as caught:
        fake_child(mode)
    assert caught.value.reason == reason
    assert reason in reader.READ_REASONS
    assert "SECRET" not in str(caught.value)


def test_reader_enforces_byte_limit(fake_child) -> None:
    with pytest.raises(reader.ExcelReadError) as caught:
        fake_child("overflow", max_bytes=4096)
    assert caught.value.reason == "worker_protocol_error"


def test_reader_is_single_flight(fake_child) -> None:
    assert reader._LOCK.acquire(blocking=False)
    try:
        with pytest.raises(reader.ExcelReadError) as caught:
            fake_child("ok")
    finally:
        reader._LOCK.release()
    assert caught.value.reason == "busy"
    assert fake_child.spawned == []  # 占用时不拉子进程
    assert fake_child("ok")  # 释放后可用


@pytest.mark.parametrize("name", ["book.xlsm", "book.xls", "book.txt", "missing.xlsx"])
def test_reader_rejects_paths_before_spawning(tmp_path, monkeypatch, name) -> None:
    calls: list = []
    monkeypatch.setattr(reader.subprocess, "Popen", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError()))
    if not name.startswith("missing"):
        (tmp_path / name).write_bytes(b"x")
    candidates = [tmp_path / name, Path("relative") / "book.xlsx", "\\\\server\\share\\book.xlsx", tmp_path]
    for candidate in candidates:
        with pytest.raises(reader.ExcelReadError) as caught:
            reader.read_via_excel(candidate, max_rows=10, max_cols=10)
        assert caught.value.reason == "path_rejected"
    assert calls == []


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_identity(pid: int) -> tuple[str, int]:
    for _ in range(50):
        identity = reader._process_identity(pid)
        if identity is not None:
            return identity
        time.sleep(0.1)
    raise AssertionError("process identity not available")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 进程信息")
def test_terminate_requires_pid_image_and_creation_time() -> None:
    proc = _sleeper()
    try:
        image, created = _wait_identity(proc.pid)
        assert reader.terminate_process_if_same(proc.pid, "EXCEL.EXE", created) is False  # 映像名不对
        assert reader.terminate_process_if_same(proc.pid, image, created + 1) is False  # 创建时间不对
        assert reader.terminate_process_if_same(proc.pid, image, 0) is False
        assert proc.poll() is None  # 三项不全对：没有被动
        assert reader.terminate_process_if_same(proc.pid, image, created) is True
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 进程信息")
def test_timeout_kills_worker_and_its_excel_but_not_the_users(fake_child, monkeypatch) -> None:
    """子进程睡死：报 timeout，子进程与它登记的「Excel」都不存活，用户原有的那个存活。"""
    owned, users = _sleeper(), _sleeper()
    try:
        image, _ = _wait_identity(owned.pid)
        _wait_identity(users.pid)
        monkeypatch.setattr(reader, "_EXCEL_IMAGE", image)  # 用同名的替身进程扮演 Excel
        started = time.monotonic()
        with pytest.raises(reader.ExcelReadError) as caught:
            fake_child("sleep", excel_pid=owned.pid, timeout=3)
        assert caught.value.reason == "timeout"
        assert time.monotonic() - started < 40
        owned.wait(timeout=10)  # 登记过的「Excel」被结束
        assert users.poll() is None  # 没登记的那个不受影响
    finally:
        for proc in (owned, users):
            if proc.poll() is None:
                proc.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 进程信息")
def test_leftover_excel_is_cleaned_after_success(fake_child, monkeypatch) -> None:
    owned = _sleeper()
    try:
        image, _ = _wait_identity(owned.pid)
        monkeypatch.setattr(reader, "_EXCEL_IMAGE", image)
        assert fake_child("ok", excel_pid=owned.pid)
        owned.wait(timeout=10)
    finally:
        if owned.poll() is None:
            owned.kill()


def test_child_command_targets_this_program() -> None:
    command = reader._child_command(Path("C:/data/a.xlsx"), 5001, 67)
    assert command[0] == sys.executable
    assert command[-4:] == [reader.CHILD_FLAG, str(Path("C:/data/a.xlsx")), "5001", "67"]
    webui = (REPO / "webui.py").read_text(encoding="utf-8")
    assert '"--sign-daily-read-child"' in webui
    spec = (REPO / "VSE-WebUI.spec").read_text(encoding="utf-8")
    assert "services.sign_daily_excel_reader" in spec


# ── 开关与规范化（plugins/sign_daily/excel_proxy.py）────────────────


def _proxy():
    return sys.modules["vse_plugins.sign_daily.excel_proxy"]


def _importer():
    return sys.modules["vse_plugins.sign_daily.importer"]


def _container(payload: bytes = b"PK\x03\x04 not really") -> bytes:
    return ENCRYPTED_CONTAINER_SIGNATURES[0] + bytes(1024 - SNIFF_BYTES) + payload


def test_status_follows_user_switch_only(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """2026-11-17 起只有用户开关一层：不再需要部署授权文件。"""
    proxy = _proxy()
    monkeypatch.setattr(proxy, "excel_available", lambda: True)
    assert proxy.status(False)["status"] == "disabled"
    assert proxy.status(None)["status"] == "disabled"
    assert proxy.status("yes")["status"] == "disabled"  # 只认布尔 true
    assert proxy.status(True) == {"status": "ok", "text": proxy.STATUS_TEXT["ok"], "enabled": True}
    assert proxy.ready({"excelProxyEnabled": True}) is True
    assert not hasattr(proxy, "deploy_authorization")

    monkeypatch.setattr(proxy, "excel_available", lambda: False)
    assert proxy.status(True)["status"] == "excel_unavailable"
    assert proxy.ready({"excelProxyEnabled": True}) is False


def _excel_matrix(rows=None, header=None) -> list[list[object]]:
    """Excel 取回值的样子：文本是 str、空格子是 None、计数列是 float。"""
    header = list(HEADERS if header is None else header)
    out: list[list[object]] = [header]
    for row in (_rows() if rows is None else rows):
        cells: list[object] = []
        for name in HEADERS:
            value = row.get(name)
            if value is None or value == "":
                cells.append(None)
            elif name in COUNT_NAMES:
                cells.append(float(value))
            else:
                cells.append(str(value))
        out.append(cells)
    return out


def test_to_canonical_follows_the_column_whitelist(client) -> None:  # type: ignore[no-untyped-def]
    proxy = _proxy()
    headers = list(HEADERS)
    count, ratio, text = headers.index("应签人数"), headers.index("签署率"), headers.index("流水单号")

    def run(index: int, value: object):
        matrix = _excel_matrix()
        matrix[1][index] = value
        return proxy.to_canonical(matrix, headers)[1][index]

    assert run(count, 3.0) == "3"  # 整数字面量
    assert run(count, 0.0) == "0"
    assert run(count, None) is None
    assert run(ratio, 0.5) == "0.5"  # repr(float)，不转百分比
    assert run(ratio, 1 / 3) == repr(1 / 3)  # 不四舍五入
    assert run(ratio, "50.00%") == "50.00%"
    assert run(text, "S1") == "S1"
    for index, value, reason in (
        (count, 2.5, "unexpected_numeric"),
        (count, -1.0, "unexpected_numeric"),
        (count, 1e9, "unexpected_numeric"),
        (text, 12345678901234567890.0, "unexpected_numeric"),  # 长编号丢精度
        (text, 45000.0, "unexpected_numeric"),  # 日期序列号
        (text, True, "cell_error"),
        (text, -2146826281, "cell_error"),
        (ratio, float("inf"), "cell_error"),
    ):
        with pytest.raises(proxy.CanonicalError) as caught:
            run(index, value)
        assert caught.value.reason == reason and caught.value.col_index == index
        assert str(value) not in str(caught.value)
    assert proxy.to_canonical([], headers) == []


# ── 插件路由 ────────────────────────────────────────────────────────


@pytest.fixture()
def proxy_env(client, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """扫描目录 + 可控的用户开关 + 被替换的 read_via_excel。"""
    _, http, db, _ = client
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    proxy = _proxy()
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    state = {"calls": [], "result": _excel_matrix(), "hook": None}
    monkeypatch.setattr(proxy, "excel_available", lambda: True)

    def fake_read(path, *, max_rows, max_cols, **kwargs):
        state["calls"].append((Path(path), max_rows, max_cols))
        if state["hook"] is not None:
            state["hook"](Path(path))
        if isinstance(state["result"], Exception):
            raise state["result"]
        return state["result"]

    monkeypatch.setattr(reader, "read_via_excel", fake_read)

    def enable(value: bool = True) -> None:
        _ok(http.post(f"{API}/config", json={"excelProxyEnabled": value}))

    def scan():
        return _ok(http.post(f"{API}/import-scan", json={"dir": str(tmp_path)}))

    def generate(scanned, **form):
        selected = scanned["selected"]
        return http.post(
            f"{API}/import-form",
            data={"scanDirId": scanned["dirId"], "scanName": selected["name"], "scanToken": selected["token"],
                  "dataDate": "2026-11-06", "projects": '["F610M"]', **form},
            content_type="multipart/form-data",
        )

    encrypted = tmp_path / "加密导出.xlsx"
    encrypted.write_bytes(_container())
    return type("Env", (), {
        "http": http, "db": db, "state": state, "enable": staticmethod(enable), "scan": staticmethod(scan),
        "generate": staticmethod(generate), "encrypted": encrypted, "dir": tmp_path,
    })


def test_state_reports_proxy_status_and_config_validates(proxy_env) -> None:
    http = proxy_env.http
    assert _ok(http.get(f"{API}/state"))["excelProxy"]["status"] == "disabled"
    proxy_env.enable()
    status = _ok(http.get(f"{API}/state"))["excelProxy"]
    assert status["status"] == "ok" and status["enabled"] is True and "authorized" not in status
    assert http.post(f"{API}/config", json={"excelProxyEnabled": "yes"}).status_code == 400


def test_switch_off_means_no_excel(proxy_env) -> None:
    """开关关闭：扫描照旧停在加密文件上，且根本不拉子进程。"""
    proxy_env.enable(False)
    scanned = proxy_env.scan()
    assert scanned["selected"] is None
    assert scanned["reason"] == "E_ENCRYPTED_WORKBOOK"
    assert proxy_env.state["calls"] == []


def test_encrypted_xlsx_in_scan_dir_generates_via_excel(proxy_env, tmp_path_factory) -> None:
    http, db = proxy_env.http, proxy_env.db
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    proxy_env.enable()  # 开关本身是一条配置；之后的导入不得再写库
    before = _snapshot_counts(db)

    scanned = proxy_env.scan()
    assert scanned["selected"]["name"] == "加密导出.xlsx"
    assert scanned["selected"]["viaExcel"] is True
    assert proxy_env.state["calls"] == []  # 扫描阶段不启动 Excel

    report = _ok(proxy_env.generate(scanned))
    assert len(proxy_env.state["calls"]) == 1
    path, max_rows, max_cols = proxy_env.state["calls"][0]
    assert path == proxy_env.encrypted.resolve() and max_rows == 5001 and max_cols == len(HEADERS) + 20
    assert report["mode"] == "manual"
    assert report["importMeta"]["sourceFormat"] == "xlsx-excel"
    assert "Excel" in report["importMeta"]["note"]
    assert report["importMeta"]["rowCount"] == len(_rows())
    assert report["delta"] is None and report["snapshotSaved"] is False
    assert _snapshot_counts(db) == before  # 零写库

    # 与同一份数据的明文 xlsx 上传结果逐字段相同（只归一来源声明）。
    plain_dir = tmp_path_factory.mktemp("plain")
    matrix = [list(HEADERS)] + [[row.get(key) for key in HEADERS] for row in _rows()]
    plain = write_workbook(plain_dir / "plain.xlsx", matrix[0], matrix[1:], sheet_name="Sheet1")
    plain_report = _ok(http.post(
        f"{API}/import-form",
        data={"file": (io.BytesIO(plain.read_bytes()), "plain.xlsx"), "dataDate": "2026-11-06",
              "projects": '["F610M"]'},
        content_type="multipart/form-data",
    ))

    def comparable(payload: dict, name: str) -> dict:
        out = dict(payload)
        meta = dict(out.pop("importMeta"))
        for key in ("sourceName", "sha256", "sourceFormat", "note", "banner"):
            meta.pop(key, None)
        out["importMeta"] = meta
        for key in ("html", "text"):
            assert name in out[key]
            out[key] = out[key].replace(name, "<SOURCE>")
        return out

    assert comparable(report, "加密导出.xlsx") == comparable(plain_report, "plain.xlsx")
    # 正文指纹不含来源声明：两条路必须相同（真机验收靠它核对）。
    digest = report["importMeta"]["reportDigest"]
    assert len(digest) == 12 and digest == plain_report["importMeta"]["reportDigest"]


def test_switch_turned_off_after_scan_blocks_generation(proxy_env) -> None:
    proxy_env.enable()
    scanned = proxy_env.scan()
    proxy_env.enable(False)
    response = proxy_env.generate(scanned)
    assert response.status_code == 422
    assert response.get_json()["error"]["type"] == "E_ENCRYPTED_WORKBOOK"
    assert proxy_env.state["calls"] == []


def test_file_replaced_while_excel_reads_is_discarded(proxy_env) -> None:
    proxy_env.enable()
    scanned = proxy_env.scan()

    def tamper(path: Path) -> None:
        info = path.stat()
        data = bytearray(path.read_bytes())
        data[-1] ^= 0x01
        path.write_bytes(bytes(data))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))  # 同大小、复原 mtime

    proxy_env.state["hook"] = tamper
    response = proxy_env.generate(scanned)
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "E_SCAN_STALE"


@pytest.mark.parametrize("reason", sorted(reader.READ_REASONS))
def test_proxy_failures_fall_back_to_phase0_message(proxy_env, caplog, reason) -> None:
    """代读没成功：落回「受终端加密」那条文案与出口，只多一个闭集 reason。"""
    importer = _importer()
    proxy_env.enable()
    scanned = proxy_env.scan()
    before = _snapshot_counts(proxy_env.db)
    proxy_env.state["result"] = reader.ExcelReadError(reason)
    caplog.set_level(logging.DEBUG)

    response = proxy_env.generate(scanned)

    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["type"] == "E_ENCRYPTED_WORKBOOK"
    assert error["message"] == importer.ENCRYPTED_TEXT
    assert error["diagnostic"] == {"reason": reason}
    assert _snapshot_counts(proxy_env.db) == before


def test_rejected_values_never_leak(proxy_env, caplog) -> None:
    importer = _importer()
    proxy_env.enable()
    scanned = proxy_env.scan()
    caplog.set_level(logging.DEBUG)
    text_col = list(HEADERS).index("流水单号")

    def matrix_with(index: int, value: object) -> list[list[object]]:
        rows = [dict(row, 零件名称=SENTINEL, 申请人=SENTINEL) for row in _rows()]
        matrix = _excel_matrix(rows)
        matrix[2][index] = value
        return matrix

    proxy_env.state["result"] = matrix_with(text_col, 20261106001.0)
    response = proxy_env.generate(scanned)
    error = response.get_json()["error"]
    assert response.status_code == 422 and error["type"] == "E_ENCRYPTED_WORKBOOK"
    assert error["message"] == importer.ENCRYPTED_TEXT
    assert error["diagnostic"] == {"reason": "unexpected_numeric", "colIndex": text_col}
    assert SENTINEL not in response.get_data(as_text=True)

    drifted = _excel_matrix([dict(row, 零件名称=SENTINEL) for row in _rows()],
                            header=[HEADERS[0]] + [HEADERS[1] + SENTINEL] + list(HEADERS[2:]))
    proxy_env.state["result"] = drifted
    response = proxy_env.generate(scanned)
    error = response.get_json()["error"]
    assert response.status_code == 422 and error["type"] == "E_HEADER_MISMATCH"
    assert error["diagnostic"] == {"reason": "schema_mismatch", "colIndex": 1}
    assert SENTINEL not in response.get_data(as_text=True)

    extra = _excel_matrix()
    extra[1] = extra[1] + [SENTINEL]
    proxy_env.state["result"] = extra
    response = proxy_env.generate(scanned)
    assert response.get_json()["error"]["type"] == "E_HEADER_MISMATCH"
    assert SENTINEL not in response.get_data(as_text=True)
    assert SENTINEL not in caplog.text


def test_upload_and_txt_never_use_excel(proxy_env) -> None:
    """上传来的密文、以及加密的 .txt 都不走代读。"""
    proxy_env.enable()
    response = proxy_env.http.post(
        f"{API}/import-form",
        data={"file": (io.BytesIO(_container()), "upload.xlsx"), "dataDate": "2026-11-06"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["diagnostic"]["reason"] == "encrypted_container"

    newer = proxy_env.dir / "更新的.txt"
    newer.write_bytes(_container())
    stamp = time.time() + 5
    os.utime(newer, (stamp, stamp))
    scanned = proxy_env.scan()
    assert scanned["selected"] is None and scanned["reason"] == "E_ENCRYPTED_WORKBOOK"
    assert proxy_env.state["calls"] == []


def test_plaintext_xlsx_in_scan_dir_still_uses_zip_reader(proxy_env) -> None:
    """只有嗅探为终端加密容器才走代读：明文 xlsx 照旧由程序自己读。"""
    proxy_env.enable()
    matrix = [list(HEADERS)] + [[row.get(key) for key in HEADERS] for row in _rows()]
    plain = write_workbook(proxy_env.dir / "明文.xlsx", matrix[0], matrix[1:], sheet_name="Sheet1")
    stamp = time.time() + 5
    os.utime(plain, (stamp, stamp))
    scanned = proxy_env.scan()
    assert scanned["selected"]["name"] == "明文.xlsx" and scanned["selected"]["viaExcel"] is False
    report = _ok(proxy_env.generate(scanned))
    assert report["importMeta"]["sourceFormat"] == "xlsx"
    assert proxy_env.state["calls"] == []


def test_concurrent_second_request_is_busy(proxy_env) -> None:
    """真实的单并发锁：第一份还在读时，第二份立刻得到 busy（不排队、不拉第二个 Excel）。"""
    importer = _importer()
    release, entered = threading.Event(), threading.Event()
    proxy_env.enable()
    scanned = proxy_env.scan()

    def slow_read(path, *, max_rows, max_cols, **kwargs):
        if not reader._LOCK.acquire(blocking=False):
            raise reader.ExcelReadError("busy")
        try:
            entered.set()
            release.wait(timeout=20)
            return _excel_matrix()
        finally:
            reader._LOCK.release()

    reader.read_via_excel = slow_read  # proxy_env 的 monkeypatch 会在收尾时还原
    results: dict[str, object] = {}

    def first() -> None:
        results["first"] = proxy_env.generate(scanned).status_code

    worker = threading.Thread(target=first)
    worker.start()
    assert entered.wait(timeout=20)
    second = proxy_env.generate(scanned)
    release.set()
    worker.join(timeout=30)

    assert second.status_code == 422
    assert second.get_json()["error"] == {
        **second.get_json()["error"], "type": "E_ENCRYPTED_WORKBOOK",
        "message": importer.ENCRYPTED_TEXT, "diagnostic": {"reason": "busy"},
    }
    assert results["first"] == 200


def test_frontend_has_the_switch_and_reason_notes() -> None:
    js = (REPO / "plugins" / "sign_daily" / "static" / "report.js").read_text(encoding="utf-8")
    assert "excelProxyEnabled" in js and "viaExcel" in js
    for reason in reader.READ_REASONS + ("unexpected_numeric",):
        assert f"{reason}:" in js, reason


# ── 扫描目录可自查 / 上传入口的指引（2026-11-12 真机反馈）──────────────


def test_scan_and_state_show_full_directory_path(proxy_env) -> None:
    """数据根随部署形态变化：页面必须拿得到完整路径，不能只有 basename。"""
    http = proxy_env.http
    import_dir = Path(_ok(http.get(f"{API}/state"))["importDir"])
    assert import_dir.is_absolute()
    # 目录名是插件 id（连字符），不是源码包名。
    assert import_dir.parts[-3:] == ("plugins", "sign-daily", "import")

    scanned = _ok(http.post(f"{API}/import-scan", json={}))  # 默认目录：空
    assert scanned["reason"] == "E_NO_FILE" and scanned["selected"] is None
    assert Path(scanned["dirPath"]) == import_dir
    assert scanned["dirPath"] in scanned["rootPaths"]

    explicit = proxy_env.scan()
    assert Path(explicit["dirPath"]) == proxy_env.dir.resolve()


def test_uploading_encrypted_xlsx_points_to_scan_dir_when_proxy_ready(proxy_env) -> None:
    http = proxy_env.http
    importer = sys.modules["vse_plugins.sign_daily.importer"]

    def upload():
        return http.post(
            f"{API}/import-form",
            data={"file": (io.BytesIO(proxy_env.encrypted.read_bytes()), "加密导出.xlsx"),
                  "dataDate": "2026-11-06", "projects": '["F610M"]'},
            content_type="multipart/form-data",
        )

    off = upload()  # 代读没开：页面给出两条出路（另存为 txt / 勾选代读后放进扫描目录）
    assert off.status_code == 422 and off.get_json()["error"]["type"] == "E_ENCRYPTED_WORKBOOK"
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    assert off.get_json()["error"]["message"] == backend.ENCRYPTED_PAGE_TEXT

    proxy_env.enable()
    on = upload()
    error = on.get_json()["error"]
    assert on.status_code == 422 and error["type"] == "E_ENCRYPTED_WORKBOOK"
    assert error["message"] == importer.ENCRYPTED_UPLOAD_TEXT and "一键生成" not in error["message"]
    assert proxy_env.state["calls"] == []  # 上传入口不拉 Excel
