# -*- coding: utf-8 -*-
"""Requests-like Windows HTTP transport backed by WinHTTP and Schannel."""

from __future__ import annotations

import json
import math
import re
import uuid
import zlib
from collections.abc import Iterable, Iterator, Mapping as MappingABC
from dataclasses import dataclass
from email.parser import Parser
from http.cookiejar import Cookie, CookieJar
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request


_PROGID = "WinHttp.WinHttpRequest.5.1"
_OPTION_ENABLE_REDIRECTS = 6
_DEFAULT_TIMEOUT = 30.0
_MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
_DECOMPRESSION_CHUNK_BYTES = 64 * 1024
_WINHTTP_TIMEOUT_CODES = {12002, -2147012894, 0x80072EE2}


class WinHTTPError(RuntimeError):
    """Safe transport error that never includes request data or credentials."""

    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id

    def __repr__(self) -> str:
        return "WinHTTPError()"


class WinHTTPTimeoutError(WinHTTPError):
    """Safe, distinguishable WinHTTP receive/connect timeout."""

    def __repr__(self) -> str:
        return "WinHTTPTimeoutError()"


class _Headers(dict[str, str]):
    def __setitem__(self, key: str, value: str) -> None:
        existing = next((item for item in self if item.lower() == str(key).lower()), None)
        if existing is not None:
            super().__delitem__(existing)
        super().__setitem__(str(key), str(value))

    def __getitem__(self, key: str) -> str:
        actual = next((item for item in self if item.lower() == str(key).lower()), str(key))
        return super().__getitem__(actual)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


@dataclass(frozen=True)
class WinHTTPResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @property
    def text(self) -> str:
        charset = _charset(self.headers.get("Content-Type", "")) or "utf-8"
        try:
            return self.content.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        """Provide the requests.Response status-checking surface used by crawlers."""
        if 400 <= self.status_code:
            raise WinHTTPError(f"WinHTTP response returned HTTP {self.status_code}")

    def __repr__(self) -> str:
        return f"WinHTTPResponse(status_code={self.status_code})"


class WinHTTPSession:
    """Small requests.Session-compatible surface used by TDC/Aras auth and crawler.

    Maintains an RFC-aware in-memory cookie jar because each COM request uses a
    fresh WinHttp.WinHttpRequest instance.
    """

    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.headers: dict[str, str] = {}
        self._cookie_jar = CookieJar()
        self.cookies: Mapping[str, str] = _CookieView(self._cookie_jar)
        self.timeout = _validate_timeout(timeout)

    def get(self, url: str, **kwargs: Any) -> WinHTTPResponse:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> WinHTTPResponse:
        return self._request("POST", url, **kwargs)

    def close(self) -> None:
        return None

    def __repr__(self) -> str:
        return "WinHTTPSession()"

    def set_cookies(self, cookies: Mapping[str, str], url: str) -> None:
        """Add caller-provided cookies as host-only cookies for ``url``."""
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("cookie URL must be an absolute HTTP(S) URL")
        for name, value in cookies.items():
            self._cookie_jar.set_cookie(
                Cookie(
                    version=0,
                    name=str(name),
                    value=str(value),
                    port=None,
                    port_specified=False,
                    domain=parts.hostname,
                    domain_specified=False,
                    domain_initial_dot=False,
                    path="/",
                    path_specified=True,
                    secure=False,
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
            )

    def import_cookies(self, cookies: Iterable[Cookie], target_url: str) -> int:
        """Import cookies that RFC 6265 would send to ``target_url``.

        Unlike :meth:`set_cookies`, each cookie keeps its original
        ``domain``/``domain_specified``/``domain_initial_dot``/``path``/
        ``path_specified``/``secure``/``port``/``expires``/``discard``
        attributes, so a parent-domain cookie (``Domain=.sgmw.com.cn``) is not
        collapsed into a host-only cookie for ``target_url``.

        Eligibility is decided by ``http.cookiejar``'s own matching: a cookie is
        imported only when a throwaway jar holding just that cookie attaches a
        ``Cookie`` header to a request for ``target_url``. Host-only cookies for
        a different host (e.g. ``account.sgmw.com.cn``) are therefore never
        imported for ``tdc.sgmw.com.cn``. Cookie names and values are never
        logged, recorded, or surfaced.

        Args:
            cookies: iterable of ``http.cookiejar.Cookie`` objects; a
                ``CookieJar`` is iterable and yields its cookies.
            target_url: absolute HTTP(S) URL the cookies must be valid for.

        Returns:
            The number of cookies actually imported (0 is a valid result).
        """
        parts = urlsplit(target_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("target URL must be an absolute HTTP(S) URL")
        imported = 0
        for cookie in cookies:
            probe = CookieJar()
            probe.set_cookie(_clone_cookie(cookie))
            probe_request = Request(target_url)
            probe.add_cookie_header(probe_request)
            if probe_request.get_header("Cookie"):
                self._cookie_jar.set_cookie(_clone_cookie(cookie))
                imported += 1
        return imported

    def _cookie_header(self, url: str) -> str:
        request = Request(url)
        self._cookie_jar.add_cookie_header(request)
        return str(request.get_header("Cookie") or "")

    def _absorb_set_cookies(self, raw_headers: str, url: str) -> None:
        lines = raw_headers.splitlines()
        if lines and ":" not in lines[0]:
            lines = lines[1:]
        response = _CookieResponse(Parser().parsestr("\n".join(lines)))
        self._cookie_jar.extract_cookies(response, Request(url))

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | tuple[float, float] | None = None,
        allow_redirects: bool = True,
    ) -> WinHTTPResponse:
        request_id = uuid.uuid4().hex[:8]
        connect_timeout, receive_timeout = _timeout_pair(self.timeout if timeout is None else timeout)
        connect_timeout_ms = round(connect_timeout * 1000)
        receive_timeout_ms = round(receive_timeout * 1000)
        final_url = _with_params(url, params)
        request_headers = {**self.headers, **dict(headers or {})}
        # Replay cookies from the jar; merge with any caller-supplied Cookie header.
        jar_header = self._cookie_header(final_url)
        if jar_header:
            existing_key = next((k for k in request_headers if k.lower() == "cookie"), None)
            if existing_key:
                request_headers[existing_key] = f"{request_headers[existing_key]}; {jar_header}"
            else:
                request_headers["Cookie"] = jar_header
        body = _encode_data(data)
        initialized = False
        handle: Any = None
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            initialized = True
            handle = win32com.client.Dispatch(_PROGID)
            handle.SetTimeouts(
                connect_timeout_ms,
                connect_timeout_ms,
                connect_timeout_ms,
                receive_timeout_ms,
            )
            handle.SetOption(_OPTION_ENABLE_REDIRECTS, bool(allow_redirects))
            handle.Open(method, final_url, False)
            for name, value in request_headers.items():
                handle.SetRequestHeader(str(name), str(value))
            if body is None:
                handle.Send()
            else:
                handle.Send(body)
            status_code = int(handle.Status)
            raw_response_headers = str(handle.GetAllResponseHeaders() or "")
            response_headers = _parse_headers(raw_response_headers)
            content = _response_bytes(handle.ResponseBody)
            self._absorb_set_cookies(raw_response_headers, final_url)
            content = _decode_response_content(content, response_headers)
            return WinHTTPResponse(status_code, response_headers, content)
        except Exception as exc:
            if isinstance(exc, WinHTTPError):
                raise
            if _contains_winhttp_timeout_code(exc.args):
                raise WinHTTPTimeoutError(
                    "WinHTTP request timed out",
                    request_id=request_id,
                ) from exc
            raise WinHTTPError(
                f"WinHTTP request failed: {type(exc).__name__}",
                request_id=request_id,
            ) from exc
        finally:
            handle = None
            if initialized:
                pythoncom.CoUninitialize()


def _clone_cookie(cookie: Cookie) -> Cookie:
    """Copy a cookie preserving every scope-defining attribute.

    ``_rest`` holds private flags such as ``HttpOnly``/``SameSite`` that
    ``http.cookiejar`` keeps off the public surface; copying it keeps those
    attributes intact across the source and target jars.
    """
    return Cookie(
        version=cookie.version,
        name=cookie.name,
        value=cookie.value,
        port=cookie.port,
        port_specified=cookie.port_specified,
        domain=cookie.domain,
        domain_specified=cookie.domain_specified,
        domain_initial_dot=cookie.domain_initial_dot,
        path=cookie.path,
        path_specified=cookie.path_specified,
        secure=cookie.secure,
        expires=cookie.expires,
        discard=cookie.discard,
        comment=cookie.comment,
        comment_url=cookie.comment_url,
        rest=dict(getattr(cookie, "_rest", {})),
        rfc2109=cookie.rfc2109,
    )


def _with_params(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    encoded = urlencode(params, doseq=True)
    query = f"{parts.query}&{encoded}" if parts.query else encoded
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _encode_data(data: Any) -> bytes | str | None:
    if data is None or isinstance(data, (bytes, str)):
        return data
    if isinstance(data, Mapping):
        return urlencode(data, doseq=True)
    return str(data)


def _parse_headers(raw: str) -> _Headers:
    headers = _Headers()
    for line in raw.splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
    return headers


def _response_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return bytes(value)


class _CookieResponse:
    def __init__(self, headers: Any) -> None:
        self._headers = headers

    def info(self) -> Any:
        return self._headers


class _CookieView(MappingABC[str, str]):
    """Read-only compatibility view that never changes cookie scope."""

    def __init__(self, jar: CookieJar) -> None:
        self._jar = jar

    def __getitem__(self, name: str) -> str:
        matches = [cookie.value for cookie in self._jar if cookie.name == name]
        if not matches:
            raise KeyError(name)
        return matches[-1]

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys(cookie.name for cookie in self._jar))

    def __len__(self) -> int:
        return len(set(cookie.name for cookie in self._jar))


def _decode_response_content(content: bytes, headers: Mapping[str, str]) -> bytes:
    encodings = [
        item.strip().lower()
        for item in headers.get("Content-Encoding", "").split(",")
        if item.strip() and item.strip().lower() != "identity"
    ]
    decoded = content
    for encoding in reversed(encodings):
        if encoding in {"gzip", "x-gzip"}:
            decoded = _decompress_bounded(decoded, 16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            try:
                decoded = _decompress_bounded(decoded, zlib.MAX_WBITS)
            except zlib.error:
                decoded = _decompress_bounded(decoded, -zlib.MAX_WBITS)
        else:
            raise WinHTTPError(f"WinHTTP response uses unsupported Content-Encoding: {encoding}")
    return decoded


def _decompress_bounded(content: bytes, window_bits: int) -> bytes:
    decompressor = zlib.decompressobj(window_bits)
    output = bytearray()
    for offset in range(0, len(content), _DECOMPRESSION_CHUNK_BYTES):
        pending = content[offset : offset + _DECOMPRESSION_CHUNK_BYTES]
        while pending:
            remaining = _MAX_DECOMPRESSED_BYTES + 1 - len(output)
            if remaining <= 0:
                raise WinHTTPError("WinHTTP response exceeds the decompressed size limit")
            output.extend(decompressor.decompress(pending, remaining))
            pending = decompressor.unconsumed_tail
            if len(output) > _MAX_DECOMPRESSED_BYTES:
                raise WinHTTPError("WinHTTP response exceeds the decompressed size limit")
    remaining = _MAX_DECOMPRESSED_BYTES + 1 - len(output)
    output.extend(decompressor.flush(max(remaining, 1)))
    if len(output) > _MAX_DECOMPRESSED_BYTES:
        raise WinHTTPError("WinHTTP response exceeds the decompressed size limit")
    if not decompressor.eof or decompressor.unused_data:
        raise zlib.error("compressed response is incomplete or contains trailing data")
    return bytes(output)


def _charset(content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    return match.group(1).strip("\"'") if match else ""


def _validate_timeout(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("timeout must be positive")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be positive") from exc
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 600:
        raise ValueError("timeout must be between 0 and 600 seconds")
    return timeout


def _timeout_pair(value: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(value, tuple):
        if len(value) != 2:
            raise ValueError("timeout tuple must contain connect and receive values")
        return _validate_timeout(value[0]), _validate_timeout(value[1])
    timeout = _validate_timeout(value)
    return timeout, timeout


def _contains_winhttp_timeout_code(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value in _WINHTTP_TIMEOUT_CODES
    if isinstance(value, (tuple, list)):
        return any(_contains_winhttp_timeout_code(item) for item in value)
    return False
