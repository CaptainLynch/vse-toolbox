# -*- coding: utf-8 -*-
"""签署日报「Excel 代读」：开关、可用性与取回值的规范化（第 1 期，2026-11-12）。

公司终端加密的 xlsx 本进程读不到内容；开启后由本机 Excel（受信进程）只读打开，
值经管道回到内存再生成日报。**不解密、不剥文件头、不产生明文文件。**

两层开关都打开才会真的去拉 Excel：

1. **部署授权**（默认关）：运行目录下的 ``deploy_flags.json`` 写明
   ``{"signDailyExcelProxy": {"authorized": true, "authRef": "<IT 授权记录编号>"}}``。
   这在 DLP 视角等于「借受信进程向本程序输出内容」，必须与 IT 的授权记录绑定；
   没有文件、文件读不出来（例如它自己被终端容器化了）、缺授权编号 → 一律视为未授权。
2. **用户开关**（默认关）：插件配置 ``excelProxyEnabled``。

状态枚举（页面与测试共用）：``ok`` / ``disabled`` / ``not_authorized`` / ``excel_unavailable``；
实际读取失败的原因见 ``services.sign_daily_excel_reader.READ_REASONS``。

规范化（``to_canonical``）是列类型白名单，其余一律拒绝（fail-closed）：

| 取回的值 | 处理 |
|---|---|
| 表头行 | 交给官方契约的逐字校验（不 strip、不做 Unicode 归一） |
| ``None`` / ``str`` | 原样 |
| 计数列（应签/已签/未签人数）的 float | 有限、是整数、≥0、不超上限 → 整数字面量 |
| 比率列（签署率）的 float | ``repr(float)``，不四舍五入、不转百分比 |
| 其余列出现 float | 拒绝 ``unexpected_numeric``（防长编号丢精度、日期序列号被当成数字） |
| bool / int（Excel 错误码）等 | 拒绝 ``cell_error`` |
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.deploy_manifest import deploy_root
from services.xlsx_preview import (
    FILE_KIND_ENCRYPTED_CONTAINER,
    SNIFF_BYTES,
    sniff_file_kind,
)

FLAGS_NAME = "deploy_flags.json"
FLAG_KEY = "signDailyExcelProxy"
_FLAGS_MAX_BYTES = 64 * 1024

STATUS_OK = "ok"
STATUS_DISABLED = "disabled"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_EXCEL_UNAVAILABLE = "excel_unavailable"

REASON_UNEXPECTED_NUMERIC = "unexpected_numeric"
REASON_CELL_ERROR = "cell_error"

#: 允许出现数字的列：计数列必须是非负整数，比率列保留原始浮点。
COUNT_COLUMNS = ("应签人数", "已签人数", "未签人数")
RATIO_COLUMNS = ("签署率",)
_COUNT_LIMIT = 1_000_000

STATUS_TEXT = {
    STATUS_OK: "已开启：加密的 xlsx 放进扫描目录后，由本机 Excel 代读。是否可用以实际读取结果为准。",
    STATUS_DISABLED: "未开启。",
    STATUS_NOT_AUTHORIZED: "本机部署没有启用授权，无法开启（需要部署方按 IT 授权记录放置授权文件）。",
    STATUS_EXCEL_UNAVAILABLE: "这台电脑上没有可用的 Excel 组件，无法代读。",
}


class CanonicalError(ValueError):
    """取回的值不符合列类型白名单；reason 是闭集词，消息里不带单元格内容。"""

    def __init__(self, reason: str, *, col_index: int | None = None) -> None:
        super().__init__(f"excel value rejected: {reason}")
        self.reason = reason
        self.col_index = col_index


def flags_path() -> Path:
    return deploy_root() / FLAGS_NAME


def deploy_authorization(path: Path | None = None) -> dict[str, Any]:
    """读部署授权文件；任何读不出/不完整的情况都返回 ``authorized=False``。

    ``state``：absent（没有文件）/ containerized（文件被终端容器化，本进程读不到）/
    invalid（不是合法 JSON 或缺字段）/ ok。
    """
    target = Path(path) if path is not None else flags_path()
    denied = {"authorized": False, "authRef": ""}
    try:
        if not target.is_file():
            return {**denied, "state": "absent"}
        with target.open("rb") as handle:
            raw = handle.read(_FLAGS_MAX_BYTES + 1)
    except OSError:
        return {**denied, "state": "invalid"}
    if len(raw) > _FLAGS_MAX_BYTES:
        return {**denied, "state": "invalid"}
    if sniff_file_kind(raw[:SNIFF_BYTES], len(raw)) == FILE_KIND_ENCRYPTED_CONTAINER:
        return {**denied, "state": "containerized"}
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return {**denied, "state": "invalid"}
    entry = payload.get(FLAG_KEY) if isinstance(payload, Mapping) else None
    if not isinstance(entry, Mapping):
        return {**denied, "state": "invalid"}
    auth_ref = entry.get("authRef")
    if entry.get("authorized") is not True or not isinstance(auth_ref, str) or not auth_ref.strip():
        return {**denied, "state": "invalid"}
    return {"authorized": True, "authRef": auth_ref.strip()[:200], "state": "ok"}


def excel_available() -> bool:
    """本机是否具备代读的前提（Windows + 打进包里的 xlwings）；不启动 Excel。"""
    if sys.platform != "win32":
        return False
    try:
        return importlib.util.find_spec("xlwings") is not None
    except (ImportError, ValueError):
        return False


def status(user_enabled: object) -> dict[str, Any]:
    """页面用的开关状态；只有 ``status == "ok"`` 才会真的去拉 Excel。"""
    authorization = deploy_authorization()
    if not authorization["authorized"]:
        code = STATUS_NOT_AUTHORIZED
    elif not excel_available():
        code = STATUS_EXCEL_UNAVAILABLE
    elif user_enabled is not True:
        code = STATUS_DISABLED
    else:
        code = STATUS_OK
    return {
        "status": code,
        "text": STATUS_TEXT[code],
        "authorized": bool(authorization["authorized"]),
        "authState": authorization["state"],
        "enabled": user_enabled is True,
    }


def ready(config: Mapping[str, Any]) -> bool:
    return status(config.get("excelProxyEnabled"))["status"] == STATUS_OK


def to_canonical(matrix: Sequence[Sequence[Any]], headers: Sequence[str]) -> list[list[Any]]:
    """把 Excel 取回的值矩阵规范成与 xlsx 读取路同形的矩阵（表头行原样留给契约校验）。"""
    if not matrix:
        return []
    counts = {index for index, name in enumerate(headers) if name in COUNT_COLUMNS}
    ratios = {index for index, name in enumerate(headers) if name in RATIO_COLUMNS}
    out: list[list[Any]] = [list(matrix[0])]
    for row in matrix[1:]:
        clean: list[Any] = []
        for index, value in enumerate(row):
            if value is None or isinstance(value, str):
                clean.append(value)
                continue
            if isinstance(value, bool) or not isinstance(value, float) or not math.isfinite(value):
                raise CanonicalError(REASON_CELL_ERROR, col_index=index)
            if index in counts:
                if value < 0 or value > _COUNT_LIMIT or not value.is_integer():
                    raise CanonicalError(REASON_UNEXPECTED_NUMERIC, col_index=index)
                clean.append(str(int(value)))
            elif index in ratios:
                clean.append(repr(value))
            else:
                raise CanonicalError(REASON_UNEXPECTED_NUMERIC, col_index=index)
        out.append(clean)
    return out


__all__ = [
    "COUNT_COLUMNS",
    "CanonicalError",
    "FLAGS_NAME",
    "FLAG_KEY",
    "RATIO_COLUMNS",
    "STATUS_DISABLED",
    "STATUS_EXCEL_UNAVAILABLE",
    "STATUS_NOT_AUTHORIZED",
    "STATUS_OK",
    "deploy_authorization",
    "excel_available",
    "flags_path",
    "ready",
    "status",
    "to_canonical",
]
