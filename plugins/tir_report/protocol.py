# -*- coding: utf-8 -*-
"""FineReport 10 protocol for ``tdc/TIR/TIR数据简表.cpt`` (pure functions, no I/O).

协议事实来自 2026-10-09 的帆软会话 HAR（只按结构分析，未入库），见
``docs/TIR_REPORT_PLUGIN_DESIGN_20261009.md`` §2：

- ``__parameters__`` = ``encodeURIComponent(cjkEncode(JSON.stringify(参数)))``；cjkEncode 把码点 ≥ 0x80
  以及 ``[``、``]`` 写成 ``[小写hex]``。浏览器提交全部键（含 ``LABEL*`` 标签键与空值），这里照抄键集与顺序。
- 多选值以 ``','`` 连成一个字符串；空的多选是 ``[]``。
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote, urlencode

BASE_PATH = "/webroot/decision"
ENTRY_ID = "3770a19c-4f81-4c1b-9a94-55dd63c6d58e"
REPORT_PATH = "tdc/TIR/TIR数据简表.cpt"
REPORT_NAME = "TIR数据简表"
DEFAULT_BASE_URL = "https://report.sgmw.com.cn"
DEFAULT_PROJECT = ""  # 留空 = 全部项目（用户 2026-10-09 确认）
DEFAULT_DEPARTMENT = "车体工程"
DEFAULT_START_DATE = "2022-07-11"

#: 样例导出（12 行 × 50 列）的第 1 行；用于校验导出结果与退路重建。
EXPECTED_HEADERS = (
    "申请单号", "序号", "故障报告编号", "责任工程师", "责任科室", "当前节点", "未操作者", "提出人", "提出科室",
    "提出日期", "发放日期", "故障等级", "问题状态", "项目编号", "项目阶段", "试验名称", "故障主题", "零件名称",
    "是否是架构项目", "所属架构平台", "是否是架构件", "一级故障模式", "三级故障模式", "试验规范", "试验地点",
    "故障背景", "车辆编号", "车辆配置", "车辆识别号（VIN）", "变速箱型号", "发动机型号", "发动机号", "电池信息",
    "故障关闭类型", "车辆验证里程（km）", "零件试验里程（km）", "坏路（km）",
    "根本原因（2/6）-计划", "根本原因（2/6）-实际", "长期措施（3/6）-计划", "长期措施（3/6）-实际",
    "措施实施（4/6）-计划", "措施实施（4/6）-实际", "验证开始（5/6）-计划", "验证开始（5/6）-实际",
    "关闭（6/6）-计划", "关闭（6/6）-实际", "试验认证协调员", "责任区域", "责任区域VSE",
)

# (参数键, 默认值)：顺序与浏览器提交一致（HAR 第 33 条）；LABEL* 是报表自带的标签键，原样提交。
_PARAMETER_TEMPLATE: tuple[tuple[str, Any], ...] = (
    ("LABELWTZT", "问题状态"), ("LABELGB6/6SJ", "关闭时间"), ("ZRGCS", ""), ("LABELZRGCS", "责任工程师"),
    ("CLSBH", ""), ("LABELCLSBH", "车辆识别号（VIN）"), ("LABELXM", "项目"), ("XM", ""),
    ("STARTTIME", ""), ("LABELENDTIME", "发放结束日期"), ("ENDTIME", ""), ("LABELKS", "科室"), ("KS", ""),
    ("LABELDJ", "等级"), ("LABELBM", "部门"), ("BM", ""), ("LABELGZBGBH", "故障报告编号"), ("GZBGBH", ""),
    ("LABELLJMC", "零件名称"), ("LJMC", ""), ("LABELSYMC", "试验名称"), ("SYMC", ""), ("LABELGZZT", "故障主题"),
    ("LABELCLPZ", "车辆配置"), ("CLPZ", ""), ("LABELSTARTTIME", "发放开始日期"), ("WTZT", ""), ("GB66SJ", ""),
    ("DJ", ""), ("GZZT", ""), ("LABELTCR", "提出人"), ("LABELTCKS", "提出科室"), ("TCKS", ""), ("XMJD", ""),
    ("LABELXMJD", "项目阶段"), ("LABELFDJXH", "发动机型号"), ("FDJXH", ""), ("LABELGZGBLX", "故障关闭类型"),
    ("GZGBLX", ""), ("TCR", ""), ("LABELSFSJGXM", "是否架构项目"), ("SFSJGXM", []),
    ("LABELSSJGPT", "所属架构平台"), ("SSJGPT", ""),
)
#: 页面可设置的筛选键（插件字段名 -> 报表参数键）。其余键按浏览器默认提交空值。
FILTER_KEYS = {
    "project": "XM", "department": "BM", "section": "KS", "startDate": "STARTTIME", "endDate": "ENDTIME",
    "status": "WTZT", "grade": "DJ", "phase": "XMJD", "closeType": "GZGBLX", "proposer": "TCR",
    "proposerSection": "TCKS", "partName": "LJMC", "testName": "SYMC", "subject": "GZZT", "vehicleConfig": "CLPZ",
    "vin": "CLSBH", "engineModel": "FDJXH", "reportNo": "GZBGBH", "engineer": "ZRGCS",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALUE_LIMIT = 200


class ProtocolError(ValueError):
    """Response or input does not match the FineReport contract this plugin knows."""


# ── 编码 ────────────────────────────────────────────────────────────


def cjk_encode(text: str) -> str:
    """FineReport ``FR.cjkEncode``: code points ≥ 0x80 and ``[``/``]`` become ``[hex]``."""
    out = []
    for ch in text:
        code = ord(ch)
        out.append(f"[{code:x}]" if code >= 0x80 or ch in "[]" else ch)
    return "".join(out)


def cjk_decode(text: str) -> str:
    return re.sub(r"\[([0-9a-fA-F]{1,6})\]", lambda m: chr(int(m.group(1), 16)), text)


def encode_uri_component(text: str) -> str:
    """JavaScript ``encodeURIComponent`` (unreserved marks stay literal)."""
    return quote(text, safe="-_.!~*'()")


def form_body(fields: Sequence[tuple[str, str]]) -> str:
    """``application/x-www-form-urlencoded`` exactly as jQuery would send it."""
    return "&".join(f"{encode_uri_component(k)}={encode_uri_component(v)}" for k, v in fields)


@dataclass(frozen=True)
class ExportFilters:
    project: str = DEFAULT_PROJECT
    department: str = DEFAULT_DEPARTMENT
    section: str = ""
    start_date: str = DEFAULT_START_DATE
    end_date: str = ""

    def as_payload(self) -> dict[str, str]:
        return {"project": self.project, "department": self.department, "section": self.section,
                "startDate": self.start_date, "endDate": self.end_date}

    def cache_key(self) -> str:
        return "|".join((self.project, self.department, self.section, self.start_date, self.end_date))


def _clean_value(value: Any, name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [_clean_value(item, name) for item in value]
        return "','".join(item for item in items if item)
    if not isinstance(value, str):
        raise ProtocolError(f"{name} 必须是文本")
    text = value.strip()
    if len(text) > _VALUE_LIMIT or any(ord(ch) < 32 for ch in text):
        raise ProtocolError(f"{name} 无效")
    return text


def normalize_filters(raw: Mapping[str, Any] | None, *, today: date) -> ExportFilters:
    """Validate page input; end date defaults to ``today``; start ≤ end."""
    raw = raw or {}
    project = _clean_value(raw.get("project", DEFAULT_PROJECT), "项目")
    department = _clean_value(raw.get("department", DEFAULT_DEPARTMENT), "部门")
    section = _clean_value(raw.get("section", ""), "科室")
    start = _clean_value(raw.get("startDate") or DEFAULT_START_DATE, "发放开始日期")
    end = _clean_value(raw.get("endDate") or today.isoformat(), "发放结束日期")
    for label, value in (("发放开始日期", start), ("发放结束日期", end)):
        if not _DATE_RE.match(value):
            raise ProtocolError(f"{label} 必须是 YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ProtocolError(f"{label} 不是有效日期") from exc
    if start > end:
        raise ProtocolError("发放开始日期不能晚于结束日期")
    return ExportFilters(project=project, department=department, section=section, start_date=start, end_date=end)


def build_parameters(filters: ExportFilters, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Full parameter object in browser key order; ``extra`` uses plugin field names (``FILTER_KEYS``)."""
    values: dict[str, Any] = {
        "XM": filters.project, "BM": filters.department, "KS": filters.section,
        "STARTTIME": filters.start_date, "ENDTIME": filters.end_date,
    }
    for field_name, value in (extra or {}).items():
        key = FILTER_KEYS.get(field_name)
        if key is None:
            raise ProtocolError(f"未知筛选项: {field_name}")
        values[key] = _clean_value(value, field_name)
    params: dict[str, Any] = {}
    for key, default in _PARAMETER_TEMPLATE:
        params[key] = values.get(key, default) if not key.startswith("LABEL") else default
    return params


def encode_parameters(params: Mapping[str, Any]) -> str:
    """The ``__parameters__`` form value before form encoding (cjkEncoded JSON)."""
    return cjk_encode(json.dumps(params, ensure_ascii=False, separators=(",", ":")))


def decode_parameters(value: str) -> dict[str, Any]:
    return json.loads(cjk_decode(value))


# ── URL 与请求 ───────────────────────────────────────────────────────


def url(base_url: str, path: str, query: Sequence[tuple[str, str]] | None = None) -> str:
    target = base_url.rstrip("/") + BASE_PATH + path
    if query:
        target += "?" + urlencode(list(query), quote_via=quote)
    return target


def login_body(username: str, encrypted_password: str, *, encrypted: bool) -> str:
    return json.dumps({"username": username, "password": encrypted_password, "validity": -1,
                       "sliderToken": "", "origin": "", "encrypted": encrypted}, ensure_ascii=False)


def entry_access_path(entry_id: str = ENTRY_ID) -> str:
    return f"/v10/entry/access/{entry_id}"


def parameters_query() -> list[tuple[str, str]]:
    return [("op", "fr_dialog"), ("cmd", "parameters_d")]


def parameters_form(params: Mapping[str, Any], timestamp_ms: int) -> str:
    return form_body([("__parameters__", encode_parameters(params)), ("_", str(timestamp_ms))])


def read_content_query(page: int, timestamp_ms: int) -> list[tuple[str, str]]:
    return [("_", str(timestamp_ms)), ("__boxModel__", "true"), ("op", "fr_write"), ("cmd", "read_w_content"),
            ("reportIndex", "0"), ("browserWidth", "918"), ("__cutpage__", ""), ("pn", str(page)),
            ("__webpage__", "true"), ("_paperWidth", "918"), ("_paperHeight", "378"), ("__fit__", "false")]


def export_query(session_id: str) -> list[tuple[str, str]]:
    """FineReport 10 原样导出 Excel 的下载端点（浏览器导航，HAR 未捕获，见方案 R2）。"""
    return [("op", "export"), ("format", "excel"), ("extype", "simple"), ("sessionID", session_id)]


def export_polling_form(timestamp_ms: int) -> str:
    return form_body([("op", "export"), ("cmd", "export_polling"), ("type", "excel"), ("data", str(timestamp_ms))])


# ── 响应解析 ─────────────────────────────────────────────────────────

_SESSION_PATTERNS = (
    re.compile(r"FR\.SessionMgr\.register\(\s*['\"]([0-9A-Za-z-]{6,64})['\"]"),
    re.compile(r"\bcurrentSessionID\s*[:=]\s*['\"]([0-9A-Za-z-]{6,64})['\"]"),
    re.compile(r"\bsessionID\s*[:=]\s*['\"]([0-9A-Za-z-]{6,64})['\"]"),
    re.compile(r"[?&]sessionID=([0-9A-Za-z-]{6,64})"),
)
_PEM_RE = re.compile(r"-----BEGIN PUBLIC KEY-----[A-Za-z0-9+/=\s\\n]+-----END PUBLIC KEY-----")
_DER_KEY_RE = re.compile(r"['\"](MI[GI][A-Za-z0-9+/]{100,}={0,2})['\"]")


def parse_session_id(page_html: str) -> str:
    for pattern in _SESSION_PATTERNS:
        match = pattern.search(page_html or "")
        if match:
            return match.group(1)
    raise ProtocolError("报表页面里找不到 sessionID")


def find_public_key(page_html: str) -> bytes | None:
    """RSA public key (PEM bytes) embedded in the login/decision page, or ``None``."""
    text = page_html or ""
    match = _PEM_RE.search(text)
    if match:
        return match.group(0).replace("\\n", "\n").encode("ascii")
    match = _DER_KEY_RE.search(text)
    if match:
        body = match.group(1)
        try:
            base64.b64decode(body, validate=True)
        except (ValueError, base64.binascii.Error):
            return None
        lines = [body[i:i + 64] for i in range(0, len(body), 64)]
        return ("-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n").encode("ascii")
    return None


def encrypt_password(password: str, public_key_pem: bytes) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, rsa.RSAPublicKey):
        raise ProtocolError("登录页公钥不是 RSA")
    return base64.b64encode(key.encrypt(password.encode("utf-8"), padding.PKCS1v15())).decode("ascii")


def parse_access_token(payload: Any) -> str:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    token = data.get("accessToken") if isinstance(data, Mapping) else None
    if not isinstance(token, str) or not token:
        raise ProtocolError("登录响应里没有 accessToken")
    return token


def login_error_code(payload: Any) -> str:
    """FineReport 登录失败时返回 ``{errorCode, errorMsg}``；只取码，不取可能回显账号的消息。"""
    if isinstance(payload, Mapping):
        code = payload.get("errorCode")
        if code is not None:
            return str(code)[:32]
    return "unknown"


def parameters_accepted(text: str) -> bool:
    try:
        return json.loads(text).get("status") == "success"
    except (ValueError, AttributeError):
        return False


DEFAULT_FILE_NAME = f"{REPORT_NAME}.xlsx"
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def download_file_name(headers: Mapping[str, Any] | None) -> str:
    """Official file name from ``Content-Disposition`` (RFC 5987 ``filename*`` first); default ``TIR数据简表.xlsx``.

    与「自动归档」的官方工作簿一样保留平台给的文件名；不安全字符或非 .xlsx 时退回默认名。
    """
    from urllib.parse import unquote as _unquote

    value = ""
    for key, item in (headers or {}).items():
        if str(key).lower() == "content-disposition":
            value = str(item)
    name = ""
    match = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", value, re.I)
    if match:
        try:
            name = _unquote(match.group(2).strip().strip('"'), encoding=match.group(1) or "utf-8")
        except LookupError:
            name = ""
    if not name:
        match = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.I)
        if match:
            name = _unquote(match.group(1).strip())
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip().rstrip(". ")
    if not name or _UNSAFE_NAME_RE.search(name) or not name.lower().endswith(".xlsx") or len(name) > 120:
        return DEFAULT_FILE_NAME
    return name


def is_xlsx(content: bytes) -> bool:
    return content[:2] == b"PK"


def looks_like_login_page(status: int, text: str) -> bool:
    return status in (301, 302, 303, 401, 403) or ("/webroot/decision/login" in (text or "")[:4000] and "<html" in (text or "")[:200].lower())


# 单元格内容截到下一个 <td 或 </tr 为止：报表里有不闭合的 <td/>，用 .*?</td> 会吞掉下一格。
_TD_RE = re.compile(r"<td\b([^>]*)>(.*?)(?=<td\b|</tr|$)", re.S | re.I)
_COL_RE = re.compile(r"\bcol=\"(\d+)\"")
_ROW_RE = re.compile(r"\brow=\"(\d+)\"")
_TAG_RE = re.compile(r"<[^>]+>")
_TOTAL_PAGE_RE = re.compile(r"reportTotalPage\s*=\s*(\d+)")


def parse_content_page(payload: Mapping[str, Any]) -> tuple[list[list[str]], int]:
    """``read_w_content`` JSON -> (rows ordered by ``row``, cells by ``col``; reportTotalPage).

    同一格可能在冻结区与主体区各渲染一次，按 (row, col) 去重；``reportTotalPage=0`` 表示未分页。
    """
    if not isinstance(payload, Mapping) or not isinstance(payload.get("html"), str):
        raise ProtocolError("read_w_content 响应不是预期的 STREAM_JSON")
    markup = payload["html"]
    grid: dict[int, dict[int, str]] = {}
    for td in _TD_RE.finditer(markup):
        col, row = _COL_RE.search(td.group(1)), _ROW_RE.search(td.group(1))
        if col is None or row is None:
            continue
        text = html_lib.unescape(_TAG_RE.sub("", td.group(2))).strip()
        cells = grid.setdefault(int(row.group(1)), {})
        if text or int(col.group(1)) not in cells:
            cells[int(col.group(1))] = text
    rows = []
    for index in sorted(grid):
        cells = grid[index]
        width = max(cells) + 1
        rows.append([cells.get(col, "") for col in range(width)])
    match = _TOTAL_PAGE_RE.search(markup)
    return rows, int(match.group(1)) if match else 0


def table_from_pages(pages: Iterable[list[list[str]]]) -> list[list[str]]:
    """Merge paged rows into ``[header] + data``.

    表头行是前三格等于 ``EXPECTED_HEADERS`` 前三项的行；只保留表头非空的列（报表里有隐藏列），
    表头之前的行（标题、参数回显）丢弃，后续分页里重复的表头跳过。
    """
    columns: list[int] | None = None
    header: list[str] = []
    body: list[list[str]] = []
    for rows in pages:
        seen_header = False
        for row in rows:
            if row[:3] == list(EXPECTED_HEADERS[:3]):
                seen_header = True
                if columns is None:
                    columns = [index for index, text in enumerate(row) if text]
                    header = [row[index] for index in columns]
                continue
            if columns is None or not seen_header:
                continue
            values = [row[index] if index < len(row) else "" for index in columns]
            if any(values):
                body.append(values)
    if columns is None:
        raise ProtocolError("报表内容里没有找到表头")
    return [header] + body
