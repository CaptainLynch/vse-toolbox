"""iBOM（ibom.sgmw.com.cn）只读客户端：数模设计审核流程（DMM）计数与报表导出。

接口契约来自 2026-11-18 实网 HAR 与 2026-11-19 阶段 0A 实测（docs/IMPACT_20261118_IBOM_SWITCH.md §11）：

- 所有 ``.api`` 请求为 POST，请求头 ``x-content-md5`` = 请求体 UTF-8 字节的 hex MD5（HAR 238/238 吻合），
  已登录请求另带 ``usertoken``/``userloginname``/``logintype``。
- 成功判定：HTTP 200、响应头 ``x-g-process-result`` 不是 ``error``、JSON ``state == "success"``；
  空 body 一律失败。
- 报表导出是同步文件流：``application/x-download``，内容为 xlsx（``PK`` 开头），文件名在
  ``Content-Disposition``。

本模块只读：不调用任何保存、审批、删除接口。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit

from core.redaction import redact_sensitive_text

DEFAULT_IBOM_BASE_URL = "https://ibom.sgmw.com.cn"
IBOM_CHECK_TOKEN_PATH = "/fwSecurity/authentication/checkToken.api"
IBOM_SMART_QUERY_PATH = "/bommgmt/change/smartQuery.api"
IBOM_DMM_EXPORT_PATH = "/bommgmt/partDigitalModelChange/exportReport.api"
DMM_DISCRIMINATOR = "DMM"
MAX_EXPORT_BYTES = 64 * 1024 * 1024
_ALLOWED_HOSTS = frozenset({"ibom.sgmw.com.cn"})


class IBOMClientError(RuntimeError):
    """iBOM 接口调用失败（只带阶段与状态，不带响应正文或请求头）。"""

    def __init__(self, message: str, *, stage: str, status_code: int | None = None) -> None:
        super().__init__(redact_sensitive_text(message))
        self.stage = stage
        self.status_code = status_code


@dataclass(frozen=True)
class IBOMToken:
    user_token: str = field(repr=False)
    user_login_name: str = field(repr=False)
    login_type: str = "DEFAULT_SSO"


@dataclass(frozen=True)
class IBOMExport:
    content: bytes = field(repr=False)
    file_name: str
    content_type: str

    @property
    def byte_count(self) -> int:
        return len(self.content)


def normalize_https_origin(value: str, label: str, *, allowed_hosts: frozenset[str] | None = None) -> str:
    parts = urlsplit(str(value or "").strip())
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/") or parts.query:
        raise ValueError(f"{label} must be an https origin")
    host = parts.hostname.lower()
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError(f"{label} host is not allowed")
    port = f":{parts.port}" if parts.port else ""
    return f"https://{host}{port}"


def content_md5(text: str) -> str:
    """``x-content-md5``：请求体原文 UTF-8 字节的 hex MD5（空体为空串的 MD5）。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324 - 网关校验约定，非安全用途


def _encode_body(body: Mapping[str, Any] | None) -> str:
    if body is None:
        return ""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _base_headers(text: str) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "needhtmlescape": "false",
        "userlanguage": "zh_CN",
        "x-g-tenant-id": "",
        "x-g-trace-id": uuid.uuid4().hex,
        "x-content-md5": content_md5(text),
    }
    if text:
        headers["content-type"] = "application/json"
    return headers


def _header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is None:
            value = headers.get(name.lower())
        if value is None:
            value = headers.get(name.title())
        return "" if value is None else str(value)
    return ""


def _status(response: Any) -> int:
    return int(getattr(response, "status_code", 0) or 0)


def _post(session: Any, url: str, text: str, headers: Mapping[str, str], timeout: float, stage: str) -> Any:
    try:
        return session.post(
            url,
            data=text.encode("utf-8") if text else None,
            headers=dict(headers),
            timeout=timeout,
            allow_redirects=False,
        )
    except Exception as exc:
        raise IBOMClientError(f"iBOM request failed during {stage}: {type(exc).__name__}", stage=stage) from None


def _json_envelope(response: Any, stage: str) -> dict[str, Any]:
    status = _status(response)
    if status != 200:
        raise IBOMClientError(f"iBOM {stage} returned HTTP {status}", stage=stage, status_code=status)
    if _header(response, "x-g-process-result").strip().lower() == "error":
        raise IBOMClientError(f"iBOM {stage} reported a processing error", stage=stage, status_code=status)
    raw = getattr(response, "content", b"") or b""
    if not raw:
        raise IBOMClientError(f"iBOM {stage} returned an empty body", stage=stage, status_code=status)
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw))
    except (ValueError, UnicodeDecodeError):
        raise IBOMClientError(f"iBOM {stage} did not return JSON", stage=stage, status_code=status) from None
    if not isinstance(payload, dict) or payload.get("state") != "success":
        raise IBOMClientError(f"iBOM {stage} did not succeed", stage=stage, status_code=status)
    return payload


def check_token(
    session: Any,
    base_url: str = DEFAULT_IBOM_BASE_URL,
    *,
    timeout: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> IBOMToken:
    """凭会话 Cookie 换 ``userToken``。会话刚建立时首个请求可能返回空体（实网 HAR 见过），重试一次。

    这里不涉及密码，重试是安全的。
    """
    base = normalize_https_origin(base_url, "base_url")
    url = base + IBOM_CHECK_TOKEN_PATH
    last: IBOMClientError | None = None
    for attempt in range(2):
        if attempt:
            sleep(2.0)
        response = _post(session, url, "", _base_headers(""), timeout, "check-token")
        try:
            payload = _json_envelope(response, "check-token")
        except IBOMClientError as exc:
            last = exc
            continue
        data = payload.get("data") or {}
        token = data.get("userToken") if isinstance(data, dict) else None
        login_name = data.get("userLoginName") if isinstance(data, dict) else None
        if isinstance(token, str) and token and isinstance(login_name, str) and login_name:
            return IBOMToken(token, login_name, str(data.get("loginType") or "DEFAULT_SSO"))
        last = IBOMClientError(
            "iBOM check-token did not return a user token", stage="check-token", status_code=_status(response)
        )
    assert last is not None
    raise last


class IBOMClient:
    """已登录的 iBOM 只读客户端。"""

    def __init__(
        self,
        session: Any,
        token: IBOMToken,
        *,
        base_url: str = DEFAULT_IBOM_BASE_URL,
        timeout: float = 60.0,
        allowed_hosts: frozenset[str] = _ALLOWED_HOSTS,
    ) -> None:
        self.session = session
        self._token = token
        self.base_url = normalize_https_origin(base_url, "base_url", allowed_hosts=allowed_hosts)
        self.timeout = float(timeout)

    def _headers(self, text: str) -> dict[str, str]:
        return {
            **_base_headers(text),
            "locale": "zh_CN",
            "logintype": self._token.login_type,
            "userloginname": self._token.user_login_name,
            "usertoken": self._token.user_token,
        }

    def _call(self, path: str, body: Mapping[str, Any] | None, stage: str) -> Any:
        text = _encode_body(body)
        return _post(self.session, self.base_url + path, text, self._headers(text), self.timeout, stage)

    def dmm_total_count(self) -> int:
        """当前账号可见的 DMM 单据总数（含所有状态）。"""
        response = self._call(
            IBOM_SMART_QUERY_PATH,
            {
                "whereList": [{"fieldName": "DISCRIMINATOR", "operator": "EMPTY", "value": DMM_DISCRIMINATOR}],
                "filterInfo": {},
                "pageInfo": {"beginIndex": 0, "pageSize": 1},
            },
            "dmm-count",
        )
        data = _json_envelope(response, "dmm-count").get("data")
        total = data.get("totalCount") if isinstance(data, dict) else None
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise IBOMClientError("iBOM dmm-count did not return a total", stage="dmm-count")
        return total

    def export_dmm_report(self) -> IBOMExport:
        """导出全部 DMM 的「数模设计审核流程报表」，返回 xlsx 字节（不落盘）。"""
        response = self._call(
            IBOM_DMM_EXPORT_PATH,
            {
                "whereList": [{"fieldName": "DISCRIMINATOR", "operator": "EMPTY", "value": DMM_DISCRIMINATOR}],
                "filterInfo": {},
            },
            "dmm-export",
        )
        status = _status(response)
        if status != 200:
            raise IBOMClientError(f"iBOM dmm-export returned HTTP {status}", stage="dmm-export", status_code=status)
        content_type = _header(response, "Content-Type")
        if not any(kind in content_type.lower() for kind in ("x-download", "spreadsheetml", "octet-stream")):
            raise IBOMClientError("iBOM dmm-export did not return a file", stage="dmm-export", status_code=status)
        content = getattr(response, "content", b"") or b""
        if not isinstance(content, (bytes, bytearray)) or not content.startswith(b"PK"):
            raise IBOMClientError("iBOM dmm-export is not an xlsx file", stage="dmm-export", status_code=status)
        if len(content) > MAX_EXPORT_BYTES:
            raise IBOMClientError("iBOM dmm-export exceeds the size limit", stage="dmm-export", status_code=status)
        return IBOMExport(bytes(content), _file_name(_header(response, "Content-Disposition")), content_type)


def _file_name(disposition: str) -> str:
    default = "数模设计审核流程报表.xlsx"
    for part in disposition.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() in ("filename", "filename*") and value:
            value = value.strip().strip('"')
            if value.lower().startswith("utf-8''"):
                value = value[7:]
            try:
                name = unquote(value)
            except Exception:
                return default
            name = name.replace("\\", "_").replace("/", "_").strip()
            return name if name.lower().endswith(".xlsx") else default
    return default
