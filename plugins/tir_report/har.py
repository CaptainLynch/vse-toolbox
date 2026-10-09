# -*- coding: utf-8 -*-
"""Redacting HAR 1.2 recorder for one FineReport export run.

白名单脱敏（方案 §6，经设计复核收紧）：

- URL 与 Referer 的主机一律换成 ``report.invalid``，查询参数只保留白名单键的值；
- 请求头只保留白名单头的值，其余（Cookie、Authorization、sessionID…）值换成 ``[redacted]``；
- 表单体只保留白名单字段；``__parameters__`` 解码后只留项目/部门/科室/起止日期；JSON 体（登录）只留键名；
- 响应只记状态码、少量响应头与尺寸；正文只保留白名单 JSON 键的标量值（``status/state/isExporting``），
  ``read_w_content`` 的水印（含登录用户名）、xlsx 二进制等一律不记；
- ``serverIPAddress``、``connection``、cookies 恒为空；写出前用本次登记的敏感字面值做一次兜底自检。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from . import protocol as P

PLACEHOLDER_HOST = "report.invalid"
REDACTED = "[redacted]"
_QUERY_KEYS = frozenset({
    "op", "cmd", "widgetname", "format", "extype", "type", "reportIndex", "pn", "__boxModel__", "__webpage__",
    "__fit__", "__cutpage__", "browserWidth", "_paperWidth", "_paperHeight",
})
_HEADER_KEYS = frozenset({"accept", "content-type", "x-requested-with"})
_RESPONSE_HEADER_KEYS = frozenset({"content-type", "content-length", "content-disposition"})
_FORM_KEYS = frozenset({"op", "cmd", "format", "type", "startIndex", "limitIndex", "reload"})
_PARAMETER_KEYS = ("XM", "BM", "KS", "STARTTIME", "ENDTIME")
_RESPONSE_JSON_KEYS = frozenset({"status", "state", "isExporting"})


class HarLeakError(RuntimeError):
    """A registered secret literal survived redaction; the HAR is not written."""


def _placeholder_url(raw: str, *, keep_query: bool = True) -> str:
    parts = urlsplit(raw)
    query = ""
    if keep_query and parts.query:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        query = "&".join(f"{k}={v if k in _QUERY_KEYS else REDACTED}" for k, v in pairs)
    return urlunsplit(("https", PLACEHOLDER_HOST, parts.path, query, ""))


def _query_list(raw: str) -> list[dict[str, str]]:
    return [{"name": k, "value": v if k in _QUERY_KEYS else REDACTED}
            for k, v in parse_qsl(urlsplit(raw).query, keep_blank_values=True)]


def _headers(headers: Mapping[str, str], allowed: frozenset[str]) -> list[dict[str, str]]:
    out = []
    for name, value in headers.items():
        lower = str(name).lower()
        if lower == "referer":
            out.append({"name": name, "value": _placeholder_url(str(value), keep_query=False)})
        elif lower in allowed:
            out.append({"name": name, "value": str(value)})
        else:
            out.append({"name": name, "value": REDACTED})
    return out


def _parameters_summary(encoded: str) -> str:
    try:
        params = P.decode_parameters(encoded)
    except (ValueError, TypeError):
        return REDACTED
    return json.dumps({key: params.get(key, "") for key in _PARAMETER_KEYS}, ensure_ascii=False)


def _post_data(body: Any, content_type: str) -> dict[str, Any] | None:
    if body is None:
        return None
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    if "json" in content_type.lower():
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        keys = sorted(parsed) if isinstance(parsed, Mapping) else []
        return {"mimeType": content_type, "text": json.dumps({k: REDACTED for k in keys})}
    params = []
    for name, value in parse_qsl(text, keep_blank_values=True):
        if name == "__parameters__":
            params.append({"name": name, "value": _parameters_summary(value)})
        else:
            params.append({"name": name, "value": value if name in _FORM_KEYS else REDACTED})
    return {"mimeType": content_type, "params": params}


def _response_text(content: bytes, content_type: str) -> str | None:
    if "json" not in content_type.lower() and "html" not in content_type.lower():
        return None
    if len(content) > 512:
        return None
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(parsed, Mapping):
        return None
    kept = {k: v for k, v in parsed.items()
            if k in _RESPONSE_JSON_KEYS and (isinstance(v, (bool, int)) or (isinstance(v, str) and v.isalnum() and len(v) <= 20))}
    return json.dumps(kept) if kept else None


class HarRecorder:
    """Wraps a requests-like session (``get``/``post``) and records each call."""

    def __init__(self, session: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._session = session
        self._clock = clock
        self.entries: list[dict[str, Any]] = []
        self._secrets: set[str] = set()

    # 会话透传：客户端经 recorder 设置头与 cookie。
    @property
    def headers(self) -> dict[str, str]:
        return self._session.headers

    def set_cookies(self, cookies: Mapping[str, str], url: str) -> None:
        self._session.set_cookies(cookies, url)

    def register_secret(self, *values: str | None) -> None:
        """Literals that must never appear in the written HAR (token, sessionID, username…)."""
        for value in values:
            if value and len(value) >= 4:
                self._secrets.add(value)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._call("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._call("POST", url, **kwargs)

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        started = datetime.now(timezone.utc)
        t0 = self._clock()
        headers = {**dict(getattr(self._session, "headers", {}) or {}), **dict(kwargs.get("headers") or {})}
        response = None
        error: Exception | None = None
        try:
            response = getattr(self._session, method.lower())(url, **kwargs)
            return response
        except Exception as exc:
            error = exc
            raise
        finally:
            self._record(method, url, headers, kwargs.get("data"), response, error, started, self._clock() - t0)

    def _record(self, method: str, url: str, headers: Mapping[str, str], body: Any, response: Any,
                error: Exception | None, started: datetime, elapsed: float) -> None:
        content_type = next((str(v) for k, v in headers.items() if str(k).lower() == "content-type"), "")
        request: dict[str, Any] = {
            "method": method, "url": _placeholder_url(url), "httpVersion": "HTTP/1.1",
            "headers": _headers(headers, _HEADER_KEYS), "queryString": _query_list(url), "cookies": [],
            "headersSize": -1, "bodySize": len(body) if isinstance(body, (bytes, str)) else 0,
        }
        post = _post_data(body, content_type)
        if post is not None:
            request["postData"] = post
        if response is not None:
            resp_headers = dict(getattr(response, "headers", {}) or {})
            mime = next((str(v) for k, v in resp_headers.items() if str(k).lower() == "content-type"), "")
            content = bytes(getattr(response, "content", b"") or b"")
            content_obj: dict[str, Any] = {"size": len(content), "mimeType": mime}
            text = _response_text(content, mime)
            if text is not None:
                content_obj["text"] = text
            resp = {
                "status": int(response.status_code), "statusText": "", "httpVersion": "HTTP/1.1",
                "headers": [h for h in _headers(resp_headers, _RESPONSE_HEADER_KEYS) if h["value"] != REDACTED],
                "cookies": [], "content": content_obj, "redirectURL": "", "headersSize": -1, "bodySize": len(content),
            }
        else:
            resp = {"status": 0, "statusText": type(error).__name__ if error else "", "httpVersion": "HTTP/1.1",
                    "headers": [], "cookies": [], "content": {"size": 0, "mimeType": ""}, "redirectURL": "",
                    "headersSize": -1, "bodySize": -1, "_error": "transport_error"}
        ms = round(elapsed * 1000, 1)
        self.entries.append({
            "startedDateTime": started.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "time": ms, "request": request, "response": resp, "cache": {},
            "timings": {"send": 0, "wait": ms, "receive": 0}, "serverIPAddress": "", "connection": "",
        })

    def to_har(self, *, comment: str = "") -> dict[str, Any]:
        return {"log": {"version": "1.2", "creator": {"name": "vse-toolbox tir-report", "version": "1"},
                        "pages": [], "entries": list(self.entries), "comment": comment}}

    def dumps(self, *, comment: str = "") -> str:
        text = json.dumps(self.to_har(comment=comment), ensure_ascii=False, indent=1)
        leaked = [s for s in self._secrets if s in text or json.dumps(s)[1:-1] in text]
        if leaked:
            raise HarLeakError("HAR 脱敏自检失败：有敏感字面值残留，已拒绝写出")
        return text

    def clear_secrets(self) -> None:
        self._secrets.clear()


def secrets_absent(text: str, values: Iterable[str]) -> bool:
    return not any(value and value in text for value in values)
