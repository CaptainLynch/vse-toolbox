"""Narrow same-browser transport for read-only EWO/PAA ApplyItem requests.

The authorization value is acquired and consumed by one browser-side
JavaScript invocation.  Python receives only a bounded business XML document
and fixed diagnostic values.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from urllib.parse import urljoin, urlsplit


SOAP_ROUTE = "Server/InnovatorServer.aspx"
CLIENT_ROUTE = "Client/default.aspx"
SOAP11_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
DEFAULT_PAGE_SIZE = 50
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_ITEM_TYPES = {"ewo": "EWO_O", "paa": "PAA_O"}
_ITEM_MODULES = {value: key for key, value in _ITEM_TYPES.items()}

ALLOWED_STAGES = frozenset(
    {
        "auth_capability_wait",
        "auth_header_call",
        "soap_dispatch",
        "soap_response",
        "soap_parse",
        "business_ready",
        "cleanup",
    }
)
ALLOWED_CATEGORIES = frozenset(
    {
        "timeout",
        "capability_missing",
        "capability_ambiguous",
        "authorization_unavailable",
        "redirect",
        "http_auth",
        "http_forbidden",
        "http_other",
        "oversize",
        "content_type",
        "xml",
        "soap_fault",
        "item_type",
        "browser_closed",
        "cancelled",
        "unexpected",
    }
)

CAP_ORIGIN = 1 << 0
CAP_FRAME = 1 << 1
CAP_ARAS = 1 << 2
CAP_OAUTH = 1 << 3
CAP_HEADER_CALLABLE = 1 << 4
CAP_HEADER_RESOLVED = 1 << 5
CAP_HEADER_SHAPE = 1 << 6
CAP_FETCH_STARTED = 1 << 7
CAP_RESPONSE = 1 << 8
CAP_HTTP_2XX = 1 << 9
CAP_RESPONSE_BOUNDED = 1 << 10
CAP_XML = 1 << 11
CAP_NO_FAULT = 1 << 12
CAP_ITEM_TYPE = 1 << 13
CAP_ALL = (1 << 14) - 1


class BrowserTransportError(RuntimeError):
    """Fixed-shape error which cannot carry request or browser material."""

    def __init__(
        self,
        code: str,
        *,
        stage: str,
        category: str,
        capability_mask: int = 0,
        http_status: int = 502,
    ) -> None:
        self.code = code if _safe_code(code) else "AUTH_SOAP_GATE_FAILED"
        self.stage = stage if stage in ALLOWED_STAGES else "soap_dispatch"
        self.category = category if category in ALLOWED_CATEGORIES else "unexpected"
        self.capability_mask = (
            int(capability_mask) & CAP_ALL
            if isinstance(capability_mask, int) and not isinstance(capability_mask, bool)
            else 0
        )
        self.http_status = int(http_status)
        super().__init__("The browser-local Aras request could not be completed.")


class _EmptyFacade(dict[str, str]):
    """Requests-compatible facade that can never expose browser state."""

    def update(self, *args: Any, **kwargs: Any) -> None:
        if args or kwargs:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )


@dataclass(frozen=True)
class BrowserHttpResponse:
    status_code: int
    text: str
    content_type: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": self.content_type}

    @property
    def reason(self) -> str:
        return ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_response",
                category=_http_category(self.status_code),
                http_status=401 if self.status_code == 401 else 502,
            )


@dataclass
class _ExportScope:
    module: str
    filters_signature: bytes
    max_pages: int
    max_records: int
    deadline: float
    next_page: int = 1
    aml_signature: bytes | None = None

    def clear(self) -> None:
        self.filters_signature = b""
        self.aml_signature = None
        self.next_page = 0


_CAPABILITY_SCRIPT = r"""
const expectedOrigin = arguments[0];
let mask = 0;
let candidates = 0;
function walk(root, seen) {
  if (!root || seen.has(root)) return;
  seen.add(root);
  try {
    if (root.location.origin !== expectedOrigin) return;
    mask |= 1;
    mask |= 2;
    if (root.aras) {
      mask |= 4;
      if (root.aras.OAuthClient) {
        mask |= 8;
        if (typeof root.aras.OAuthClient.getAuthorizationHeader === 'function') {
          mask |= 16;
          candidates += 1;
        }
      }
    }
    for (let index = 0; index < root.frames.length; index++) {
      walk(root.frames[index], seen);
    }
  } catch (_) {}
}
walk(window.top, new Set());
return {mask: mask, candidates: candidates};
"""


_BROWSER_SOAP_SCRIPT = r"""
const done = arguments[arguments.length - 1];
const expectedOrigin = arguments[0];
const soapUrl = arguments[1];
const requestBody = arguments[2];
const timeoutMs = arguments[3];
const maxRequestBytes = arguments[4];
const maxResponseBytes = arguments[5];
const expectedType = arguments[6];
let finished = false;
let mask = 0;
function finish(value) {
  if (!finished) { finished = true; done(value); }
}
function collect(root) {
  const candidates = [];
  const seen = new Set();
  function walk(w) {
    if (!w || seen.has(w)) return;
    seen.add(w);
    try {
      if (w.location.origin !== expectedOrigin) return;
      mask |= 1;
      mask |= 2;
      if (w.aras) {
        mask |= 4;
        if (w.aras.OAuthClient) {
          mask |= 8;
          if (typeof w.aras.OAuthClient.getAuthorizationHeader === 'function') {
            mask |= 16;
            candidates.push(w);
          }
        }
      }
      for (let i = 0; i < w.frames.length; i++) walk(w.frames[i]);
    } catch (_) {}
  }
  walk(root);
  return candidates;
}
(async () => {
  const candidates = collect(window.top);
  if (candidates.length !== 1) {
    return finish({
      ok:false,
      stage:'auth_capability_wait',
      category:candidates.length ? 'capability_ambiguous' : 'capability_missing',
      mask:mask
    });
  }
  const encoded = new TextEncoder().encode(requestBody);
  if (encoded.byteLength > maxRequestBytes) {
    encoded.fill(0);
    return finish({ok:false,stage:'soap_dispatch',category:'oversize',mask:mask});
  }
  encoded.fill(0);
  let authorization = '';
  let authorizationName = '';
  try {
    const authResult = await Promise.resolve(
      candidates[0].aras.OAuthClient.getAuthorizationHeader()
    );
    mask |= 32;
    if (typeof authResult === 'string' && authResult.length > 0) {
      authorizationName = 'Authorization';
      authorization = authResult;
    } else if (authResult && typeof authResult === 'object') {
      const keys = Object.keys(authResult);
      if (keys.length === 1 &&
          keys[0].toLowerCase() === 'authorization' &&
          typeof authResult[keys[0]] === 'string' &&
          authResult[keys[0]].length > 0) {
        authorizationName = keys[0];
        authorization = authResult[keys[0]];
      }
    }
    if (!authorization || !authorizationName) {
      return finish({
        ok:false,stage:'auth_header_call',
        category:'authorization_unavailable',mask:mask
      });
    }
    mask |= 64;
  } catch (_) {
    return finish({
      ok:false,stage:'auth_header_call',
      category:'authorization_unavailable',mask:mask
    });
  }
  const headers = {
    'Content-Type':'text/xml; charset=UTF-8',
    'SOAPAction':'ApplyItem'
  };
  headers[authorizationName] = authorization;
  const controller = new AbortController();
  try { window.top.__vseArasActiveAbort = controller; } catch (_) {}
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    mask |= 128;
    const response = await candidates[0].fetch(soapUrl, {
      method:'POST',
      credentials:'same-origin',
      redirect:'manual',
      headers:headers,
      body:requestBody,
      signal:controller.signal
    });
    authorization = '';
    authorizationName = '';
    mask |= 256;
    if (response.type === 'opaqueredirect' || response.status === 0 ||
        (response.status >= 300 && response.status < 400)) {
      return finish({ok:false,stage:'soap_response',category:'redirect',mask:mask});
    }
    if (response.status === 401) {
      return finish({ok:false,stage:'soap_response',category:'http_auth',mask:mask});
    }
    if (response.status === 403) {
      return finish({ok:false,stage:'soap_response',category:'http_forbidden',mask:mask});
    }
    if (response.status < 200 || response.status >= 300) {
      return finish({ok:false,stage:'soap_response',category:'http_other',mask:mask});
    }
    mask |= 512;
    if (!response.body || typeof response.body.getReader !== 'function') {
      return finish({ok:false,stage:'soap_response',category:'content_type',mask:mask});
    }
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      total += part.value.byteLength;
      if (total > maxResponseBytes) {
        controller.abort();
        return finish({ok:false,stage:'soap_response',category:'oversize',mask:mask});
      }
      chunks.push(part.value);
    }
    const merged = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }
    let text = '';
    try {
      text = new TextDecoder('utf-8', {fatal:true}).decode(merged);
    } catch (_) {
      merged.fill(0);
      return finish({ok:false,stage:'soap_parse',category:'xml',mask:mask});
    }
    merged.fill(0);
    const contentType = String(response.headers.get('content-type') || '').slice(0, 256);
    if (!/xml/i.test(contentType) && !/^\s*</.test(text)) {
      text = '';
      return finish({
        ok:false,stage:'soap_response',category:'content_type',mask:mask
      });
    }
    mask |= 1024;
    let documentValue;
    try {
      documentValue = new DOMParser().parseFromString(text, 'application/xml');
      if (documentValue.getElementsByTagName('parsererror').length) throw new Error();
      mask |= 2048;
    } catch (_) {
      text = '';
      return finish({ok:false,stage:'soap_parse',category:'xml',mask:mask});
    }
    const all = Array.from(documentValue.getElementsByTagName('*'));
    if (all.some(node => node.localName === 'Fault')) {
      text = '';
      return finish({ok:false,stage:'soap_parse',category:'soap_fault',mask:mask});
    }
    mask |= 4096;
    const items = all.filter(node => node.localName === 'Item');
    if (items.length && items.some(node => node.getAttribute('type') !== expectedType)) {
      text = '';
      return finish({ok:false,stage:'soap_parse',category:'item_type',mask:mask});
    }
    mask |= 8192;
    return finish({
      ok:true,status_code:response.status,content_type:contentType,text:text,mask:mask
    });
  } catch (error) {
    authorization = '';
    authorizationName = '';
    return finish({
      ok:false,
      stage:'soap_dispatch',
      category:error && error.name === 'AbortError' ? 'timeout' : 'unexpected',
      mask:mask
    });
  } finally {
    authorization = '';
    authorizationName = '';
    clearTimeout(timer);
    try { delete window.top.__vseArasActiveAbort; } catch (_) {}
  }
})().catch(() => finish({
  ok:false,stage:'soap_dispatch',category:'unexpected',mask:mask
}));
"""

# `execute_async_script` would block the owner thread for the complete fetch
# and prevent a RAM cancel event from being observed.  Scheme A starts the
# promise in browser memory, then polls it from the same owner thread.  The
# canceling thread only sets the shared Event; it never touches WebDriver.
_BROWSER_SOAP_START_SCRIPT = _BROWSER_SOAP_SCRIPT.replace(
    "const done = arguments[arguments.length - 1];",
    (
        "const operationKey = arguments[7];"
        "const operationEntry = {done:false};"
        "window.top[operationKey] = operationEntry;"
        "const done = (value) => {"
        "if (window.top[operationKey] === operationEntry) {"
        "operationEntry.done = true;"
        "operationEntry.value = value;"
        "}"
        "};"
    ),
    1,
)
_BROWSER_SOAP_POLL_SCRIPT = r"""
const operationKey = arguments[0];
const entry = window.top[operationKey];
if (!entry) return {state:'missing'};
if (entry.done !== true) return {state:'pending'};
const value = entry.value;
delete window.top[operationKey];
return {state:'done', value:value};
"""
_BROWSER_SOAP_CANCEL_SCRIPT = r"""
const operationKey = arguments[0];
try { window.top.__vseArasActiveAbort.abort(); } catch (_) {}
try { delete window.top.__vseArasActiveAbort; } catch (_) {}
try { delete window.top[operationKey]; } catch (_) {}
return true;
"""
_BROWSER_OPERATION_KEY = "__vseArasSoapOperation"


class BrowserArasSession:
    """Single-threaded requests-like adapter owned by one Chrome session."""

    is_browser_aras_session = True

    def __init__(
        self,
        owner: Any,
        *,
        base_url: str,
        deadline: float,
        clock: Any = time.monotonic,
        sleeper: Any = time.sleep,
    ) -> None:
        self._owner = owner
        self._driver = owner.driver
        self.base_url = base_url.rstrip("/") + "/"
        parsed = urlsplit(self.base_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._soap_url = urljoin(self.base_url, SOAP_ROUTE)
        self._deadline = float(deadline)
        self._clock = clock
        self._sleep = sleeper
        self._thread_id = threading.get_ident()
        self._scope: _ExportScope | None = None
        self._closed = False
        self._cleanup_ok = True
        self._operation_lock = threading.Lock()
        self.headers = _EmptyFacade()
        self.cookies = _EmptyFacade()
        self.trust_env = False
        self.prewarm = False

    @property
    def owner(self) -> Any:
        return self._owner

    def _require_owner_thread(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        if self._closed or getattr(self._owner, "closed", False):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="browser_closed",
            )
        if getattr(self._owner, "cancelled", False):
            raise BrowserTransportError(
                "AUTH_EXPORT_CANCELLED",
                stage="soap_dispatch",
                category="cancelled",
                http_status=409,
            )

    def capability(self) -> tuple[int, int]:
        self._require_owner_thread()
        try:
            result = self._driver.execute_script(_CAPABILITY_SCRIPT, self._origin)
        except Exception:
            return 0, 0
        if not isinstance(result, Mapping):
            return 0, 0
        mask = result.get("mask")
        candidates = result.get("candidates")
        return (
            int(mask) & CAP_ALL
            if isinstance(mask, int) and not isinstance(mask, bool)
            else 0,
            int(candidates)
            if isinstance(candidates, int) and not isinstance(candidates, bool)
            else 0,
        )

    @contextmanager
    def begin_full_export(
        self,
        module: str,
        filters_signature: str,
        max_pages: int,
        max_records: int,
        deadline: float,
    ) -> Iterator["BrowserArasSession"]:
        self._require_owner_thread()
        if (
            module not in _ITEM_TYPES
            or not isinstance(filters_signature, str)
            or not filters_signature
            or max_pages <= 0
            or max_records <= 0
            or not math.isfinite(deadline)
            or deadline <= self._clock()
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        if not self._operation_lock.acquire(blocking=False):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        scope = _ExportScope(
            module=module,
            filters_signature=hashlib.sha256(
                filters_signature.encode("utf-8")
            ).digest(),
            max_pages=int(max_pages),
            max_records=int(max_records),
            deadline=min(float(deadline), self._deadline),
        )
        self._scope = scope
        try:
            yield self
        finally:
            scope.clear()
            self._scope = None
            self._operation_lock.release()

    def perform_gate(self, item_type: str, timeout: float) -> int:
        module = _ITEM_MODULES.get(item_type)
        if module is None:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="item_type",
                http_status=400,
            )
        payload = (
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="'
            + SOAP11_NAMESPACE
            + '"><SOAP-ENV:Body><ApplyItem><Item type="'
            + item_type
            + '" action="get" page="1" pagesize="1" maxRecords="1" '
            'select="id" returnMode="itemsOnly"/></ApplyItem>'
            "</SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )
        response, mask = self._dispatch(payload, item_type, timeout)
        self._validate_response(response, item_type, mask, require_item=True)
        return mask

    def post(
        self,
        url: str,
        *,
        data: str,
        headers: Mapping[str, str] | None,
        timeout: float,
        allow_redirects: bool = False,
    ) -> BrowserHttpResponse:
        self._require_owner_thread()
        scope = self._scope
        if scope is None:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        if self._clock() >= scope.deadline:
            raise BrowserTransportError(
                "AUTH_DEADLINE_EXCEEDED",
                stage="soap_dispatch",
                category="timeout",
                http_status=504,
            )
        self._validate_target(url, allow_redirects)
        self._validate_headers(headers)
        item_type = self._validate_aml(data, scope)
        response, mask = self._dispatch(
            data,
            item_type,
            min(float(timeout), scope.deadline - self._clock()),
        )
        self._validate_response(response, item_type, mask, require_item=False)
        return response

    def _validate_target(self, url: str, allow_redirects: bool) -> None:
        actual = urlsplit(str(url))
        expected = urlsplit(self._soap_url)
        if (
            allow_redirects is not False
            or actual.scheme != expected.scheme
            or actual.netloc != expected.netloc
            or actual.path != expected.path
            or actual.query
            or actual.fragment
            or actual.username is not None
            or actual.password is not None
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="redirect",
            )

    def _validate_headers(self, headers: Mapping[str, str] | None) -> None:
        if not isinstance(headers, Mapping):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        lowered = {str(key).casefold(): value for key, value in headers.items()}
        if (
            lowered.get("soapaction") != "ApplyItem"
            or lowered.get("content-type") != "text/xml; charset=UTF-8"
            or any(
                name in lowered
                for name in ("authorization", "cookie", "x-csrf-token")
            )
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )

    def _validate_aml(self, data: str, scope: _ExportScope) -> str:
        if not isinstance(data, str) or len(data.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="oversize",
            )
        try:
            root = ET.fromstring(data)
        except (ET.ParseError, ValueError):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_parse",
                category="xml",
            ) from None
        if (
            root.tag != f"{{{SOAP11_NAMESPACE}}}Envelope"
            or root.attrib
            or len(list(root)) != 1
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_parse",
                category="xml",
            )
        body = _single_child(root, "Body")
        if body.attrib or len(list(body)) != 1:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_parse",
                category="xml",
            )
        apply = _single_child(body, "ApplyItem")
        if apply.attrib or len(list(apply)) != 1:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        item = _single_child(apply, "Item")
        item_type = item.get("type", "")
        if (
            item_type != _ITEM_TYPES[scope.module]
            or item.get("action") != "get"
            or item.get("returnMode") != "itemsOnly"
            or set(item.attrib)
            != {
                "type",
                "action",
                "page",
                "select",
                "pagesize",
                "maxRecords",
                "returnMode",
            }
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="item_type",
            )
        try:
            page = int(item.attrib["page"])
            page_size = int(item.attrib["pagesize"])
            max_records = int(item.attrib["maxRecords"])
        except (KeyError, ValueError):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            ) from None
        from services.aras_crawler import (
            DEFAULT_EWO_SELECT_FIELDS,
            DEFAULT_PAA_SELECT_FIELDS,
        )

        expected_select = ",".join(
            DEFAULT_EWO_SELECT_FIELDS
            if scope.module == "ewo"
            else DEFAULT_PAA_SELECT_FIELDS
        )
        if (
            page != scope.next_page
            or page > scope.max_pages
            or page_size != DEFAULT_PAGE_SIZE
            or max_records != scope.max_records
            or item.get("select") != expected_select
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        _validate_filter_tree(item, scope.module)
        signature = hashlib.sha256(
            repr(_element_descriptor(item, omit_page=True)).encode()
        ).digest()
        if scope.aml_signature is None:
            scope.aml_signature = signature
        elif not hmac.compare_digest(scope.aml_signature, signature):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="unexpected",
            )
        scope.next_page += 1
        return item_type

    def _dispatch(
        self, data: str, item_type: str, timeout: float
    ) -> tuple[BrowserHttpResponse, int]:
        self._require_owner_thread()
        remaining = (
            min(
                self._deadline,
                getattr(self._scope, "deadline", self._deadline),
            )
            - self._clock()
        )
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(float(timeout))
            or timeout <= 0
            or remaining <= 0
        ):
            raise BrowserTransportError(
                "AUTH_DEADLINE_EXCEEDED",
                stage="soap_dispatch",
                category="timeout",
                http_status=504,
            )
        bounded = min(float(timeout), remaining)
        try:
            self._driver.execute_script(
                _BROWSER_SOAP_START_SCRIPT,
                self._origin,
                self._soap_url,
                data,
                max(1, int(bounded * 1000)),
                MAX_REQUEST_BYTES,
                MAX_RESPONSE_BYTES,
                item_type,
                _BROWSER_OPERATION_KEY,
            )
            result: Any = None
            dispatch_deadline = min(
                self._deadline,
                getattr(self._scope, "deadline", self._deadline),
                self._clock() + bounded,
            )
            while self._clock() < dispatch_deadline:
                if getattr(self._owner, "cancelled", False):
                    self._cancel_active_browser_operation()
                    raise BrowserTransportError(
                        "AUTH_EXPORT_CANCELLED",
                        stage="soap_dispatch",
                        category="cancelled",
                        http_status=409,
                    )
                polled = self._driver.execute_script(
                    _BROWSER_SOAP_POLL_SCRIPT,
                    _BROWSER_OPERATION_KEY,
                )
                if (
                    isinstance(polled, Mapping)
                    and polled.get("state") == "done"
                ):
                    result = polled.get("value")
                    break
                if (
                    not isinstance(polled, Mapping)
                    or polled.get("state") != "pending"
                ):
                    self._cancel_active_browser_operation()
                    raise BrowserTransportError(
                        "AUTH_SOAP_GATE_FAILED",
                        stage="soap_dispatch",
                        category="unexpected",
                    )
                self._sleep(0.05)
            if result is None:
                self._cancel_active_browser_operation()
                raise BrowserTransportError(
                    "AUTH_DEADLINE_EXCEEDED",
                    stage="soap_dispatch",
                    category="timeout",
                    http_status=504,
                )
        except BrowserTransportError:
            raise
        except Exception:
            self._cancel_active_browser_operation()
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_dispatch",
                category="browser_closed",
            ) from None
        finally:
            data = ""
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            stage = result.get("stage") if isinstance(result, Mapping) else None
            category = result.get("category") if isinstance(result, Mapping) else None
            mask = result.get("mask") if isinstance(result, Mapping) else 0
            raise BrowserTransportError(
                _error_code(stage, category),
                stage=str(stage),
                category=str(category),
                capability_mask=mask if isinstance(mask, int) else 0,
                http_status=504 if category == "timeout" else 502,
            )
        status = result.get("status_code")
        text = result.get("text")
        content_type = result.get("content_type")
        mask = result.get("mask")
        if (
            not isinstance(status, int)
            or not isinstance(text, str)
            or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES
            or not isinstance(content_type, str)
            or len(content_type) > 256
            or not isinstance(mask, int)
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_response",
                category="unexpected",
            )
        return BrowserHttpResponse(status, text, content_type), mask & CAP_ALL

    def _cancel_active_browser_operation(self) -> None:
        try:
            self._driver.execute_script(
                _BROWSER_SOAP_CANCEL_SCRIPT,
                _BROWSER_OPERATION_KEY,
            )
        except Exception:
            pass

    @staticmethod
    def _validate_response(
        response: BrowserHttpResponse,
        item_type: str,
        mask: int,
        *,
        require_item: bool,
    ) -> None:
        if not 200 <= response.status_code < 300:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_response",
                category=_http_category(response.status_code),
                capability_mask=mask,
            )
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_parse",
                category="xml",
                capability_mask=mask,
            ) from None
        if any(_local_name(node.tag) == "Fault" for node in root.iter()):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_parse",
                category="soap_fault",
                capability_mask=mask,
                http_status=403,
            )
        items = [node for node in root.iter() if _local_name(node.tag) == "Item"]
        if (require_item and not items) or any(
            node.get("type") != item_type for node in items
        ):
            raise BrowserTransportError(
                "AUTH_SOAP_GATE_FAILED",
                stage="soap_parse",
                category="item_type",
                capability_mask=mask,
            )

    def request_cancel(self) -> None:
        try:
            self._owner.request_cancel()
        except Exception:
            pass

    def close(self) -> bool:
        if self._closed:
            return self._cleanup_ok
        self._closed = True
        self.headers.clear()
        self.cookies.clear()
        self._scope = None
        owner = self._owner
        self._owner = None
        self._driver = None
        if owner is not None:
            self._cleanup_ok = bool(owner.close())
        return self._cleanup_ok


def canonical_filters_signature(module: str, filters: Any) -> str:
    """Return a stable, non-secret signature source for the export scope."""
    if module not in _ITEM_TYPES:
        raise ValueError("unsupported Aras report module")
    values = getattr(filters, "__dict__", None)
    if not isinstance(values, dict):
        raise ValueError("filters must be a report filter dataclass")
    normalized = tuple(
        (str(key), "" if value is None else str(value).strip())
        for key, value in sorted(values.items())
    )
    return hashlib.sha256(repr((module, normalized)).encode("utf-8")).hexdigest()


def _validate_filter_tree(item: ET.Element, module: str) -> None:
    ewo_conditions = {
        "_no": None,
        "eplmwriteneplcode": None,
        "_subject": "like",
        "_sort_type": None,
        "_sort_sub_type": None,
        "_area": "like",
        "state": None,
        "_rsp_department": "like",
        "_modelinfo": "like",
        "_submit_time": {"ge", "le"},
    }
    paa_conditions = {
        "_no": None,
        "_ewo_no": None,
        "state": None,
        "_area": "like",
        "_base": "like",
        "_submit_date": {"ge", "le"},
        "_mtl_rq_date": {"ge", "le"},
    }
    allowed = ewo_conditions if module == "ewo" else paa_conditions

    def valid_leaf(node: ET.Element, fields: Mapping[str, Any]) -> bool:
        name = _local_name(node.tag)
        expected = fields.get(name, object())
        if expected.__class__ is object:
            return False
        if list(node):
            return False
        condition = node.attrib.get("condition")
        if expected is None:
            return not node.attrib
        if isinstance(expected, set):
            return set(node.attrib) == {"condition"} and condition in expected
        return set(node.attrib) == {"condition"} and condition == expected

    children = list(item)
    if module == "ewo":
        if any(not valid_leaf(child, allowed) for child in children):
            _filter_rejected()
        _validate_direct_filter_multiplicity(children, {"_submit_time"})
        return
    direct_children: list[ET.Element] = []
    and_count = 0
    for child in children:
        if valid_leaf(child, allowed):
            direct_children.append(child)
            continue
        if _local_name(child.tag) != "and" or child.attrib or (child.text or "").strip():
            _filter_rejected()
        and_count += 1
        if and_count > 1:
            _filter_rejected()
        grouped = list(child)
        if not 1 <= len(grouped) <= 2:
            _filter_rejected()
        seen_group_names: set[str] = set()
        for group in grouped:
            name = _local_name(group.tag)
            if name == "or":
                if name in seen_group_names or group.attrib or (group.text or "").strip():
                    _filter_rejected()
                department_fields = {
                    "_pe_tdc_department": "like",
                    "_requester_department": "like",
                }
                leaves = list(group)
                if (
                    len(leaves) != 2
                    or {_local_name(leaf.tag) for leaf in leaves}
                    != set(department_fields)
                    or any(not valid_leaf(leaf, department_fields) for leaf in leaves)
                ):
                    _filter_rejected()
            elif name == "_vehicles":
                if name in seen_group_names or not valid_leaf(
                    group, {"_vehicles": "like"}
                ):
                    _filter_rejected()
            else:
                _filter_rejected()
            seen_group_names.add(name)
    _validate_direct_filter_multiplicity(
        direct_children, {"_submit_date", "_mtl_rq_date"}
    )


def _validate_direct_filter_multiplicity(
    children: list[ET.Element], dual_condition_fields: set[str]
) -> None:
    seen: dict[str, set[str]] = {}
    for child in children:
        name = _local_name(child.tag)
        condition = child.attrib.get("condition", "")
        values = seen.setdefault(name, set())
        if condition in values:
            _filter_rejected()
        values.add(condition)
        limit = 2 if name in dual_condition_fields else 1
        if len(values) > limit:
            _filter_rejected()


def _filter_rejected() -> None:
    raise BrowserTransportError(
        "AUTH_SOAP_GATE_FAILED",
        stage="soap_dispatch",
        category="unexpected",
    )


def _single_child(parent: ET.Element, local_name: str) -> ET.Element:
    children = [node for node in list(parent) if _local_name(node.tag) == local_name]
    if len(children) != 1:
        raise BrowserTransportError(
            "AUTH_SOAP_GATE_FAILED",
            stage="soap_parse",
            category="xml",
        )
    return children[0]


def _element_descriptor(
    node: ET.Element, *, omit_page: bool = False
) -> tuple[Any, ...]:
    attributes = tuple(
        sorted(
            (key, value)
            for key, value in node.attrib.items()
            if not (omit_page and key == "page")
        )
    )
    return (
        _local_name(node.tag),
        attributes,
        (node.text or "").strip(),
        tuple(_element_descriptor(child) for child in list(node)),
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _http_category(status: int) -> str:
    if status == 401:
        return "http_auth"
    if status == 403:
        return "http_forbidden"
    return "http_other"


def _error_code(stage: Any, category: Any) -> str:
    if category == "cancelled":
        return "AUTH_EXPORT_CANCELLED"
    if category == "timeout":
        return "AUTH_DEADLINE_EXCEEDED"
    if stage == "auth_capability_wait" and category == "capability_ambiguous":
        return "AUTH_SESSION_CAPABILITY_AMBIGUOUS"
    if stage == "auth_capability_wait":
        return "AUTH_SESSION_CAPABILITY_TIMEOUT"
    if stage == "auth_header_call":
        return "AUTH_AUTHORIZATION_UNAVAILABLE"
    return "AUTH_SOAP_GATE_FAILED"


def _safe_code(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value.isupper()
        and value.replace("_", "").isalpha()
    )


__all__ = [
    "ALLOWED_CATEGORIES",
    "ALLOWED_STAGES",
    "BrowserArasSession",
    "BrowserHttpResponse",
    "BrowserTransportError",
    "CAP_ALL",
    "canonical_filters_signature",
]
