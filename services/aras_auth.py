"""Ephemeral, origin-bound password authentication for Aras Innovator.

The adapter follows the OIDC configuration advertised by the target Aras
instance.  Secrets and response bodies are intentionally absent from all
public errors and diagnostics.
"""

from __future__ import annotations

import json
import secrets
import shutil
import sys
import tempfile
import time
import traceback as traceback_module
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - minimal runtime only
    requests = None  # type: ignore[assignment]


DISCOVERY_ROUTE = "Server/OAuthServerDiscovery.aspx"
CLIENT_ROUTE = "Client/default.aspx"
SOAP_ROUTE = "Server/InnovatorServer.aspx"
CALLBACK_ROUTE = "Client/OAuth/RedirectCallback"
CLIENT_ID = "InnovatorClient"
MAX_AUTH_REDIRECTS = 10
SOAP11_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
_BROWSER_PROCESSING_MARKERS = (
    "encryptedpassword",
    "encryptpassword",
    "crypto.subtle",
    "passwordencrypt",
    "passwordcipher",
)
BROWSER_AUTH_SUBSTAGES = frozenset(
    {
        "driver_start",
        "navigate",
        "credential_page",
        "form_validation",
        "credential_submit",
        "callback_wait",
        "session_extract",
        "cleanup",
    }
)
BROWSER_EXCEPTION_CATEGORIES = frozenset(
    {
        "timeout",
        "webdriver",
        "security",
        "protocol",
        "unexpected",
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
    }
)
_CALLBACK_MEMORY_KEY = "__vseArasCallbackCapture"

# Exact B2 failures that are known to occur before the one permitted
# credential POST.  This is deliberately a code/stage/substage/category
# contract, not a caller-provided stage check.  Callback, redirect-origin,
# token, SOAP and credential errors are intentionally absent.
_B2_RETRYABLE_PRETOUCH_ERRORS = frozenset(
    {
        ("AUTH_METADATA_INVALID", "metadata", "navigate", "protocol"),
        ("AUTH_METADATA_INVALID", "metadata", "navigate", "security"),
        ("AUTH_NETWORK_FAILED", "metadata", "navigate", "timeout"),
        ("AUTH_NETWORK_FAILED", "metadata", "navigate", "unexpected"),
        ("AUTH_CODE_CONTRACT_UNSUPPORTED", "client", "navigate", "protocol"),
        ("AUTH_CODE_CONTRACT_UNSUPPORTED", "client", "navigate", "security"),
        ("AUTH_NETWORK_FAILED", "client", "navigate", "timeout"),
        ("AUTH_NETWORK_FAILED", "client", "navigate", "unexpected"),
        ("AUTH_AUTHORIZE_REJECTED", "authorize", "navigate", "protocol"),
        ("AUTH_NETWORK_FAILED", "authorize", "navigate", "timeout"),
        ("AUTH_NETWORK_FAILED", "authorize", "navigate", "unexpected"),
        ("AUTH_FORM_INVALID", "form", "form_validation", "protocol"),
    }
)


class ArasAuthError(RuntimeError):
    """Stable authentication failure safe to return to CLI or Web clients."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        stage: str,
        http_status: int = 502,
        substage: str | None = None,
        category: str | None = None,
        credential_touched: bool = False,
        capability_mask: int = 0,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.stage = stage
        self.http_status = http_status
        self.substage = substage if substage in BROWSER_AUTH_SUBSTAGES else None
        self.category = category if category in BROWSER_EXCEPTION_CATEGORIES else None
        # This flag contains no credential material.  It lets RAM-only callers
        # fail closed after the one permitted credential POST.
        self.credential_touched = bool(credential_touched)
        self.capability_mask = (
            int(capability_mask) & ((1 << 14) - 1)
            if isinstance(capability_mask, int) and not isinstance(capability_mask, bool)
            else 0
        )


def is_retryable_b2_pretouch_error(error: object) -> bool:
    """Return whether a caught internal B2 error may keep the RAM password.

    HTTP request data is never consulted.  The vault caller passes the actual
    ``ArasAuthError`` raised by the authentication service.  An exact type and
    exact tuple are required, and the credential-touch flag is authoritative.
    """
    if type(error) is not ArasAuthError or error.credential_touched is not False:
        return False
    return (
        error.code,
        error.stage,
        error.substage,
        error.category,
    ) in _B2_RETRYABLE_PRETOUCH_ERRORS


@dataclass(frozen=True)
class ArasAuthDiagnosticEvent:
    stage: str
    method: str
    origin: str
    path: str
    status_code: int | None = None
    error_category: str | None = None


@dataclass(frozen=True)
class ArasLoginResult:
    session: Any = field(repr=False)
    expires_at: float | None = None
    auth_origin: str = ""
    validation: str = "apply_item_read"


@dataclass(frozen=True)
class ArasTransportPolicy:
    """One-shot transport permission bound to exactly one Aras origin."""

    base_url: str
    allow_insecure_http: bool = False
    aras_origin: str = field(init=False)

    def __post_init__(self) -> None:
        parsed = _parsed_absolute(self.base_url, "INVALID_BASE_URL", "transport")
        if parsed.scheme not in {"http", "https"}:
            raise ArasAuthError(
                "INVALID_BASE_URL",
                "The Aras address must use HTTP or HTTPS.",
                stage="transport",
                http_status=400,
            )
        origin = _origin_from_parsed(parsed)
        object.__setattr__(self, "aras_origin", origin)
        if parsed.scheme == "http" and not self.allow_insecure_http:
            raise ArasAuthError(
                "INSECURE_HTTP_NOT_ALLOWED",
                "Password authentication over HTTP requires explicit one-time approval.",
                stage="transport",
                http_status=400,
            )

    def validate_aras_url(self, url: str) -> str:
        parsed = _parsed_absolute(url, "INSECURE_HTTP_HOST_MISMATCH", "transport")
        if parsed.username or parsed.password or _origin_from_parsed(parsed) != self.aras_origin:
            raise ArasAuthError(
                "INSECURE_HTTP_HOST_MISMATCH",
                "The request is not bound to the approved Aras origin.",
                stage="transport",
                http_status=400,
            )
        if parsed.scheme == "http" and not self.allow_insecure_http:
            raise ArasAuthError(
                "INSECURE_HTTP_NOT_ALLOWED",
                "Password authentication over HTTP requires explicit one-time approval.",
                stage="transport",
                http_status=400,
            )
        return _strip_userinfo_fragment(url)

    def validate_auth_url(self, url: str, trusted_origins: set[str], *, code: str) -> str:
        parsed = _parsed_absolute(url, code, "authorize")
        origin = _origin_from_parsed(parsed)
        if parsed.username or parsed.password or origin not in trusted_origins:
            raise ArasAuthError(
                code,
                "The identity-provider redirect was rejected by the origin policy.",
                stage="authorize",
            )
        if parsed.scheme != "https" and not (
            origin == self.aras_origin and self.allow_insecure_http
        ):
            raise ArasAuthError(
                code,
                "The identity-provider redirect was rejected by the transport policy.",
                stage="authorize",
            )
        return _strip_userinfo_fragment(url)


@dataclass
class _Form:
    action: str
    method: str
    fields: dict[str, str]
    password_names: list[str]
    username_names: list[str]
    input_types: dict[str, str] = field(default_factory=dict)
    onsubmit: str = ""
    browser_markers: list[str] = field(default_factory=list)


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_Form] = []
        self._current: _Form | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "form":
            self._current = _Form(
                action=attributes.get("action", ""),
                method=attributes.get("method", "post").lower(),
                fields={},
                password_names=[],
                username_names=[],
                onsubmit=attributes.get("onsubmit", "").strip(),
            )
            self.forms.append(self._current)
            return
        if tag.lower() != "input" or self._current is None:
            return
        name = attributes.get("name", "").strip()
        input_type = attributes.get("type", "text").lower()
        if not name:
            if input_type == "password":
                self._current.browser_markers.append("unnamed-password")
            return
        self._current.fields[name] = attributes.get("value", "")
        self._current.input_types[name] = input_type
        lowered = name.casefold()
        encrypted_name = any(
            marker in lowered for marker in ("encrypted", "cipher", "digest", "hash")
        )
        password_named_non_password = (
            input_type != "password"
            and ("password" in lowered or lowered in {"pwd", "pass"})
        )
        if encrypted_name or password_named_non_password:
            self._current.browser_markers.append(f"field:{name}")
        elif input_type == "password":
            self._current.password_names.append(name)
        elif input_type in {"text", "email"} and any(
            marker in lowered for marker in ("user", "login", "email", "account")
        ):
            self._current.username_names.append(name)


class ArasPasswordAuthClient:
    """Authenticate once and return the production Scheme-A browser session."""

    def __init__(
        self,
        base_url: str,
        *,
        allow_insecure_http: bool = False,
        timeout: float = 30.0,
        max_redirects: int = MAX_AUTH_REDIRECTS,
        diagnostic_hook: Callable[[ArasAuthDiagnosticEvent], None] | None = None,
        cancel_event: Any | None = None,
    ) -> None:
        if requests is None:
            raise ImportError("Aras password authentication requires requests")
        self.base_url = _normalize_aras_app_root(base_url)
        self.policy = ArasTransportPolicy(self.base_url, bool(allow_insecure_http))
        self.timeout = max(1.0, float(timeout))
        self.max_redirects = max(1, min(int(max_redirects), MAX_AUTH_REDIRECTS))
        self.diagnostic_hook = diagnostic_hook
        self.cancel_event = cancel_event

    def login(
        self,
        username: str,
        password: str,
        *,
        validation_item_type: str = "EWO_O",
    ) -> ArasLoginResult:
        """Run base-first Scheme A with no B2 import, retry or fallback."""
        from services.aras_browser_auth import (
            ArasBrowserSessionOwner,
            BrowserAuthError,
        )

        user_value = str(username or "")
        password_value = str(password or "")
        username = None  # type: ignore[assignment]
        password = None  # type: ignore[assignment]
        result: ArasLoginResult | None = None
        pending_error: ArasAuthError | None = None
        caught_error: BaseException | None = None
        owner: Any | None = None
        try:
            owner = ArasBrowserSessionOwner(
                self.base_url,
                allow_insecure_http=self.policy.allow_insecure_http,
                timeout=self.timeout,
                cancel_event=self.cancel_event,
            )
            browser_session = owner.authenticate(
                user_value,
                password_value,
                validation_item_type,
            )
            result = ArasLoginResult(
                session=browser_session,
                expires_at=None,
                auth_origin="",
                validation="browser_apply_item_read",
            )
            owner = None
        except BrowserAuthError as exc:
            caught_error = exc
            pending_error = ArasAuthError(
                exc.code,
                _scheme_a_safe_message(exc.code),
                stage=exc.stage,
                http_status=exc.http_status,
                category=exc.category,
                credential_touched=exc.credential_touched,
                capability_mask=exc.capability_mask,
            )
        except Exception as exc:
            caught_error = exc
            pending_error = ArasAuthError(
                "AUTH_BROWSER_UNAVAILABLE",
                "Browser authentication could not be started.",
                stage="base_load",
                category="unexpected",
                credential_touched=True,
            )
        finally:
            if owner is not None:
                try:
                    owner.close()
                except Exception:
                    pass
                owner = None
            if caught_error is not None:
                _clear_auth_exception_chain(caught_error, active_frame=sys._getframe())
            caught_error = None
            user_value = None  # type: ignore[assignment]
            password_value = None  # type: ignore[assignment]
            username = None  # type: ignore[assignment]
            password = None  # type: ignore[assignment]

        # Deliberately outside ``except``/``finally``: Python otherwise stores
        # the handled exception in ``__context__`` even with ``from None``.
        if pending_error is not None:
            error_to_raise = pending_error
            pending_error = None
            # The actual traceback/context/cause were already erased above.
            # Keep legacy presentation semantics without relying on this flag
            # as a secrecy mechanism.
            error_to_raise.__suppress_context__ = True
            raise error_to_raise
        if result is None:  # pragma: no cover - defensive invariant
            raise ArasAuthError(
                "AUTH_BROWSER_UNAVAILABLE",
                "Browser authentication could not be completed.",
                stage="base_load",
            )
        return result

    def _discover(self, session: Any) -> tuple[dict[str, Any], set[str]]:
        response = self._request(
            session,
            "GET",
            self._aras_url(DISCOVERY_ROUTE),
            stage="discovery",
        )
        try:
            document = response.json()
        except Exception as exc:
            raise ArasAuthError(
                "AUTH_DISCOVERY_FAILED",
                "The Aras identity-provider discovery response is invalid.",
                stage="discovery",
            ) from exc
        locations = document.get("locations", []) if isinstance(document, dict) else []
        candidates: list[str] = []
        for item in locations if isinstance(locations, list) else []:
            uri = item.get("uri") if isinstance(item, dict) else None
            if isinstance(uri, str) and uri.strip():
                candidates.append(uri.rstrip("/"))
        if not candidates:
            raise ArasAuthError(
                "AUTH_DISCOVERY_FAILED",
                "No Aras identity provider was advertised.",
                stage="discovery",
            )

        last_error: Exception | None = None
        for location in dict.fromkeys(candidates):
            try:
                origin = _origin(location)
                trusted = {self.policy.aras_origin, origin}
                self.policy.validate_auth_url(
                    location,
                    trusted,
                    code="UNTRUSTED_AUTH_REDIRECT",
                )
                metadata_url = location + "/.well-known/openid-configuration"
                metadata_response = self._request(
                    session,
                    "GET",
                    metadata_url,
                    stage="metadata",
                    trusted_origins=trusted,
                )
                metadata = metadata_response.json()
                authorize = metadata.get("authorization_endpoint") if isinstance(metadata, dict) else None
                if not isinstance(authorize, str) or not authorize:
                    raise ValueError("authorization endpoint is absent")
                # Metadata is trusted only to identify its authorization endpoint.
                # Unrelated issuer/userinfo/token endpoints must never become
                # credential sinks merely because they appear in the document.
                authorize_origin = _origin(authorize)
                authorize_parsed = urlsplit(authorize_origin)
                if authorize_parsed.scheme != "https" and not (
                    authorize_origin == self.policy.aras_origin
                    and self.policy.allow_insecure_http
                ):
                    raise ArasAuthError(
                        "UNTRUSTED_AUTH_REDIRECT",
                        "The identity-provider authorization endpoint was rejected.",
                        stage="metadata",
                    )
                trusted.add(authorize_origin)
                self.policy.validate_auth_url(
                    authorize,
                    trusted,
                    code="UNTRUSTED_AUTH_REDIRECT",
                )
                return metadata, trusted
            except (ArasAuthError, ValueError, TypeError, json.JSONDecodeError) as exc:
                last_error = exc
        raise ArasAuthError(
            "AUTH_METADATA_INVALID",
            "No usable Aras identity-provider metadata was found.",
            stage="metadata",
        ) from last_error

    def _authorize_url(self, metadata: Mapping[str, Any]) -> tuple[str, str]:
        authorize = str(metadata["authorization_endpoint"])
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        callback = self._aras_url(CALLBACK_ROUTE)
        query = urlencode(
            {
                "client_id": CLIENT_ID,
                "response_type": "id_token token",
                "scope": "openid Innovator",
                "redirect_uri": callback,
                "state": state,
                "nonce": nonce,
                "prompt": "login",
            }
        )
        separator = "&" if urlsplit(authorize).query else "?"
        return authorize + separator + query, state

    def _login_with_requests(
        self,
        session: Any,
        authorize_url: str,
        trusted_origins: set[str],
        username: str,
        password: str,
    ) -> str:
        current = authorize_url
        response: Any | None = None
        for _ in range(self.max_redirects + 1):
            if _origin(current) == self.policy.aras_origin and _is_callback(current, self.base_url):
                return current
            response = self._request(
                session,
                "GET",
                current,
                stage="authorize",
                trusted_origins=trusted_origins,
                allow_redirects=False,
            )
            location = _location(response)
            if location:
                current = urljoin(current, location)
                if _is_callback(current, self.base_url):
                    return current
                current = self.policy.validate_auth_url(
                    current,
                    trusted_origins,
                    code="UNTRUSTED_AUTH_REDIRECT",
                )
                continue
            break
        else:
            raise ArasAuthError(
                "AUTH_REDIRECT_LIMIT",
                "The identity-provider redirect limit was exceeded.",
                stage="authorize",
            )
        if response is None:
            raise ArasAuthError(
                "AUTH_BROWSER_REQUIRED",
                "Browser-based authentication is required.",
                stage="authorize",
            )

        html_text = str(getattr(response, "text", "") or "")
        form = _select_login_form(html_text)
        if form is None:
            raise ArasAuthError(
                "AUTH_BROWSER_REQUIRED",
                "Browser-based authentication is required.",
                stage="form",
            )
        action = urljoin(str(getattr(response, "url", current) or current), form.action or current)
        action = self.policy.validate_auth_url(
            action,
            trusted_origins,
            code="AUTH_FORM_ORIGIN_REJECTED",
        )
        if form.method != "post":
            raise ArasAuthError(
                "AUTH_FORM_INVALID",
                "The identity-provider login form is unsupported.",
                stage="form",
            )
        if _form_requires_browser(form, html_text):
            raise ArasAuthError(
                "AUTH_BROWSER_REQUIRED",
                "Browser-based authentication is required.",
                stage="form",
            )
        if not form.password_names or not form.username_names:
            raise ArasAuthError(
                "AUTH_FORM_INVALID",
                "The identity-provider login form is unsupported.",
                stage="form",
            )
        fields = dict(form.fields)
        fields[form.username_names[0]] = username
        fields[form.password_names[0]] = password
        try:
            response = self._request(
                session,
                "POST",
                action,
                stage="credentials",
                trusted_origins=trusted_origins,
                data=fields,
                allow_redirects=False,
            )
        finally:
            for key in list(fields):
                fields[key] = ""
            fields.clear()

        current = str(getattr(response, "url", action) or action)
        for _ in range(self.max_redirects + 1):
            location = _location(response)
            if not location:
                if _looks_like_interaction(str(getattr(response, "text", "") or "")):
                    raise ArasAuthError(
                        "AUTH_INTERACTION_REQUIRED",
                        "The identity provider requires interactive verification.",
                        stage="credentials",
                        http_status=409,
                    )
                raise ArasAuthError(
                    "AUTH_CREDENTIALS_REJECTED",
                    "The username or password was not accepted.",
                    stage="credentials",
                    http_status=401,
                )
            current = urljoin(current, location)
            if _is_callback(current, self.base_url):
                return current
            current = self.policy.validate_auth_url(
                current,
                trusted_origins,
                code="UNTRUSTED_AUTH_REDIRECT",
            )
            response = self._request(
                session,
                "GET",
                current,
                stage="authorize",
                trusted_origins=trusted_origins,
                allow_redirects=False,
            )
        raise ArasAuthError(
            "AUTH_REDIRECT_LIMIT",
            "The identity-provider redirect limit was exceeded.",
            stage="authorize",
        )

    def _login_with_selenium(
        self,
        authorize_url: str,
        trusted_origins: set[str],
        username: str,
        password: str,
    ) -> str:
        browser_substage = "driver_start"
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            raise ArasAuthError(
                "AUTH_BROWSER_UNAVAILABLE",
                "Browser automation is unavailable for this Aras login page.",
                stage="browser",
                substage=browser_substage,
                category="webdriver",
            ) from None

        profile: Path | None = Path(tempfile.mkdtemp(prefix="vse-aras-auth-chrome-"))
        driver: Any | None = None
        try:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.page_load_strategy = "none"
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--incognito")
            chrome_options.add_argument(f"--user-data-dir={profile}")
            try:
                driver = webdriver.Chrome(options=chrome_options)
            except Exception:
                failed_chrome_profile = profile
                profile = None
                try:
                    shutil.rmtree(failed_chrome_profile, ignore_errors=True)
                except Exception:
                    pass
                profile = Path(tempfile.mkdtemp(prefix="vse-aras-auth-edge-"))
                edge_options = webdriver.EdgeOptions()
                edge_options.page_load_strategy = "none"
                edge_options.add_argument("--headless=new")
                edge_options.add_argument("--inprivate")
                edge_options.add_argument(f"--user-data-dir={profile}")
                try:
                    driver = webdriver.Edge(options=edge_options)
                except Exception as exc:
                    raise ArasAuthError(
                        "AUTH_BROWSER_UNAVAILABLE",
                        "Browser automation is unavailable for this Aras login page.",
                        stage="browser",
                        substage=browser_substage,
                        category=_browser_exception_category(exc),
                    ) from None

            browser_substage = "navigate"
            callback_target = self._aras_url(CALLBACK_ROUTE)
            _install_callback_capture_hook(driver, callback_target)
            driver.set_page_load_timeout(self.timeout)
            _navigate_authorize_with_cdp(driver, authorize_url)

            browser_substage = "credential_page"

            def trusted_credential_page(browser: Any) -> bool:
                current = str(browser.current_url or "")
                if _is_exact_callback(current, callback_target):
                    return True
                self.policy.validate_auth_url(
                    current,
                    trusted_origins,
                    code="UNTRUSTED_AUTH_REDIRECT",
                )
                return bool(
                    _usable_elements(
                        browser.find_elements(By.CSS_SELECTOR, "input[type='password']"),
                        required_type="password",
                    )
                )

            WebDriverWait(driver, self.timeout).until(trusted_credential_page)
            captured = _read_callback_capture(driver, callback_target)
            if captured:
                return captured
            current_after_wait = str(driver.current_url or "")
            if _is_exact_callback(current_after_wait, callback_target):
                if urlsplit(current_after_wait).fragment:
                    return current_after_wait

            password_candidates = _usable_elements(
                driver.find_elements(By.CSS_SELECTOR, "input[type='password']"),
                required_type="password",
            )
            if not password_candidates:
                raise ArasAuthError(
                    "AUTH_INTERACTION_REQUIRED",
                    "The identity provider requires interactive verification.",
                    stage="browser",
                    http_status=409,
                )

            browser_substage = "form_validation"
            # Resolve and validate the actual credential form before clear(),
            # send_keys(), click(), or any other credential-bearing action.
            form = password_candidates[0].find_element(By.XPATH, "ancestor::form[1]")
            current_page = str(driver.current_url or "")
            form_method = str(form.get_attribute("method") or "get").strip().casefold()
            form_action_value = str(form.get_attribute("action") or "").strip()
            form_action = urljoin(current_page, form_action_value or current_page)
            if form_method != "post":
                raise ArasAuthError(
                    "AUTH_FORM_INVALID",
                    "The identity-provider login form is unsupported.",
                    stage="browser",
                )
            self.policy.validate_auth_url(
                form_action,
                trusted_origins,
                code="AUTH_FORM_ORIGIN_REJECTED",
            )

            # Submit controls can override both the form action and method.
            # Review every control associated with this form, including hidden
            # and disabled defaults, before placing credentials in the DOM.
            submitters = _related_submitters(driver, form, By)
            safe_submitters: list[Any] = []
            for submitter in submitters:
                submit_method = str(
                    submitter.get_attribute("formmethod") or form_method
                ).strip().casefold()
                submit_action_value = str(
                    submitter.get_attribute("formaction") or form_action_value
                ).strip()
                submit_action = urljoin(
                    current_page,
                    submit_action_value or current_page,
                )
                if submit_method != "post":
                    raise ArasAuthError(
                        "AUTH_FORM_INVALID",
                        "The identity-provider login form is unsupported.",
                        stage="browser",
                    )
                self.policy.validate_auth_url(
                    submit_action,
                    trusted_origins,
                    code="AUTH_FORM_ORIGIN_REJECTED",
                )
                if _usable_elements([submitter]):
                    safe_submitters.append(submitter)

            use_request_submit = False
            if not safe_submitters:
                # requestSubmit() preserves validation and submit events while
                # using the already-reviewed form POST target.  It is safe only
                # for a plain form with no submitter-specific processing.
                requires_submitter_processing = bool(
                    submitters
                    or str(form.get_attribute("onsubmit") or "").strip()
                    or _selenium_form_requires_browser_processing(form, By)
                    or _selenium_page_requires_browser_processing(driver)
                )
                if requires_submitter_processing:
                    raise ArasAuthError(
                        "AUTH_FORM_INVALID",
                        "The identity-provider login form has no safe submit control.",
                        stage="browser",
                    )
                try:
                    use_request_submit = bool(
                        driver.execute_script(
                            "return typeof arguments[0].requestSubmit === 'function';",
                            form,
                        )
                    )
                except Exception:
                    use_request_submit = False
                if not use_request_submit:
                    raise ArasAuthError(
                        "AUTH_FORM_INVALID",
                        "The identity-provider login form has no safe submit control.",
                        stage="browser",
                    )

            browser_substage = "credential_submit"
            password_elements = _usable_elements(
                form.find_elements(By.CSS_SELECTOR, "input[type='password']"),
                required_type="password",
            )
            username_elements = _usable_elements(
                form.find_elements(
                    By.CSS_SELECTOR,
                    "input[type='text'],input[type='email'],input[name*='user' i],input[name*='login' i]",
                )
            )
            if not password_elements or not username_elements:
                raise ArasAuthError(
                    "AUTH_INTERACTION_REQUIRED",
                    "The identity provider requires interactive verification.",
                    stage="browser",
                    http_status=409,
                )
            username_elements[0].clear()
            username_elements[0].send_keys(username)
            password_elements[0].clear()
            password_elements[0].send_keys(password)
            if safe_submitters:
                safe_submitters[0].click()
            else:
                driver.execute_script("arguments[0].requestSubmit();", form)

            browser_substage = "callback_wait"
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                captured = _read_callback_capture(driver, callback_target)
                if captured:
                    return captured
                current = str(driver.current_url or "")
                if _is_exact_callback(current, callback_target) and urlsplit(current).fragment:
                    return current
                if current:
                    if _is_exact_callback(current, callback_target):
                        time.sleep(0.05)
                    else:
                        self.policy.validate_auth_url(
                            current,
                            trusted_origins,
                            code="UNTRUSTED_AUTH_REDIRECT",
                        )
                time.sleep(0.1)
            page_text = str(driver.find_element(By.TAG_NAME, "body").text or "")
            if _looks_like_interaction(page_text):
                raise ArasAuthError(
                    "AUTH_INTERACTION_REQUIRED",
                    "The identity provider requires interactive verification.",
                    stage="browser",
                    http_status=409,
                )
            if _looks_like_credentials_rejected(page_text):
                raise ArasAuthError(
                    "AUTH_CREDENTIALS_REJECTED",
                    "The username or password was not accepted.",
                    stage="browser",
                    http_status=401,
                )
            raise ArasAuthError(
                "AUTH_BROWSER_FAILED",
                "Browser-based authentication could not be completed.",
                stage="browser",
                substage=browser_substage,
                category="timeout",
            )
        except ArasAuthError as exc:
            if exc.substage is not None and exc.category is not None:
                raise
            category = (
                "security"
                if exc.code
                in {
                    "AUTH_FORM_INVALID",
                    "AUTH_FORM_ORIGIN_REJECTED",
                    "UNTRUSTED_AUTH_REDIRECT",
                }
                else "protocol"
            )
            raise ArasAuthError(
                exc.code,
                exc.safe_message,
                stage=exc.stage,
                http_status=exc.http_status,
                substage=browser_substage,
                category=category,
            ) from None
        except Exception as exc:
            raise ArasAuthError(
                "AUTH_BROWSER_FAILED",
                "Browser-based authentication could not be completed.",
                stage="browser",
                substage=browser_substage,
                category=_browser_exception_category(exc),
            ) from None
        finally:
            browser_substage = "cleanup"
            if driver is not None:
                try:
                    driver.execute_script(
                        "try { delete window[arguments[0]]; } catch (_) {} "
                        "window.localStorage.clear(); window.sessionStorage.clear();",
                        _CALLBACK_MEMORY_KEY,
                    )
                except Exception:
                    pass
                try:
                    driver.delete_all_cookies()
                except Exception:
                    pass
                try:
                    driver.quit()
                except Exception:
                    pass
            if profile is not None:
                shutil.rmtree(profile, ignore_errors=True)

    def _parse_callback(self, callback_url: str, expected_state: str) -> tuple[str, str, float | None]:
        parsed = urlsplit(callback_url)
        callback_target = self._aras_url(CALLBACK_ROUTE)
        if not _is_exact_callback(callback_url, callback_target):
            raise ArasAuthError(
                "UNTRUSTED_AUTH_REDIRECT",
                "The identity-provider callback was rejected.",
                stage="callback",
            )
        if parsed.fragment and parsed.query:
            raise ArasAuthError(
                "AUTH_CALLBACK_INVALID",
                "The identity-provider callback response is invalid.",
                stage="callback",
            )
        encoded_values = parsed.fragment or parsed.query
        values = parse_qs(encoded_values, keep_blank_values=True)
        if values.get("error"):
            raise ArasAuthError(
                "AUTH_CREDENTIALS_REJECTED",
                "The identity provider rejected the login.",
                stage="callback",
                http_status=401,
            )
        if values.get("state", [""])[0] != expected_state:
            raise ArasAuthError(
                "AUTH_STATE_MISMATCH",
                "The identity-provider callback state did not match.",
                stage="callback",
            )
        token = values.get("access_token", [""])[0]
        token_type = values.get("token_type", [""])[0]
        if not token or token_type.casefold() != "bearer":
            raise ArasAuthError(
                "AUTH_TOKEN_MISSING",
                "The identity-provider callback did not contain a usable access token.",
                stage="callback",
            )
        expires_at: float | None = None
        try:
            expires = int(values.get("expires_in", [""])[0])
            if expires > 0:
                expires_at = time.time() + expires
        except (TypeError, ValueError):
            expires_at = None
        return token, "Bearer", expires_at

    def validate_authenticated_session(self, session: Any, item_type: str) -> None:
        """Validate a vault-owned session for one allowlisted read-only report type."""
        if item_type not in {"EWO_O", "PAA_O"}:
            raise ArasAuthError(
                "AUTH_VALIDATION_INVALID",
                "The authentication validation target is not allowed.",
                stage="validation",
                http_status=400,
            )
        try:
            from services.aras_browser_transport import BrowserArasSession
        except ImportError:  # pragma: no cover - defensive packaging guard
            BrowserArasSession = ()  # type: ignore[assignment,misc]
        if isinstance(session, BrowserArasSession):
            try:
                session.owner.validate_module(item_type)
            except Exception as exc:
                code = getattr(exc, "code", "AUTH_SOAP_GATE_FAILED")
                stage = getattr(exc, "stage", "business_ready")
                category = getattr(exc, "category", "unexpected")
                capability_mask = getattr(exc, "capability_mask", 0)
                raise ArasAuthError(
                    code if isinstance(code, str) else "AUTH_SOAP_GATE_FAILED",
                    _scheme_a_safe_message(code),
                    stage=stage if isinstance(stage, str) else "business_ready",
                    category=category if isinstance(category, str) else "unexpected",
                    capability_mask=(
                        capability_mask if isinstance(capability_mask, int) else 0
                    ),
                    credential_touched=True,
                ) from None
            return
        self._validate_session(session, item_type)

    def _validate_session(self, session: Any, item_type: str) -> None:
        payload = (
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
            '<SOAP-ENV:Body><ApplyItem><Item type="'
            + item_type
            + '" action="get" page="1" pagesize="1" maxRecords="1" '
            'select="id" returnMode="itemsOnly"/></ApplyItem></SOAP-ENV:Body></SOAP-ENV:Envelope>'
        )
        response = self._request(
            session,
            "POST",
            self._aras_url(SOAP_ROUTE),
            stage="validation",
            data=payload,
            headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": "ApplyItem"},
            allow_redirects=False,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 401:
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session could not be validated.",
                stage="validation",
                http_status=401,
            )
        if status == 403:
            raise ArasAuthError(
                "ARAS_PERMISSION_DENIED",
                "The authenticated account cannot read the requested Aras report.",
                stage="validation",
                http_status=403,
            )
        if status < 200 or status >= 300:
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session validation request was rejected.",
                stage="validation",
                http_status=502,
            )
        if _location(response) or _looks_like_html(response):
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session could not be validated.",
                stage="validation",
                http_status=401,
            )
        try:
            root = ET.fromstring(str(getattr(response, "text", "") or ""))
        except ET.ParseError as exc:
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session could not be validated.",
                stage="validation",
                http_status=401,
            ) from exc
        soap_envelope_tag = f"{{{SOAP11_NAMESPACE}}}Envelope"
        soap_body_tag = f"{{{SOAP11_NAMESPACE}}}Body"
        if root.tag != soap_envelope_tag:
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session validation response was not a SOAP 1.1 envelope.",
                stage="validation",
                http_status=502,
            )
        body = next(
            (node for node in list(root) if node.tag == soap_body_tag),
            None,
        )
        if body is None:
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session validation response did not contain a SOAP body.",
                stage="validation",
                http_status=502,
            )
        fault = next(
            (node for node in body.iter() if node.tag.rsplit("}", 1)[-1] == "Fault"),
            None,
        )
        if fault is not None:
            raise ArasAuthError(
                "ARAS_PERMISSION_DENIED",
                "The authenticated account cannot read the requested Aras report.",
                stage="validation",
                http_status=403,
            )
        result = next(
            (node for node in body.iter() if node.tag.rsplit("}", 1)[-1] == "Result"),
            None,
        )
        if result is None:
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session validation response did not contain ApplyItem results.",
                stage="validation",
                http_status=502,
            )
        items = [
            node for node in result.iter() if node.tag.rsplit("}", 1)[-1] == "Item"
        ]
        if not items or not any(node.get("type") == item_type for node in items):
            raise ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session validation response did not match the requested report type.",
                stage="validation",
                http_status=502,
            )

    def _request(
        self,
        session: Any,
        method: str,
        url: str,
        *,
        stage: str,
        trusted_origins: set[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        if trusted_origins is None:
            safe_url = self.policy.validate_aras_url(url)
        else:
            safe_url = self.policy.validate_auth_url(
                url,
                trusted_origins,
                code="UNTRUSTED_AUTH_REDIRECT",
            )
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", False)
        try:
            request_method = getattr(session, method.lower(), None)
            if request_method is None:
                def request_method(target: str, **options: Any) -> Any:
                    return session.request(method, target, **options)
            response = request_method(safe_url, **kwargs)
        except ArasAuthError:
            raise
        except Exception as exc:
            self._emit(stage, method, safe_url, error_category=type(exc).__name__)
            raise ArasAuthError(
                "AUTH_NETWORK_FAILED",
                "The Aras authentication service could not be reached.",
                stage=stage,
                http_status=502,
            ) from exc
        status = int(getattr(response, "status_code", 0) or 0)
        self._emit(stage, method, safe_url, status_code=status)
        if status >= 500:
            raise ArasAuthError(
                "AUTH_UPSTREAM_FAILED",
                "The Aras authentication service returned an error.",
                stage=stage,
                http_status=502,
            )
        if status >= 400 and stage not in {"credentials", "validation"}:
            raise ArasAuthError(
                "AUTH_UPSTREAM_REJECTED",
                "The Aras authentication request was rejected.",
                stage=stage,
                http_status=502,
            )
        return response

    def _aras_url(self, route: str) -> str:
        return self.policy.validate_aras_url(urljoin(self.base_url, route.lstrip("/")))

    def _emit(
        self,
        stage: str,
        method: str,
        url: str,
        *,
        status_code: int | None = None,
        error_category: str | None = None,
    ) -> None:
        if self.diagnostic_hook is None:
            return
        parsed = urlsplit(url)
        self.diagnostic_hook(
            ArasAuthDiagnosticEvent(
                stage=stage,
                method=method,
                origin=_origin_from_parsed(parsed),
                path=parsed.path,
                status_code=status_code,
                error_category=error_category,
            )
        )


def close_authenticated_session(session: Any) -> None:
    """Best-effort destruction of runtime authentication state."""
    if getattr(session, "is_browser_aras_session", False):
        try:
            session.close()
        except Exception:
            pass
        return
    try:
        session.headers.pop("Authorization", None)
    except Exception:
        pass
    try:
        session.cookies.clear()
    except Exception:
        pass
    try:
        session.close()
    except Exception:
        pass


def _scheme_a_safe_message(code: object) -> str:
    messages = {
        "AUTH_BROWSER_UNAVAILABLE": "Browser authentication could not be started.",
        "AUTH_CALLBACK_INVALID": "The browser authentication callback was rejected.",
        "AUTH_CALLBACK_TIMEOUT": "The browser authentication callback timed out.",
        "AUTH_SESSION_CAPABILITY_TIMEOUT": "The authenticated browser session did not become ready.",
        "AUTH_SESSION_CAPABILITY_AMBIGUOUS": "The authenticated browser session was ambiguous.",
        "AUTH_AUTHORIZATION_UNAVAILABLE": "Browser authorization was unavailable.",
        "AUTH_SOAP_GATE_FAILED": "The protected Aras session validation failed.",
        "AUTH_EXPORT_CANCELLED": "The Aras export was cancelled.",
        "AUTH_DEADLINE_EXCEEDED": "The Aras export exceeded its deadline.",
        "AUTH_CLEANUP_FAILED": "Browser authentication cleanup could not be verified.",
        "AUTH_CREDENTIALS_REJECTED": "The username or password was not accepted.",
        "INSECURE_HTTP_NOT_ALLOWED": "Password authentication over HTTP requires explicit one-time approval.",
        "INVALID_BASE_URL": "The Aras address is invalid.",
    }
    return messages.get(str(code), "Browser authentication could not be completed.")


def _scrub_http_exception_artifact(
    value: Any,
    *,
    seen: set[int] | None = None,
    depth: int = 0,
    budget: list[int] | None = None,
) -> None:
    """Erase a bounded HTTP-exception object graph in place.

    Only exceptions, response/request-shaped values, and small built-in
    containers are traversed.  Arbitrary application objects are never
    enumerated.  This also works when the exception has no traceback and when
    another caller retains the original exception or HTTP artifact.
    """
    if value is None or depth > 8:
        return
    if seen is None:
        seen = set()
    if budget is None:
        budget = [128]
    if budget[0] <= 0 or id(value) in seen:
        return
    seen.add(id(value))
    budget[0] -= 1

    is_exception = isinstance(value, BaseException)
    is_response = hasattr(value, "status_code") or (
        hasattr(value, "request")
        and any(hasattr(value, name) for name in ("content", "_content", "history"))
    )
    is_request = (
        not is_response and hasattr(value, "body") and hasattr(value, "url")
    )

    if is_exception:
        # requests exceptions expose request/response directly.  Some wrappers
        # also retain a response history or place artifacts inside nested args.
        for attribute in ("request", "response", "history"):
            try:
                nested = getattr(value, attribute)
            except Exception:
                continue
            _scrub_http_exception_artifact(
                nested,
                seen=seen,
                depth=depth + 1,
                budget=budget,
            )
        try:
            arguments = tuple(value.args)[:16]
        except Exception:
            arguments = ()
        for argument in arguments:
            _scrub_http_exception_artifact(
                argument,
                seen=seen,
                depth=depth + 1,
                budget=budget,
            )
        # Fixed ArasAuthError args are already public-safe and must remain
        # stable.  Raw transport exceptions may retain URLs/body text in args.
        if not isinstance(value, ArasAuthError):
            try:
                value.args = ()
            except Exception:
                pass
        try:
            history = getattr(value, "history")
            history.clear()
        except Exception:
            pass
        return

    if is_response:
        try:
            prepared = getattr(value, "request")
        except Exception:
            prepared = None
        _scrub_http_exception_artifact(
            prepared,
            seen=seen,
            depth=depth + 1,
            budget=budget,
        )
        try:
            response_history = tuple(getattr(value, "history"))[:16]
        except Exception:
            response_history = ()
        for historical_response in response_history:
            _scrub_http_exception_artifact(
                historical_response,
                seen=seen,
                depth=depth + 1,
                budget=budget,
            )
        for attribute, replacement in (
            ("_content", b""),
            ("content", b""),
            ("text", ""),
            ("url", ""),
        ):
            try:
                setattr(value, attribute, replacement)
            except Exception:
                pass
        for attribute in ("headers", "history", "cookies"):
            try:
                getattr(value, attribute).clear()
            except Exception:
                pass
        try:
            value.close()
        except Exception:
            pass
        return

    if is_request:
        try:
            value.body = None
        except Exception:
            pass
        try:
            value.url = ""
        except Exception:
            pass
        try:
            value.headers.clear()
        except Exception:
            pass
        return

    if isinstance(value, Mapping):
        try:
            children = tuple(value.values())[:16]
        except Exception:
            children = ()
    elif isinstance(value, (tuple, list, set, frozenset)):
        try:
            children = tuple(value)[:16]
        except Exception:
            children = ()
    else:
        return
    for child in children:
        _scrub_http_exception_artifact(
            child,
            seen=seen,
            depth=depth + 1,
            budget=budget,
        )


def _clear_auth_exception_chain(
    error: BaseException,
    *,
    active_frame: Any | None = None,
) -> None:
    """Erase traceback-held HTTP artifacts and detach every exception link.

    ``traceback.clear_frames`` cannot clear the currently executing login
    frame.  That frame is skipped here and its sensitive locals are explicitly
    overwritten by the caller's ``finally`` block.
    """
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        cause = current.__cause__
        context = current.__context__
        if cause is not None:
            pending.append(cause)
        if context is not None:
            pending.append(context)

        # Scrub direct request/response/history/args even when no traceback
        # exists.  A retained reference then observes the same cleared object.
        _scrub_http_exception_artifact(current)

        traceback_value = current.__traceback__
        cursor = traceback_value
        while cursor is not None:
            if cursor.tb_frame is not active_frame:
                try:
                    for local_value in tuple(cursor.tb_frame.f_locals.values()):
                        _scrub_http_exception_artifact(local_value)
                except Exception:
                    pass
            cursor = cursor.tb_next

        clear_from = traceback_value
        while clear_from is not None and clear_from.tb_frame is active_frame:
            clear_from = clear_from.tb_next
        if clear_from is not None:
            try:
                traceback_module.clear_frames(clear_from)
            except Exception:
                # Continue detaching even if an implementation refuses to
                # clear an executing generator/coroutine frame.
                pass
        current.__traceback__ = None
        current.__context__ = None
        current.__cause__ = None
        current.__suppress_context__ = False


def _select_login_form(html_text: str) -> _Form | None:
    parser = _FormParser()
    try:
        parser.feed(html_text)
    except Exception:
        return None
    candidates = [
        form
        for form in parser.forms
        if form.password_names or form.browser_markers or form.onsubmit
    ]
    return next((form for form in candidates if form.username_names), None) or next(
        iter(candidates),
        None,
    )


def _form_requires_browser(form: _Form, html_text: str) -> bool:
    """Conservatively refuse to place plaintext credentials in transformed forms."""
    if form.browser_markers or form.onsubmit:
        return True
    if any(form.input_types.get(name) != "password" for name in form.password_names):
        return True
    return _html_requires_browser_processing(html_text)


def _html_requires_browser_processing(html_text: str) -> bool:
    """Detect page-level credential processing despite case/spacing changes."""
    compact = "".join(str(html_text or "").casefold().split())
    return any(marker in compact for marker in _BROWSER_PROCESSING_MARKERS)


def _usable_elements(elements: Any, *, required_type: str | None = None) -> list[Any]:
    """Return controls that Selenium reports as visible, enabled, and type-safe."""
    usable: list[Any] = []
    for element in elements or []:
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue
            if required_type is not None:
                actual_type = str(element.get_attribute("type") or "").strip().casefold()
                if actual_type != required_type:
                    continue
        except Exception:
            continue
        usable.append(element)
    return usable


def _related_submitters(driver: Any, form: Any, by: Any) -> list[Any]:
    """Enumerate every submitter whose DOM ``form`` owner is the login form."""
    try:
        candidates = driver.find_elements(
            by.CSS_SELECTOR,
            "button,input[type='submit'],input[type='image']",
        )
    except Exception:
        raise ArasAuthError(
            "AUTH_FORM_INVALID",
            "The identity-provider login form could not be verified.",
            stage="browser",
        ) from None

    related: list[Any] = []
    for candidate in candidates:
        try:
            input_type = str(candidate.get_attribute("type") or "").strip().casefold()
            if input_type not in {"submit", "image"}:
                continue
            owns_form = bool(
                driver.execute_script(
                    "return arguments[0].form === arguments[1];",
                    candidate,
                    form,
                )
            )
        except Exception:
            raise ArasAuthError(
                "AUTH_FORM_INVALID",
                "The identity-provider login form could not be verified.",
                stage="browser",
            ) from None
        if owns_form:
            related.append(candidate)
    return related


def _selenium_form_requires_browser_processing(form: Any, by: Any) -> bool:
    """Detect credential transformation fields before choosing requestSubmit()."""
    try:
        fields = form.find_elements(by.CSS_SELECTOR, "input[name]")
    except Exception:
        return True
    for field_element in fields:
        try:
            name = str(field_element.get_attribute("name") or "").strip().casefold()
            input_type = str(field_element.get_attribute("type") or "").strip().casefold()
        except Exception:
            return True
        encrypted_name = any(
            marker in name for marker in ("encrypted", "cipher", "digest", "hash")
        )
        hidden_password = input_type != "password" and (
            "password" in name or name in {"pwd", "pass"}
        )
        if encrypted_name or hidden_password:
            return True
    return False


def _selenium_page_requires_browser_processing(driver: Any) -> bool:
    """Fail closed when the page source cannot be reviewed before credential entry."""
    try:
        page_source = str(driver.page_source or "")
    except Exception:
        return True
    return _html_requires_browser_processing(page_source)


def _browser_exception_category(exc: Exception) -> str:
    """Map browser exceptions to a small public, message-free taxonomy."""
    try:
        from selenium.common.exceptions import TimeoutException, WebDriverException
    except ImportError:
        return "unexpected"
    if isinstance(exc, TimeoutException):
        return "timeout"
    if isinstance(exc, WebDriverException):
        return "webdriver"
    return "unexpected"


def _callback_capture_script(callback_target: str) -> str:
    parsed = urlsplit(callback_target)
    expected_origin = _origin_from_parsed(parsed)
    expected_path = parsed.path
    return (
        "(() => { try {"
        f"const expectedOrigin={json.dumps(expected_origin)};"
        f"const expectedPath={json.dumps(expected_path)};"
        f"const memoryKey={json.dumps(_CALLBACK_MEMORY_KEY)};"
        "if (window.location.origin !== expectedOrigin || "
        "window.location.pathname !== expectedPath) { return; }"
        "const hasCallbackData=Boolean(window.location.hash || window.location.search);"
        "const capturedSearch=String(window.location.search || '');"
        "const capturedHash=String(window.location.hash || '');"
        "if (!hasCallbackData || capturedSearch.length + capturedHash.length > 32768) { return; }"
        "const captured=Object.freeze([capturedSearch,capturedHash]);"
        "Object.defineProperty(window,memoryKey,{value:captured,writable:false,configurable:true});"
        "try { window.stop(); } catch (_) {}"
        "} catch (_) {} })();"
    )


def _install_callback_capture_hook(driver: Any, callback_target: str) -> None:
    try:
        result = driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _callback_capture_script(callback_target)},
        )
    except Exception as exc:
        raise ArasAuthError(
            "AUTH_BROWSER_FAILED",
            "Browser-based authentication could not be completed.",
            stage="browser",
            substage="navigate",
            category=_browser_exception_category(exc),
        ) from None
    if not isinstance(result, Mapping) or not str(result.get("identifier", "")).strip():
        raise ArasAuthError(
            "AUTH_BROWSER_FAILED",
            "Browser-based authentication could not be completed.",
            stage="browser",
            substage="navigate",
            category="protocol",
        )


def _browser_navigation_error_category(error_text: str) -> str | None:
    """Immediately reduce a CDP navigation error to a fixed safe category."""
    lowered = str(error_text or "").casefold()
    if not lowered:
        return None
    if any(
        marker in lowered
        for marker in (
            "unsafe_port",
            "unsafe-port",
            "blocked_by_administrator",
            "blocked-by-administrator",
            "blocked_by_client",
            "blocked-by-client",
            "policy",
        )
    ):
        return "browser_policy"
    if any(marker in lowered for marker in ("proxy", "tunnel")):
        return "proxy"
    if any(
        marker in lowered
        for marker in ("name_not_resolved", "name-not-resolved", "name resolution", "dns")
    ):
        return "dns"
    if any(marker in lowered for marker in ("certificate", "cert_", "ssl", "tls")):
        return "tls"
    if any(
        marker in lowered
        for marker in (
            "timed_out",
            "timed-out",
            "timeout",
            "refused",
            "reset",
            "closed",
            "aborted",
            "unreachable",
            "internet_disconnected",
        )
    ):
        return "connect"
    return "network_unknown"


def _navigate_authorize_with_cdp(driver: Any, authorize_url: str) -> None:
    """Navigate once and discard any raw CDP network error after classification."""
    try:
        navigation_result = driver.execute_cdp_cmd("Page.navigate", {"url": authorize_url})
    except Exception as exc:
        raise ArasAuthError(
            "AUTH_BROWSER_NETWORK_FAILED",
            "The browser could not reach the authentication service.",
            stage="browser",
            substage="navigate",
            category=_browser_exception_category(exc),
        ) from None
    if not isinstance(navigation_result, Mapping):
        raise ArasAuthError(
            "AUTH_BROWSER_NETWORK_FAILED",
            "The browser could not reach the authentication service.",
            stage="browser",
            substage="navigate",
            category="protocol",
        )
    raw_error = str(navigation_result.get("errorText", "") or "")
    network_category = _browser_navigation_error_category(raw_error)
    raw_error = ""
    navigation_result = None
    if network_category is None:
        return
    if network_category == "browser_policy":
        raise ArasAuthError(
            "AUTH_BROWSER_POLICY_BLOCKED",
            "Browser policy blocked the authentication page.",
            stage="browser",
            substage="navigate",
            category="security",
        )
    raise ArasAuthError(
        "AUTH_BROWSER_NETWORK_FAILED",
        "The browser could not reach the authentication service.",
        stage="browser",
        substage="navigate",
        category="webdriver",
    )


def _read_callback_capture(driver: Any, callback_target: str) -> str | None:
    expected = urlsplit(callback_target)
    expected_origin = _origin_from_parsed(expected)
    try:
        result = driver.execute_script(
            "const expectedOrigin=arguments[0], expectedPath=arguments[1], key=arguments[2];"
            "if (window.location.origin !== expectedOrigin || "
            "window.location.pathname !== expectedPath) { return [false, '', '']; }"
            "const captured=window[key];"
            "try { delete window[key]; } catch (_) {}"
            "if (Array.isArray(captured) && captured.length === 2) {"
            "return [true, typeof captured[0] === 'string' ? captured[0] : '', "
            "typeof captured[1] === 'string' ? captured[1] : '']; }"
            "return [true, typeof captured === 'string' ? captured : ''];",
            expected_origin,
            expected.path,
            _CALLBACK_MEMORY_KEY,
        )
    except Exception as exc:
        raise ArasAuthError(
            "AUTH_BROWSER_FAILED",
            "Browser-based authentication could not be completed.",
            stage="browser",
            substage="callback_wait",
            category=_browser_exception_category(exc),
        ) from None
    if not isinstance(result, (list, tuple)) or len(result) not in {2, 3}:
        raise ArasAuthError(
            "AUTH_BROWSER_FAILED",
            "Browser-based authentication could not be completed.",
            stage="browser",
            substage="callback_wait",
            category="protocol",
        )
    if result[0] is not True:
        return None
    if len(result) == 2:
        captured = str(result[1] or "")
        invalid_single_capture = bool(captured) and captured[0] not in {"#", "?"}
        captured_search = captured if captured.startswith("?") else ""
        captured_hash = captured if captured.startswith("#") else ""
    else:
        invalid_single_capture = False
        captured_search = str(result[1] or "")
        captured_hash = str(result[2] or "")
    if (
        invalid_single_capture
        or len(captured_search) + len(captured_hash) > 32768
        or (captured_search and not captured_search.startswith("?"))
        or (captured_hash and not captured_hash.startswith("#"))
    ):
        raise ArasAuthError(
            "AUTH_BROWSER_FAILED",
            "Browser-based authentication could not be completed.",
            stage="browser",
            substage="callback_wait",
            category="protocol",
        )
    if not captured_search and not captured_hash:
        return None
    return urlunsplit(
        (
            expected.scheme,
            expected.netloc,
            expected.path,
            captured_search[1:] if captured_search else "",
            captured_hash[1:] if captured_hash else "",
        )
    )


def _looks_like_interaction(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in (
            "captcha",
            "multi-factor",
            "two-factor",
            "verification code",
            "approve sign in",
            "change password",
            "验证码",
            "多因素",
            "审批",
            "修改密码",
        )
    )


def _looks_like_credentials_rejected(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in (
            "invalid username or password",
            "incorrect username or password",
            "incorrect password",
            "authentication failed",
            "login failed",
            "用户名或密码错误",
            "用户名或密码不正确",
            "登录失败",
        )
    )


def _looks_like_html(response: Any) -> bool:
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("Content-Type", "")).casefold()
    text = str(getattr(response, "text", "") or "").lstrip().casefold()
    return "text/html" in content_type or text.startswith(("<!doctype html", "<html"))


def _location(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    return str(headers.get("Location", "") or "").strip()


def _is_callback(url: str, base_url: str) -> bool:
    candidate = urlsplit(url)
    expected = urlsplit(urljoin(base_url, CALLBACK_ROUTE))
    return (
        _origin_from_parsed(candidate) == _origin_from_parsed(expected)
        and candidate.path.rstrip("/").casefold() == expected.path.rstrip("/").casefold()
    )


def _is_exact_callback(url: str, callback_target: str) -> bool:
    candidate = urlsplit(url)
    expected = urlsplit(callback_target)
    return (
        candidate.username is None
        and candidate.password is None
        and _origin_from_parsed(candidate) == _origin_from_parsed(expected)
        and candidate.path == expected.path
    )


def _parsed_absolute(url: str, code: str, stage: str):
    try:
        parsed = urlsplit(str(url).strip())
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise ArasAuthError(code, "The supplied URL is invalid.", stage=stage, http_status=400) from exc
    if not parsed.scheme or not parsed.hostname:
        raise ArasAuthError(code, "The supplied URL is invalid.", stage=stage, http_status=400)
    return parsed


def _origin(url: str) -> str:
    return _origin_from_parsed(_parsed_absolute(url, "INVALID_BASE_URL", "transport"))


def _origin_from_parsed(parsed: Any) -> str:
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold()
    port = parsed.port
    effective = port if port is not None else (443 if scheme == "https" else 80)
    default = (scheme == "https" and effective == 443) or (scheme == "http" and effective == 80)
    return f"{scheme}://{host}" if default else f"{scheme}://{host}:{effective}"


def _strip_userinfo_fragment(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host + (f":{parsed.port}" if parsed.port is not None else "")
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path or "/", parsed.query, ""))


def _normalize_aras_app_root(base_url: str) -> str:
    cleaned = str(base_url or "").strip()
    if not cleaned:
        raise ArasAuthError(
            "INVALID_BASE_URL",
            "The Aras address is required.",
            stage="transport",
            http_status=400,
        )
    if not cleaned.endswith("/"):
        cleaned += "/"
    lowered = cleaned.casefold()
    marker = "/innovatorserver/"
    marker_index = lowered.find(marker)
    root = cleaned[: marker_index + len(marker)] if marker_index >= 0 else urljoin(cleaned, "innovatorserver/")
    parsed = _parsed_absolute(root, "INVALID_BASE_URL", "transport")
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path, "", ""))
