"""Production Scheme-A browser owner for SGMW Aras password authentication."""

from __future__ import annotations

import hmac
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from services.aras_browser_transport import (
    BrowserArasSession,
    BrowserTransportError,
)


ACCOUNT_ORIGIN = "https://account.sgmw.com.cn"
AUTHORIZE_PATH = "/auth/realms/common/protocol/openid-connect/auth"
LOGIN_PATH = "/auth/realms/common/login-actions/authenticate"
CLIENT_ID = "ecm-front"
SCOPE = "openid"
CALLBACK_PATH = "/innovatorserver/client/redirect.html"
SAFE_STATE = re.compile(r"^[A-Za-z0-9._~-]{1,512}$")
SAFE_CODE = re.compile(r"^[A-Za-z0-9._~-]{1,4096}$")
SAFE_SESSION = re.compile(r"^[A-Za-z0-9._~-]{1,512}$")
OWNER_STATES = frozenset(
    {
        "NEW",
        "BASE_LOADED",
        "CREDENTIAL_SUBMITTED",
        "CALLBACK_VERIFIED",
        "BUSINESS_READY",
        "ACTIVE",
        "FAILED",
        "CLOSING",
        "CLOSED",
    }
)


class BrowserAuthError(RuntimeError):
    """Fixed error shape safe to translate to a public response."""

    def __init__(
        self,
        code: str,
        *,
        stage: str,
        category: str,
        capability_mask: int = 0,
        http_status: int = 502,
        credential_touched: bool = False,
    ) -> None:
        self.code = code if _safe_code(code) else "AUTH_BROWSER_UNAVAILABLE"
        self.stage = stage if stage in _AUTH_STAGES else "base_load"
        self.category = category if category in _AUTH_CATEGORIES else "unexpected"
        self.capability_mask = (
            int(capability_mask) & ((1 << 14) - 1)
            if isinstance(capability_mask, int) and not isinstance(capability_mask, bool)
            else 0
        )
        self.http_status = int(http_status)
        self.credential_touched = bool(credential_touched)
        super().__init__("Browser authentication could not be completed.")


_AUTH_STAGES = frozenset(
    {
        "base_load",
        "credential_submit",
        "callback_wait",
        "callback_verify",
        "auth_capability_wait",
        "auth_header_call",
        "soap_dispatch",
        "soap_response",
        "soap_parse",
        "business_ready",
        "cleanup",
    }
)
_AUTH_CATEGORIES = frozenset(
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


class _CallbackGate:
    def __init__(
        self,
        *,
        devtools: Any,
        connection: Any,
        callback: str,
        expected_state: bytearray,
    ) -> None:
        self.devtools = devtools
        self.connection = connection
        self.callback = callback
        self.expected_state = expected_state
        self.callback_id: int | None = None
        self.event = threading.Event()
        self.credential_post_count = 0
        self.callback_intercepted = False
        self.state_verified = False
        self.continued_original = False
        self.failed = False
        self._lock = threading.Lock()

    def install(self) -> None:
        patterns = [
            self.devtools.fetch.RequestPattern(
                url_pattern=ACCOUNT_ORIGIN + LOGIN_PATH + "*",
                resource_type=self.devtools.network.ResourceType.DOCUMENT,
                request_stage=self.devtools.fetch.RequestStage.REQUEST,
            ),
            self.devtools.fetch.RequestPattern(
                url_pattern=self.callback + "*",
                resource_type=self.devtools.network.ResourceType.DOCUMENT,
                request_stage=self.devtools.fetch.RequestStage.REQUEST,
            ),
        ]
        self.callback_id = self.connection.add_callback(
            self.devtools.fetch.RequestPaused, self._paused
        )
        self.connection.execute(self.devtools.fetch.enable(patterns=patterns))

    def _paused(self, event: Any) -> None:
        with self._lock:
            raw_url = str(event.request.url)
            if len(raw_url) > 8192:
                self._block(event.request_id)
                return
            parsed = urlsplit(raw_url)
            raw_url = ""
            method = str(event.request.method).upper()
            if (
                parsed.scheme == "https"
                and parsed.netloc.casefold() == "account.sgmw.com.cn"
                and parsed.path == LOGIN_PATH
            ):
                query = _parse_query(parsed.query, 4)
                valid = bool(
                    method == "POST"
                    and set(query)
                    == {"session_code", "execution", "client_id", "tab_id"}
                    and all(_one(query, key) for key in query)
                    and query.get("client_id") == [CLIENT_ID]
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.fragment
                )
                self.credential_post_count += 1
                if valid and self.credential_post_count == 1:
                    self.connection.execute(
                        self.devtools.fetch.continue_request(event.request_id)
                    )
                else:
                    self._block(event.request_id)
                return
            self.callback_intercepted = True
            valid = False
            code_value = ""
            returned_state = ""
            try:
                expected = urlsplit(self.callback)
                query = _parse_query(parsed.query, 4)
                code_value = _one(query, "code") or ""
                returned_state = _one(query, "state") or ""
                session_values = query.get("session_state", [])
                valid = bool(
                    method == "GET"
                    and parsed.scheme == expected.scheme
                    and parsed.netloc == expected.netloc
                    and parsed.path == expected.path
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.fragment
                    and set(query).issubset({"code", "state", "session_state"})
                    and len(session_values) <= 1
                    and (
                        not session_values
                        or bool(SAFE_SESSION.fullmatch(session_values[0]))
                    )
                    and bool(SAFE_CODE.fullmatch(code_value))
                    and bool(SAFE_STATE.fullmatch(returned_state))
                    and hmac.compare_digest(
                        returned_state.encode("ascii"), bytes(self.expected_state)
                    )
                )
                code_value = ""
                returned_state = ""
                if valid:
                    self.state_verified = True
                    self.connection.execute(
                        self.devtools.fetch.continue_request(event.request_id)
                    )
                    self.continued_original = True
                else:
                    self._block(event.request_id, set_event=False)
            except Exception:
                code_value = ""
                returned_state = ""
                self._block(event.request_id, set_event=False)
            finally:
                self.event.set()

    def _block(self, request_id: Any, *, set_event: bool = True) -> None:
        self.failed = True
        try:
            self.connection.execute(
                self.devtools.fetch.fail_request(
                    request_id,
                    self.devtools.network.ErrorReason.BLOCKED_BY_CLIENT,
                )
            )
        except Exception:
            pass
        if set_event:
            self.event.set()

    def close(self) -> bool:
        clean = True
        try:
            self.connection.execute(self.devtools.fetch.disable())
        except Exception:
            clean = False
        if self.callback_id is not None:
            try:
                self.connection.remove_callback(
                    self.devtools.fetch.RequestPaused, self.callback_id
                )
            except Exception:
                clean = False
        callbacks = getattr(self.connection, "callbacks", {}).get(
            self.devtools.fetch.RequestPaused.event_class, []
        )
        for index in range(len(self.expected_state)):
            self.expected_state[index] = 0
        self.expected_state.clear()
        return clean and not callbacks


class ArasBrowserSessionOwner:
    """Own Chrome, callback interception and the browser-local transport."""

    def __init__(
        self,
        base_url: str,
        *,
        allow_insecure_http: bool,
        timeout: float,
        driver_factory: Callable[[Path], tuple[Any, Any | None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.base_url, self.origin, self.callback, _soap = _validate_base(
            base_url, allow_insecure_http
        )
        self.allow_insecure_http = bool(allow_insecure_http)
        self.timeout = max(1.0, min(float(timeout), 300.0))
        self._driver_factory = driver_factory or _create_chrome
        self._clock = clock
        self._sleep = sleeper
        self._thread_id = threading.get_ident()
        self._cancel_event = cancel_event if cancel_event is not None else threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._close_started = False
        self._credential_submit_count = 0
        self.cleanup_failed = False
        self._profile: Path | None = None
        self._service: Any | None = None
        self.driver: Any | None = None
        self.session: BrowserArasSession | None = None
        self.state = "NEW"
        self.validated_modules: set[str] = set()
        self.capability_mask = 0

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def credential_submit_count(self) -> int:
        return self._credential_submit_count

    def _transition(self, state: str) -> None:
        if state not in OWNER_STATES:
            raise BrowserAuthError(
                "AUTH_BROWSER_UNAVAILABLE",
                stage="base_load",
                category="unexpected",
            )
        self.state = state

    def authenticate(
        self, username: str, password: str, validation_item_type: str
    ) -> BrowserArasSession:
        username_buffer = bytearray(str(username or "").encode("utf-8"))
        password_buffer = bytearray(str(password or "").encode("utf-8"))
        username = ""
        password = ""
        touched = False
        try:
            if validation_item_type not in {"EWO_O", "PAA_O"}:
                raise BrowserAuthError(
                    "AUTH_SOAP_GATE_FAILED",
                    stage="business_ready",
                    category="item_type",
                    http_status=400,
                )
            self._raise_if_cancelled(
                "base_load", credential_touched=False
            )
            if (
                threading.get_ident() != self._thread_id
                or self.state != "NEW"
            ):
                raise BrowserAuthError(
                    "AUTH_BROWSER_UNAVAILABLE",
                    stage="base_load",
                    category="unexpected",
                )
            if not username_buffer or not password_buffer:
                raise BrowserAuthError(
                    "AUTH_CREDENTIALS_REJECTED",
                    stage="credential_submit",
                    category="unexpected",
                    http_status=400,
                )
            profile = Path(tempfile.mkdtemp(prefix="vse-aras-browser-"))
            self._profile = profile
            self.driver, self._service = self._driver_factory(profile)
            self._raise_if_cancelled("base_load", credential_touched=False)
            self.driver.set_page_load_timeout(max(30.0, self.timeout))
            self.driver.set_script_timeout(max(30.0, self.timeout))
            self._raise_if_cancelled("base_load", credential_touched=False)
            self.driver.get(self.base_url)
            authorize = self._wait_for_authorize()
            self._transition("BASE_LOADED")
            ok, existing_state = _validate_authorize(
                authorize, callback=self.callback, allow_missing_state=True
            )
            authorize = ""
            if not ok:
                raise BrowserAuthError(
                    "AUTH_CALLBACK_INVALID",
                    stage="base_load",
                    category="redirect",
                )
            if existing_state is None:
                current = str(self.driver.current_url or "")
                rebuilt, expected_state = _with_state(current)
                current = ""
                self.driver.get(rebuilt)
                rebuilt = ""
                second = self._wait_for_authorize()
                valid, returned_state = _validate_authorize(
                    second, callback=self.callback, allow_missing_state=False
                )
                second = ""
                if not (
                    valid
                    and returned_state
                    and hmac.compare_digest(
                        returned_state.encode("ascii"), bytes(expected_state)
                    )
                ):
                    raise BrowserAuthError(
                        "AUTH_CALLBACK_INVALID",
                        stage="callback_verify",
                        category="redirect",
                    )
                returned_state = None
            else:
                expected_state = bytearray(existing_state.encode("ascii"))
                existing_state = None
            controls = self._wait_for_form()
            devtools, connection = self.driver.start_devtools()
            gate = _CallbackGate(
                devtools=devtools,
                connection=connection,
                callback=self.callback,
                expected_state=expected_state,
            )
            listener_clean = False
            try:
                gate.install()
                self._raise_if_cancelled(
                    "credential_submit", credential_touched=False
                )
                if self._credential_submit_count != 0:
                    raise BrowserAuthError(
                        "AUTH_CALLBACK_INVALID",
                        stage="credential_submit",
                        category="unexpected",
                        credential_touched=True,
                    )
                controls[0].clear()
                touched = True
                controls[0].send_keys(bytes(username_buffer).decode("utf-8"))
                self._raise_if_cancelled(
                    "credential_submit", credential_touched=True
                )
                controls[1].clear()
                controls[1].send_keys(bytes(password_buffer).decode("utf-8"))
                self._raise_if_cancelled(
                    "credential_submit", credential_touched=True
                )
                self._credential_submit_count = 1
                controls[2].click()
                self._transition("CREDENTIAL_SUBMITTED")
                _zeroize(username_buffer)
                _zeroize(password_buffer)
                callback_deadline = self._clock() + max(30.0, self.timeout)
                while (
                    not gate.event.wait(0.1)
                    and self._clock() < callback_deadline
                ):
                    self._raise_if_cancelled(
                        "callback_wait", credential_touched=True
                    )
                self._raise_if_cancelled(
                    "callback_wait", credential_touched=True
                )
                if not gate.event.is_set():
                    raise BrowserAuthError(
                        "AUTH_CALLBACK_TIMEOUT",
                        stage="callback_wait",
                        category="timeout",
                        http_status=504,
                        credential_touched=True,
                    )
                if not (
                    gate.credential_post_count == 1
                    and gate.callback_intercepted
                    and gate.state_verified
                    and gate.continued_original
                    and not gate.failed
                ):
                    raise BrowserAuthError(
                        "AUTH_CALLBACK_INVALID",
                        stage="callback_verify",
                        category="redirect",
                        credential_touched=True,
                    )
                self._transition("CALLBACK_VERIFIED")
            finally:
                listener_clean = gate.close()
            if not listener_clean:
                raise BrowserAuthError(
                    "AUTH_CLEANUP_FAILED",
                    stage="cleanup",
                    category="unexpected",
                    credential_touched=touched,
                )
            session_deadline = self._clock() + 15 * 60.0
            self.session = BrowserArasSession(
                self,
                base_url=self.base_url,
                deadline=session_deadline,
                clock=self._clock,
                sleeper=self._sleep,
            )
            self.capability_mask = self._wait_for_capability(self.session)
            try:
                self.capability_mask = self.session.perform_gate(
                    validation_item_type, max(30.0, self.timeout)
                )
            except BrowserTransportError as exc:
                raise _translate_transport(exc, touched=True) from None
            self.validated_modules.add(validation_item_type)
            self._transition("BUSINESS_READY")
            self._transition("ACTIVE")
            return self.session
        except BrowserAuthError:
            self._transition("FAILED")
            self.close()
            raise
        except Exception:
            self._transition("FAILED")
            self.close()
            raise BrowserAuthError(
                "AUTH_BROWSER_UNAVAILABLE",
                stage="credential_submit" if touched else "base_load",
                category="browser_closed" if touched else "unexpected",
                credential_touched=touched,
            ) from None
        finally:
            _zeroize(username_buffer)
            _zeroize(password_buffer)
            username = ""
            password = ""

    def _wait_for_authorize(self) -> str:
        deadline = self._clock() + max(30.0, self.timeout)
        while self._clock() < deadline and not self.cancelled:
            try:
                current = str(self.driver.current_url or "")
                parsed = urlsplit(current)
                if (
                    parsed.scheme == "https"
                    and parsed.netloc.casefold() == "account.sgmw.com.cn"
                    and parsed.path == AUTHORIZE_PATH
                ):
                    return current
            except Exception:
                pass
            self._sleep(0.2)
        raise BrowserAuthError(
            "AUTH_EXPORT_CANCELLED"
            if self.cancelled
            else "AUTH_CALLBACK_TIMEOUT",
            stage="base_load",
            category="cancelled" if self.cancelled else "timeout",
            http_status=504,
        )

    def _wait_for_form(self) -> tuple[Any, Any, Any]:
        deadline = self._clock() + max(30.0, self.timeout)
        while self._clock() < deadline and not self.cancelled:
            try:
                return _locate_form(self.driver)
            except Exception:
                self._sleep(0.2)
        raise BrowserAuthError(
            "AUTH_EXPORT_CANCELLED"
            if self.cancelled
            else "AUTH_BROWSER_UNAVAILABLE",
            stage="credential_submit",
            category="cancelled" if self.cancelled else "timeout",
            http_status=504,
        )

    def _wait_for_capability(self, session: BrowserArasSession) -> int:
        deadline = self._clock() + min(120.0, max(30.0, self.timeout * 4.0))
        last_mask = 0
        while self._clock() < deadline and not self.cancelled:
            mask, candidates = session.capability()
            last_mask = mask
            if candidates == 1 and mask & (1 << 4):
                return mask
            if candidates > 1:
                raise BrowserAuthError(
                    "AUTH_SESSION_CAPABILITY_AMBIGUOUS",
                    stage="auth_capability_wait",
                    category="capability_ambiguous",
                    capability_mask=mask,
                    credential_touched=True,
                )
            self._sleep(0.25)
        raise BrowserAuthError(
            "AUTH_EXPORT_CANCELLED"
            if self.cancelled
            else "AUTH_SESSION_CAPABILITY_TIMEOUT",
            stage="auth_capability_wait",
            category="cancelled" if self.cancelled else "capability_missing",
            capability_mask=last_mask,
            http_status=504,
            credential_touched=True,
        )

    def _raise_if_cancelled(
        self, stage: str, *, credential_touched: bool
    ) -> None:
        if self.cancelled:
            raise BrowserAuthError(
                "AUTH_EXPORT_CANCELLED",
                stage=stage,
                category="cancelled",
                http_status=409,
                credential_touched=credential_touched,
            )

    def validate_module(self, item_type: str) -> None:
        if item_type in self.validated_modules:
            return
        if self.session is None:
            raise BrowserAuthError(
                "AUTH_BROWSER_UNAVAILABLE",
                stage="business_ready",
                category="browser_closed",
            )
        try:
            self.capability_mask = self.session.perform_gate(
                item_type, max(30.0, self.timeout)
            )
        except BrowserTransportError as exc:
            raise _translate_transport(exc, touched=True) from None
        self.validated_modules.add(item_type)

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def close(self) -> bool:
        with self._close_lock:
            if self._closed or self._close_started:
                return not self.cleanup_failed
            self._close_started = True
        self._transition("CLOSING")
        self._cancel_event.set()
        driver = self.driver
        service = self._service
        profile = self._profile
        cleanup_ok = True
        try:
            if driver is not None:
                try:
                    driver.execute_script(
                        "try{window.top.__vseArasActiveAbort.abort();}"
                        "catch(_){};try{delete window.top.__vseArasActiveAbort;}"
                        "catch(_){};"
                    )
                except Exception:
                    pass
                for origin in (self.origin, ACCOUNT_ORIGIN):
                    try:
                        driver.execute_cdp_cmd(
                            "Storage.clearDataForOrigin",
                            {"origin": origin, "storageTypes": "all"},
                        )
                    except Exception:
                        cleanup_ok = False
                try:
                    driver.delete_all_cookies()
                except Exception:
                    pass
                try:
                    driver.quit()
                except Exception:
                    cleanup_ok = False
            if service is not None:
                try:
                    service.stop()
                except Exception:
                    cleanup_ok = False
            if profile is not None:
                try:
                    resolved = profile.resolve()
                    temp_root = Path(tempfile.gettempdir()).resolve()
                    if (
                        resolved.parent == temp_root
                        and resolved.name.startswith("vse-aras-browser-")
                    ):
                        shutil.rmtree(resolved, ignore_errors=True)
                        if resolved.exists():
                            cleanup_ok = False
                    else:
                        cleanup_ok = False
                except Exception:
                    cleanup_ok = False
        finally:
            self.driver = None
            self._service = None
            self._profile = None
            self.session = None
            self.validated_modules.clear()
            self.capability_mask = 0
            self.cleanup_failed = not cleanup_ok
            self._closed = True
            self._transition("CLOSED")
        return not self.cleanup_failed


def _create_chrome(profile: Path) -> tuple[Any, Any]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
    except Exception:
        raise BrowserAuthError(
            "AUTH_BROWSER_UNAVAILABLE",
            stage="base_load",
            category="capability_missing",
        ) from None
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "none"
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--disable-sync")
    options.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.password_manager_leak_detection": False,
        },
    )
    service = Service(log_output=os.devnull)
    try:
        return webdriver.Chrome(service=service, options=options), service
    except Exception:
        try:
            service.stop()
        except Exception:
            pass
        raise BrowserAuthError(
            "AUTH_BROWSER_UNAVAILABLE",
            stage="base_load",
            category="browser_closed",
        ) from None


def _locate_form(driver: Any) -> tuple[Any, Any, Any]:
    from selenium.webdriver.common.by import By

    passwords = [
        element
        for element in driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
        if _usable(element)
    ]
    if len(passwords) != 1:
        raise ValueError("credential_form")
    form = passwords[0].find_element(By.XPATH, "ancestor::form[1]")
    usernames: list[Any] = []
    for element in form.find_elements(By.CSS_SELECTOR, "input"):
        if not _usable(element):
            continue
        input_type = str(element.get_attribute("type") or "text").casefold()
        name = str(element.get_attribute("name") or "").casefold()
        identifier = str(element.get_attribute("id") or "").casefold()
        if input_type in {"text", "email"} and (
            "username" in name
            or "username" in identifier
            or name in {"user", "account"}
            or identifier in {"user", "account"}
        ):
            usernames.append(element)
    submitters = [
        element
        for element in form.find_elements(By.CSS_SELECTOR, '#kc-login,[name="login"]')
        if _usable(element)
        and str(element.get_attribute("type") or "submit").casefold() == "submit"
        and bool(
            driver.execute_script(
                "return arguments[0].form === arguments[1];", element, form
            )
        )
    ]
    action = urlsplit(str(form.get_attribute("action") or ""))
    query = _parse_query(action.query, 4)
    if not (
        len(usernames) == 1
        and len(submitters) == 1
        and str(form.get_attribute("method") or "").casefold() == "post"
        and action.scheme == "https"
        and action.netloc.casefold() == "account.sgmw.com.cn"
        and action.path == LOGIN_PATH
        and action.username is None
        and action.password is None
        and not action.fragment
        and set(query) == {"session_code", "execution", "client_id", "tab_id"}
        and all(_one(query, key) for key in query)
        and query.get("client_id") == [CLIENT_ID]
    ):
        raise ValueError("credential_form")
    for submitter in submitters:
        submit_action = urlsplit(
            urljoin(
                action.geturl(),
                str(submitter.get_attribute("formaction") or action.geturl()),
            )
        )
        submit_method = str(
            submitter.get_attribute("formmethod") or form.get_attribute("method")
        ).casefold()
        if (
            submit_method != "post"
            or submit_action.scheme != "https"
            or submit_action.netloc.casefold() != "account.sgmw.com.cn"
            or submit_action.path != LOGIN_PATH
        ):
            raise ValueError("credential_form")
    return usernames[0], passwords[0], submitters[0]


def _usable(element: Any) -> bool:
    try:
        return bool(element.is_displayed() and element.is_enabled())
    except Exception:
        return False


def _validate_base(
    value: str, allow_insecure_http: bool
) -> tuple[str, str, str, str]:
    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/").casefold() != "/innovatorserver"
        or (parsed.scheme == "http" and not allow_insecure_http)
    ):
        raise BrowserAuthError(
            "INSECURE_HTTP_NOT_ALLOWED"
            if parsed.scheme == "http" and not allow_insecure_http
            else "INVALID_BASE_URL",
            stage="base_load",
            category="redirect",
            http_status=400,
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    base = origin + "/innovatorserver"
    callback = base + "/client/redirect.html"
    soap = base + "/Server/InnovatorServer.aspx"
    return base, origin, callback, soap


def _validate_authorize(
    value: str, *, callback: str, allow_missing_state: bool
) -> tuple[bool, str | None]:
    if len(value) > 8192:
        return False, None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "account.sgmw.com.cn"
        or parsed.path != AUTHORIZE_PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return False, None
    query = _parse_query(parsed.query, 5)
    if not set(query).issubset(
        {"client_id", "response_type", "scope", "redirect_uri", "state"}
    ):
        return False, None
    if (
        query.get("client_id") != [CLIENT_ID]
        or query.get("response_type") != ["code"]
        or query.get("scope") != [SCOPE]
        or query.get("redirect_uri") != [callback]
    ):
        return False, None
    states = query.get("state", [])
    if not states and allow_missing_state:
        return True, None
    state = _one(query, "state")
    if state is None or not SAFE_STATE.fullmatch(state):
        return False, None
    return True, state


def _with_state(value: str) -> tuple[str, bytearray]:
    parsed = urlsplit(value)
    query = _parse_query(parsed.query, 4)
    if "state" in query:
        raise BrowserAuthError(
            "AUTH_CALLBACK_INVALID",
            stage="callback_verify",
            category="redirect",
        )
    state = secrets.token_urlsafe(32)
    if len(state) < 32 or not SAFE_STATE.fullmatch(state):
        raise BrowserAuthError(
            "AUTH_CALLBACK_INVALID",
            stage="callback_verify",
            category="unexpected",
        )
    query["state"] = [state]
    rebuilt = parsed._replace(
        query=urlencode(
            [(key, item) for key, values in query.items() for item in values]
        )
    ).geturl()
    return rebuilt, bytearray(state.encode("ascii"))


def _parse_query(value: str, max_fields: int) -> dict[str, list[str]]:
    try:
        return parse_qs(value, keep_blank_values=True, max_num_fields=max_fields)
    except ValueError:
        return {}


def _one(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key, [])
    if len(values) != 1 or not values[0]:
        return None
    return values[0]


def _translate_transport(
    error: BrowserTransportError, *, touched: bool
) -> BrowserAuthError:
    return BrowserAuthError(
        error.code,
        stage=error.stage,
        category=error.category,
        capability_mask=error.capability_mask,
        http_status=error.http_status,
        credential_touched=touched,
    )


def _zeroize(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
    value.clear()


def _safe_code(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value.isupper()
        and value.replace("_", "").isalpha()
    )


__all__ = [
    "ACCOUNT_ORIGIN",
    "ArasBrowserSessionOwner",
    "BrowserAuthError",
    "OWNER_STATES",
]
