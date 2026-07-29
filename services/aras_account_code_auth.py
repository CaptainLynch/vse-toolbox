"""Pinned SGMW Account authorization-code authentication for ECM/Aras.

This module implements the reviewed ``B2_unique`` network contract.  It does
not execute the ECM callback JavaScript, copy cookies between clients, persist
credentials, or fall back to the legacy implicit/RSA/browser implementations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - minimal runtime only
    requests = None  # type: ignore[assignment]

from services import aras_auth as legacy_auth


ACCOUNT_ORIGIN = "https://account.sgmw.com.cn"
REALM_ISSUER = ACCOUNT_ORIGIN + "/auth/realms/common"
METADATA_URL = REALM_ISSUER + "/.well-known/openid-configuration"
AUTHORIZATION_ENDPOINT = REALM_ISSUER + "/protocol/openid-connect/auth"
TOKEN_ENDPOINT = REALM_ISSUER + "/protocol/openid-connect/token"
LOGIN_ACTION_PATH = "/auth/realms/common/login-actions/authenticate"
REALM_PATH_PREFIX = "/auth/realms/common/"
CALLBACK_PATH = "/innovatorserver/client/redirect.html"
CLIENT_ID = "ecm-front"
SCOPE = "openid"

# Anonymous, zero-credential evidence captured 2026-07-23.  A drift is a
# pre-credential contract failure, never a reason to continue optimistically.
CALLBACK_EXTERNAL_BYTES = 93_638
CALLBACK_EXTERNAL_SHA256 = (
    "E7564409C1FA50A09DDE3A9224C9515ADE72AF37B3CB3736C08BC361DD069961"
)
CALLBACK_INLINE_BYTES = 4_024
CALLBACK_INLINE_SHA256 = (
    "BA26A1A561C01A0FF340AB2A919B01A6ED844D7A05082CB00FCBF155118CA3E9"
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FORM_QUERY_KEYS = frozenset({"session_code", "execution", "client_id", "tab_id"})
_CALLBACK_VALUE_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CREDENTIAL_TRANSFORM_MARKERS = (
    "encryptedpassword",
    "encryptpassword",
    "passwordencrypt",
    "passwordcipher",
    "crypto.subtle",
)
_INTERACTIVE_MARKERS = ("recaptcha", "hcaptcha", "captcha-response")
_MAX_METADATA_BYTES = 64 * 1024
_MAX_CALLBACK_HTML_BYTES = 256 * 1024
_MAX_CALLBACK_SCRIPT_BYTES = 256 * 1024
_MAX_LOGIN_HTML_BYTES = 768 * 1024
_MAX_TOKEN_BYTES = 64 * 1024
_MAX_URL_LENGTH = 8 * 1024
_MAX_FORM_FIELDS = 64
_MAX_FIELD_NAME = 128
_MAX_FIELD_VALUE = 8 * 1024
_MAX_CALLBACK_FIELDS = 16
_MAX_TOKEN_SECONDS = 7 * 24 * 60 * 60

_state_lock = threading.Lock()
_state_digests: dict[bytes, float] = {}
_STATE_DIGEST_TTL_SECONDS = 30 * 60
_MAX_STATE_DIGESTS = 1024


@dataclass(frozen=True)
class OidcCodeContract:
    """Immutable, origin-bound form of the approved B2 contract."""

    redirect_uri: str
    account_origin: str = ACCOUNT_ORIGIN
    issuer: str = REALM_ISSUER
    metadata_url: str = METADATA_URL
    authorization_endpoint: str = AUTHORIZATION_ENDPOINT
    token_endpoint: str = TOKEN_ENDPOINT
    client_id: str = CLIENT_ID
    response_type: str = "code"
    scope: str = SCOPE


@dataclass(repr=False)
class _PasswordForm:
    action: str = field(repr=False)
    hidden: dict[str, str] = field(repr=False)
    submit_value: str = field(repr=False)


@dataclass(repr=False)
class _CallbackGrant:
    code: str = field(repr=False)
    state: str = field(repr=False)


@dataclass(repr=False)
class _ParsedForm:
    form_id: str
    action: str = field(repr=False)
    method: str
    onsubmit: str = field(repr=False)
    inputs: list[dict[str, str]] = field(default_factory=list, repr=False)


class _AccountFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_ParsedForm] = []
        self._current: _ParsedForm | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): "" if value is None else str(value) for key, value in attrs}
        lowered = tag.casefold()
        if lowered == "form":
            if self._current is not None:
                self._current = None
            self._current = _ParsedForm(
                form_id=values.get("id", "").strip(),
                action=values.get("action", "").strip(),
                method=values.get("method", "get").strip().casefold(),
                onsubmit=values.get("onsubmit", "").strip(),
            )
            self.forms.append(self._current)
            return
        if lowered in {"input", "button"} and self._current is not None:
            control = dict(values)
            control["_tag"] = lowered
            self._current.inputs.append(control)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "form":
            self._current = None


class _CallbackScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.external_sources: list[str] = []
        self.inline_scripts: list[str] = []
        self._inside_script = False
        self._current_chunks: list[str] = []
        self._current_external = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "script":
            return
        values = {str(key).casefold(): "" if value is None else str(value) for key, value in attrs}
        source = values.get("src", "").strip()
        self._inside_script = True
        self._current_chunks = []
        self._current_external = bool(source)
        if source:
            self.external_sources.append(source)

    def handle_data(self, data: str) -> None:
        if self._inside_script and not self._current_external:
            self._current_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or not self._inside_script:
            return
        if not self._current_external:
            content = "".join(self._current_chunks)
            if content.strip():
                self.inline_scripts.append(content)
        self._inside_script = False
        self._current_chunks = []
        self._current_external = False


def _new_state() -> str:
    """Create a fresh 256-bit CSPRNG state and reject an in-process replay."""
    for _attempt in range(4):
        value = secrets.token_urlsafe(32)
        digest = hashlib.sha256(value.encode("ascii", errors="strict")).digest()
        now = time.monotonic()
        with _state_lock:
            expired = [key for key, deadline in _state_digests.items() if deadline <= now]
            for key in expired:
                _state_digests.pop(key, None)
            if digest in _state_digests:
                continue
            if len(_state_digests) >= _MAX_STATE_DIGESTS:
                oldest = min(_state_digests, key=_state_digests.get)  # type: ignore[arg-type]
                _state_digests.pop(oldest, None)
            _state_digests[digest] = now + _STATE_DIGEST_TTL_SECONDS
            return value
    raise legacy_auth.ArasAuthError(
        "AUTH_STATE_GENERATION_FAILED",
        "A fresh authentication state could not be created.",
        stage="authorize",
        substage="navigate",
        category="security",
    )


class ArasAccountCodeAuthClient:
    """Establish one RAM-only Aras Bearer session using the approved code flow."""

    def __init__(
        self,
        base_url: str,
        *,
        allow_insecure_http: bool = False,
        timeout: float = 30.0,
        max_redirects: int = legacy_auth.MAX_AUTH_REDIRECTS,
        diagnostic_hook: Callable[[legacy_auth.ArasAuthDiagnosticEvent], None] | None = None,
    ) -> None:
        if requests is None:
            raise ImportError("Aras authorization-code authentication requires requests")
        self.base_url = legacy_auth._normalize_aras_app_root(base_url)
        self.policy = legacy_auth.ArasTransportPolicy(
            self.base_url, bool(allow_insecure_http)
        )
        self.timeout = max(1.0, float(timeout))
        self.max_redirects = max(
            1, min(int(max_redirects), legacy_auth.MAX_AUTH_REDIRECTS)
        )
        redirect_uri = self.policy.validate_aras_url(
            self.policy.aras_origin + CALLBACK_PATH
        )
        self.contract = OidcCodeContract(redirect_uri=redirect_uri)
        self.diagnostic_hook = diagnostic_hook
        self._credential_touched = False
        self._credential_posted = False

    def login(
        self,
        username: str,
        password: str,
        *,
        validation_item_type: str = "EWO_O",
    ) -> legacy_auth.ArasLoginResult:
        user_value = str(username or "").strip()
        password_value = str(password or "")
        username = None  # type: ignore[assignment]
        password = None  # type: ignore[assignment]
        session: Any | None = None
        expected_state: str | None = None
        authorize_url: str | None = None
        page_url: str | None = None
        html_text: str | None = None
        code_value: str | None = None
        access_token: str | None = None
        token_payload: dict[str, Any] | None = {}
        credential_response: Any | None = None
        grant: _CallbackGrant | None = None
        form: _PasswordForm | None = None
        validator: legacy_auth.ArasPasswordAuthClient | None = None
        expires_at: float | None = None
        result: legacy_auth.ArasLoginResult | None = None
        pending_error: legacy_auth.ArasAuthError | None = None
        caught_error: BaseException | None = None
        success = False
        try:
            if not user_value or not password_value:
                raise self._error(
                    "AUTH_CREDENTIALS_REQUIRED",
                    "Both username and password are required.",
                    stage="credentials",
                    http_status=400,
                    substage="form_validation",
                    category="protocol",
                )
            if _CONTROL_RE.search(user_value):
                raise self._error(
                    "AUTH_CREDENTIALS_INVALID",
                    "The username contains unsupported characters.",
                    stage="credentials",
                    http_status=400,
                    substage="form_validation",
                    category="protocol",
                )
            if validation_item_type not in {"EWO_O", "PAA_O"}:
                raise self._error(
                    "AUTH_VALIDATION_INVALID",
                    "The authentication validation target is not allowed.",
                    stage="validation",
                    http_status=400,
                    substage="session_extract",
                    category="protocol",
                )

            session = requests.Session()
            session.trust_env = False
            expected_state = _new_state()
            self._verify_metadata(session)
            self._verify_callback_contract(session)
            authorize_url = self._authorize_url(expected_state)
            page_url, html_text = self._get_login_page(session, authorize_url)
            try:
                form = self._parse_password_form(html_text, page_url)
            finally:
                html_text = ""

            credential_response = self._post_credentials_once(
                session,
                form,
                authorize_url,
                user_value,
                password_value,
            )
            # Do not retain immutable credential references beyond submission.
            user_value = None  # type: ignore[assignment]
            password_value = None  # type: ignore[assignment]
            grant = self._capture_callback(session, credential_response, form.action)
            credential_response = None
            code_value = grant.code
            grant.code = ""
            if not hmac.compare_digest(grant.state, expected_state):
                raise self._error(
                    "AUTH_STATE_MISMATCH",
                    "The identity-provider callback state did not match.",
                    stage="callback",
                    substage="session_extract",
                    category="security",
                )
            grant.state = ""
            expected_state = None

            token_payload = self._exchange_code(session, code_value)
            code_value = None
            access_token, expires_at = self._parse_token_payload(token_payload)
            token_payload.clear()
            session.headers["Authorization"] = "Bearer " + access_token
            access_token = None

            # Reuse the existing strict SOAP 1.1 ApplyItem validator.  The
            # validator client is not used for login and cannot trigger a
            # legacy authentication fallback.
            validator = legacy_auth.ArasPasswordAuthClient(
                self.base_url,
                allow_insecure_http=self.policy.allow_insecure_http,
                timeout=self.timeout,
                max_redirects=self.max_redirects,
                diagnostic_hook=self.diagnostic_hook,
            )
            validator.validate_authenticated_session(session, validation_item_type)
            success = True
            result = legacy_auth.ArasLoginResult(
                session=session,
                expires_at=expires_at,
                auth_origin=self.contract.account_origin,
            )
        except legacy_auth.ArasAuthError as exc:
            caught_error = exc
            pending_error = self._error(
                exc.code,
                exc.safe_message,
                stage=exc.stage,
                http_status=exc.http_status,
                substage=exc.substage,
                category=exc.category,
            )
        except Exception as exc:
            caught_error = exc
            pending_error = self._error(
                "AUTH_CODE_FLOW_FAILED",
                "The account authorization-code login could not be completed.",
                stage="callback" if self._credential_touched else "authorize",
                substage="session_extract" if self._credential_touched else "navigate",
                category="unexpected",
            )
        finally:
            if caught_error is not None:
                legacy_auth._clear_auth_exception_chain(
                    caught_error,
                    active_frame=sys._getframe(),
                )
            caught_error = None
            if credential_response is not None:
                self._dispose(credential_response)
            credential_response = None
            if form is not None:
                form.hidden.clear()
                form.action = ""
                form.submit_value = ""
            form = None
            if grant is not None:
                grant.code = ""
                grant.state = ""
            grant = None
            if token_payload is not None:
                token_payload.clear()
            token_payload = None
            if session is not None and not success:
                legacy_auth.close_authenticated_session(session)
                try:
                    session.headers.clear()
                except Exception:
                    pass
                try:
                    session.cookies.clear()
                except Exception:
                    pass
            session = None
            validator = None
            user_value = None  # type: ignore[assignment]
            password_value = None  # type: ignore[assignment]
            username = None  # type: ignore[assignment]
            password = None  # type: ignore[assignment]
            expected_state = None
            authorize_url = None
            page_url = None
            html_text = None
            code_value = None
            access_token = None
            expires_at = None

        # Raising here occurs with no handled exception active, so the fresh
        # fixed-field error cannot acquire the scrubbed exception as context.
        if pending_error is not None:
            error_to_raise = pending_error
            pending_error = None
            # Compatibility flag only: the real exception chain and frames
            # were scrubbed and detached before reaching this statement.
            error_to_raise.__suppress_context__ = True
            raise error_to_raise
        if result is None:  # pragma: no cover - defensive invariant
            raise self._error(
                "AUTH_CODE_FLOW_FAILED",
                "The account authorization-code login could not be completed.",
                stage="authorize",
                category="unexpected",
            )
        return result

    def _verify_metadata(self, session: Any) -> None:
        response = self._request(
            session,
            "GET",
            self.contract.metadata_url,
            stage="metadata",
            origin=self.contract.account_origin,
            path=urlsplit(self.contract.metadata_url).path,
            headers={"Accept": "application/json"},
            stream=True,
        )
        document = self._json_document(
            response,
            limit=_MAX_METADATA_BYTES,
            code="AUTH_METADATA_INVALID",
            stage="metadata",
            substage="navigate",
        )
        if (
            document.get("issuer") != self.contract.issuer
            or document.get("authorization_endpoint")
            != self.contract.authorization_endpoint
            or document.get("token_endpoint") != self.contract.token_endpoint
            or "code" not in _string_set(document.get("response_types_supported"))
            or "authorization_code"
            not in _string_set(document.get("grant_types_supported"))
        ):
            raise self._error(
                "AUTH_METADATA_INVALID",
                "The account authorization metadata did not match the approved contract.",
                stage="metadata",
                substage="navigate",
                category="security",
            )

    def _verify_callback_contract(self, session: Any) -> None:
        response = self._request(
            session,
            "GET",
            self.contract.redirect_uri,
            stage="client",
            origin=self.policy.aras_origin,
            path=CALLBACK_PATH,
            headers={"Accept": "text/html,application/xhtml+xml"},
            stream=True,
        )
        self._require_2xx(response, "AUTH_CODE_CONTRACT_UNSUPPORTED", "client")
        content_type = _header(response, "Content-Type").casefold()
        if "html" not in content_type:
            self._dispose(response)
            raise self._error(
                "AUTH_CODE_CONTRACT_UNSUPPORTED",
                "The ECM callback contract could not be verified.",
                stage="client",
                substage="navigate",
                category="protocol",
            )
        html_bytes = self._read_bounded(
            response,
            _MAX_CALLBACK_HTML_BYTES,
            "AUTH_CODE_CONTRACT_UNSUPPORTED",
            "client",
            "navigate",
        )
        try:
            html_text = html_bytes.decode("utf-8", errors="strict")
            parser = _CallbackScriptParser()
            parser.feed(html_text)
        except Exception:
            raise self._error(
                "AUTH_CODE_CONTRACT_UNSUPPORTED",
                "The ECM callback contract could not be verified.",
                stage="client",
                substage="navigate",
                category="protocol",
            ) from None
        finally:
            html_bytes = b""
            html_text = ""

        if len(parser.external_sources) != 1 or len(parser.inline_scripts) != 1:
            raise self._error(
                "AUTH_CODE_CONTRACT_UNSUPPORTED",
                "The ECM callback contract has changed and requires review.",
                stage="client",
                substage="navigate",
                category="security",
            )
        inline_bytes = parser.inline_scripts[0].encode("utf-8")
        inline_ok = (
            len(inline_bytes) == CALLBACK_INLINE_BYTES
            and hmac.compare_digest(
                hashlib.sha256(inline_bytes).hexdigest().upper(),
                CALLBACK_INLINE_SHA256,
            )
        )
        inline_bytes = b""
        if not inline_ok:
            raise self._error(
                "AUTH_CODE_CONTRACT_UNSUPPORTED",
                "The ECM callback contract has changed and requires review.",
                stage="client",
                substage="navigate",
                category="security",
            )

        script_url = urljoin(self.contract.redirect_uri, parser.external_sources[0])
        self._validate_ecm_script_url(script_url)
        script_response = self._request(
            session,
            "GET",
            script_url,
            stage="client",
            origin=self.policy.aras_origin,
            path=urlsplit(script_url).path,
            headers={"Accept": "application/javascript,text/javascript,*/*;q=0.1"},
            stream=True,
        )
        self._require_2xx(script_response, "AUTH_CODE_CONTRACT_UNSUPPORTED", "client")
        script_bytes = self._read_bounded(
            script_response,
            _MAX_CALLBACK_SCRIPT_BYTES,
            "AUTH_CODE_CONTRACT_UNSUPPORTED",
            "client",
            "navigate",
        )
        script_ok = (
            len(script_bytes) == CALLBACK_EXTERNAL_BYTES
            and hmac.compare_digest(
                hashlib.sha256(script_bytes).hexdigest().upper(),
                CALLBACK_EXTERNAL_SHA256,
            )
        )
        script_bytes = b""
        if not script_ok:
            raise self._error(
                "AUTH_CODE_CONTRACT_UNSUPPORTED",
                "The ECM callback contract has changed and requires review.",
                stage="client",
                substage="navigate",
                category="security",
            )

    def _authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.contract.client_id,
                "response_type": self.contract.response_type,
                "scope": self.contract.scope,
                "redirect_uri": self.contract.redirect_uri,
                "state": state,
            }
        )
        return self.contract.authorization_endpoint + "?" + query

    def _get_login_page(self, session: Any, authorize_url: str) -> tuple[str, str]:
        current = authorize_url
        for _hop in range(self.max_redirects + 1):
            self._validate_account_url(current, allow_authorize=True)
            response = self._request(
                session,
                "GET",
                current,
                stage="authorize",
                origin=self.contract.account_origin,
                path=urlsplit(current).path,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                },
                stream=True,
            )
            status = _status(response)
            if status in _REDIRECT_STATUSES:
                location = _header(response, "Location")
                self._dispose(response)
                current = self._safe_redirect_target(current, location, account_only=True)
                continue
            if status < 200 or status >= 300:
                self._dispose(response)
                raise self._error(
                    "AUTH_AUTHORIZE_REJECTED",
                    "The account authorization request was rejected.",
                    stage="authorize",
                    substage="navigate",
                    category="protocol",
                )
            content_type = _header(response, "Content-Type").casefold()
            if "html" not in content_type:
                self._dispose(response)
                raise self._error(
                    "AUTH_FORM_INVALID",
                    "The account login form could not be verified.",
                    stage="form",
                    substage="form_validation",
                    category="protocol",
                )
            body = self._read_bounded(
                response,
                _MAX_LOGIN_HTML_BYTES,
                "AUTH_FORM_INVALID",
                "form",
                "form_validation",
            )
            try:
                return current, body.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise self._error(
                    "AUTH_FORM_INVALID",
                    "The account login form could not be verified.",
                    stage="form",
                    substage="form_validation",
                    category="protocol",
                ) from None
            finally:
                body = b""
        raise self._error(
            "AUTH_REDIRECT_LIMIT",
            "The account authorization redirect limit was reached.",
            stage="authorize",
            substage="navigate",
            category="security",
        )

    def _parse_password_form(self, html_text: str, page_url: str) -> _PasswordForm:
        compact = "".join(html_text.casefold().split())
        if any(marker in compact for marker in _CREDENTIAL_TRANSFORM_MARKERS) or any(
            marker in compact for marker in _INTERACTIVE_MARKERS
        ):
            raise self._error(
                "AUTH_INTERACTION_REQUIRED",
                "The account login requires an unsupported interactive step.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        parser = _AccountFormParser()
        try:
            parser.feed(html_text)
        except Exception:
            raise self._error(
                "AUTH_FORM_INVALID",
                "The account login form could not be verified.",
                stage="form",
                substage="form_validation",
                category="protocol",
            ) from None

        candidates: list[_ParsedForm] = []
        for form in parser.forms:
            password_fields = [
                item
                for item in form.inputs
                if item.get("name", "").strip() == "password"
                and item.get("type", "text").casefold() == "password"
            ]
            username_fields = [
                item
                for item in form.inputs
                if item.get("name", "").strip() == "username"
                and item.get("type", "text").casefold() in {"text", "email"}
            ]
            all_password_names = [
                item for item in form.inputs if item.get("name", "").strip() == "password"
            ]
            all_username_names = [
                item for item in form.inputs if item.get("name", "").strip() == "username"
            ]
            if (
                len(password_fields) == 1
                and len(username_fields) == 1
                and len(all_password_names) == 1
                and len(all_username_names) == 1
            ):
                candidates.append(form)
        if len(candidates) != 1:
            raise self._error(
                "AUTH_FORM_INVALID",
                "A unique account password-login form was not found.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        form = candidates[0]
        if form.form_id != "kc-form-login" or form.method != "post" or form.onsubmit:
            raise self._error(
                "AUTH_FORM_INVALID",
                "The account password-login form contract was rejected.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        action = urljoin(page_url, form.action)
        self._validate_login_action(action)

        hidden: dict[str, str] = {}
        submitters: list[dict[str, str]] = []
        for item in form.inputs:
            name = item.get("name", "").strip()
            input_type = item.get("type", "text").strip().casefold()
            if input_type == "hidden" and name:
                value = item.get("value", "")
                if (
                    name in {"username", "password", "login"}
                    or
                    name in hidden
                    or len(name) > _MAX_FIELD_NAME
                    or len(value) > _MAX_FIELD_VALUE
                    or _CONTROL_RE.search(name)
                ):
                    raise self._error(
                        "AUTH_FORM_INVALID",
                        "The account login form controls were rejected.",
                        stage="form",
                        substage="form_validation",
                        category="security",
                    )
                hidden[name] = value
            if name == "login" and input_type == "submit":
                submitters.append(item)
        if len(hidden) > _MAX_FORM_FIELDS or len(submitters) != 1:
            raise self._error(
                "AUTH_FORM_INVALID",
                "The account login form controls were rejected.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        submitter = submitters[0]
        if submitter.get("formaction", "").strip() or submitter.get("formmethod", "").strip():
            raise self._error(
                "AUTH_FORM_INVALID",
                "The account login submitter contract was rejected.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        submit_value = submitter.get("value", "")
        if len(submit_value) > _MAX_FIELD_VALUE:
            raise self._error(
                "AUTH_FORM_INVALID",
                "The account login submitter contract was rejected.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        return _PasswordForm(action=action, hidden=hidden, submit_value=submit_value)

    def _post_credentials_once(
        self,
        session: Any,
        form: _PasswordForm,
        authorize_url: str,
        username: str,
        password: str,
    ) -> Any:
        if self._credential_posted:
            raise self._error(
                "AUTH_CREDENTIAL_REPLAY_BLOCKED",
                "The credential request cannot be repeated.",
                stage="credentials",
                substage="credential_submit",
                category="security",
            )
        self._validate_login_action(form.action)
        payload = dict(form.hidden)
        payload["username"] = username
        payload["password"] = password
        payload["login"] = form.submit_value
        self._credential_posted = True
        self._credential_touched = True
        try:
            return self._request(
                session,
                "POST",
                form.action,
                stage="credentials",
                origin=self.contract.account_origin,
                path=LOGIN_ACTION_PATH,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": self.contract.account_origin,
                    "Referer": authorize_url,
                },
                data=payload,
                stream=True,
            )
        finally:
            payload["password"] = ""
            payload.clear()

    def _capture_callback(
        self, session: Any, response: Any, credential_action: str
    ) -> _CallbackGrant:
        current = credential_action
        after_credential_post = True
        for _hop in range(self.max_redirects + 1):
            status = _status(response)
            if status not in _REDIRECT_STATUSES:
                self._dispose(response)
                code = (
                    "AUTH_CREDENTIALS_REJECTED"
                    if status in {200, 400, 401, 403}
                    else "AUTH_CALLBACK_INVALID"
                )
                http_status = 401 if code == "AUTH_CREDENTIALS_REJECTED" else 502
                raise self._error(
                    code,
                    "The account rejected the login or requires an additional verification step."
                    if code == "AUTH_CREDENTIALS_REJECTED"
                    else "The account callback response was invalid.",
                    stage="credentials" if code == "AUTH_CREDENTIALS_REJECTED" else "callback",
                    http_status=http_status,
                    substage="credential_submit" if code == "AUTH_CREDENTIALS_REJECTED" else "callback_wait",
                    category="protocol",
                )
            if after_credential_post and status in {307, 308}:
                self._dispose(response)
                raise self._error(
                    "AUTH_CREDENTIAL_REPLAY_BLOCKED",
                    "The account attempted to repeat the credential request.",
                    stage="callback",
                    substage="callback_wait",
                    category="security",
                )
            location = _header(response, "Location")
            self._dispose(response)
            target = self._safe_redirect_target(current, location, account_only=False)
            if self._is_exact_callback(target):
                return self._parse_callback(target)
            self._validate_account_url(target, allow_authorize=False)
            current = target
            after_credential_post = False
            response = self._request(
                session,
                "GET",
                current,
                stage="callback",
                origin=self.contract.account_origin,
                path=urlsplit(current).path,
                headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                stream=True,
            )
        self._dispose(response)
        raise self._error(
            "AUTH_REDIRECT_LIMIT",
            "The account callback redirect limit was reached.",
            stage="callback",
            substage="callback_wait",
            category="security",
        )

    def _parse_callback(self, callback_url: str) -> _CallbackGrant:
        if not self._is_exact_callback(callback_url):
            raise self._error(
                "UNTRUSTED_AUTH_REDIRECT",
                "The identity-provider callback was rejected.",
                stage="callback",
                substage="callback_wait",
                category="security",
            )
        parsed = urlsplit(callback_url)
        if parsed.fragment or len(parsed.query) > _MAX_URL_LENGTH:
            raise self._error(
                "AUTH_CALLBACK_INVALID",
                "The identity-provider callback response is invalid.",
                stage="callback",
                substage="session_extract",
                category="security",
            )
        try:
            values = parse_qs(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=_MAX_CALLBACK_FIELDS,
            )
        except (ValueError, TypeError):
            raise self._error(
                "AUTH_CALLBACK_INVALID",
                "The identity-provider callback response is invalid.",
                stage="callback",
                substage="session_extract",
                category="security",
            ) from None
        if "error" in values:
            if "code" in values:
                code = "AUTH_CALLBACK_INVALID"
                status = 502
            else:
                code = "AUTH_CREDENTIALS_REJECTED"
                status = 401
            raise self._error(
                code,
                "The identity provider rejected the login."
                if status == 401
                else "The identity-provider callback response is invalid.",
                stage="callback",
                http_status=status,
                substage="session_extract",
                category="protocol",
            )
        code_values = values.get("code", [])
        state_values = values.get("state", [])
        if len(code_values) != 1 or len(state_values) != 1:
            raise self._error(
                "AUTH_CALLBACK_INVALID",
                "The identity-provider callback code/state was invalid.",
                stage="callback",
                substage="session_extract",
                category="security",
            )
        code_value = code_values[0]
        state_value = state_values[0]
        if not _valid_callback_value(code_value, 2048) or not _valid_callback_value(
            state_value, 256
        ):
            raise self._error(
                "AUTH_CALLBACK_INVALID",
                "The identity-provider callback code/state was invalid.",
                stage="callback",
                substage="session_extract",
                category="security",
            )
        return _CallbackGrant(code=code_value, state=state_value)

    def _exchange_code(self, session: Any, code_value: str) -> dict[str, Any]:
        token_form = {
            "grant_type": "authorization_code",
            "code": code_value,
            "client_id": self.contract.client_id,
            "redirect_uri": self.contract.redirect_uri,
        }
        try:
            response = self._request(
                session,
                "POST",
                self.contract.token_endpoint,
                stage="callback",
                origin=self.contract.account_origin,
                path=urlsplit(self.contract.token_endpoint).path,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": self.policy.aras_origin,
                    "Referer": self.contract.redirect_uri,
                    "X-Requested-With": "XMLHttpRequest",
                },
                data=token_form,
                stream=True,
            )
        finally:
            token_form["code"] = ""
            token_form.clear()
        if _status(response) < 200 or _status(response) >= 300:
            self._dispose(response)
            raise self._error(
                "AUTH_TOKEN_REJECTED",
                "The identity provider rejected the authorization code.",
                stage="callback",
                substage="session_extract",
                category="protocol",
            )
        return self._json_document(
            response,
            limit=_MAX_TOKEN_BYTES,
            code="AUTH_TOKEN_INVALID",
            stage="callback",
            substage="session_extract",
        )

    def _parse_token_payload(self, payload: Mapping[str, Any]) -> tuple[str, float]:
        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        scope = payload.get("scope")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or len(access_token) > 64 * 1024
            or _CONTROL_RE.search(access_token) is not None
            or not isinstance(token_type, str)
            or token_type.casefold() != "bearer"
            or not isinstance(scope, str)
            or "openid" not in scope.split()
            or isinstance(expires_in, bool)
        ):
            raise self._error(
                "AUTH_TOKEN_INVALID",
                "The identity-provider token response was invalid.",
                stage="callback",
                substage="session_extract",
                category="protocol",
            )
        try:
            seconds = int(expires_in)
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0 or seconds > _MAX_TOKEN_SECONDS:
            raise self._error(
                "AUTH_TOKEN_INVALID",
                "The identity-provider token lifetime was invalid.",
                stage="callback",
                substage="session_extract",
                category="protocol",
            )
        return access_token, time.time() + seconds

    def _json_document(
        self,
        response: Any,
        *,
        limit: int,
        code: str,
        stage: str,
        substage: str,
    ) -> dict[str, Any]:
        if _status(response) < 200 or _status(response) >= 300:
            self._dispose(response)
            raise self._error(
                code,
                "The authentication service returned an invalid response.",
                stage=stage,
                substage=substage,
                category="protocol",
            )
        content_type = _header(response, "Content-Type").casefold()
        raw = b""
        try:
            raw = self._read_bounded(response, limit, code, stage, substage)
            if "json" not in content_type:
                raise ValueError("content type")
            document = json.loads(raw.decode("utf-8", errors="strict"))
            if not isinstance(document, dict):
                raise ValueError("not object")
            return document
        except legacy_auth.ArasAuthError:
            raise
        except Exception:
            raise self._error(
                code,
                "The authentication service returned invalid JSON.",
                stage=stage,
                substage=substage,
                category="protocol",
            ) from None
        finally:
            raw = b""

    def _request(
        self,
        session: Any,
        method: str,
        url: str,
        *,
        stage: str,
        origin: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", False)
        try:
            request_method = getattr(session, method.casefold(), None)
            if request_method is None:
                response = session.request(method, url, **kwargs)
            else:
                response = request_method(url, **kwargs)
        except Exception as exc:
            category = "timeout" if "timeout" in type(exc).__name__.casefold() else "unexpected"
            self._emit(stage, method, origin, path, error_category=category)
            raise self._error(
                "AUTH_NETWORK_FAILED",
                "The authentication service could not be reached.",
                stage=stage,
                substage="credential_submit" if stage == "credentials" else "navigate",
                category=category,
            ) from None
        self._emit(stage, method, origin, path, status_code=_status(response))
        return response

    def _read_bounded(
        self,
        response: Any,
        limit: int,
        code: str,
        stage: str,
        substage: str,
    ) -> bytes:
        chunks: list[bytes] = []
        size = 0
        try:
            iterator = getattr(response, "iter_content", None)
            if callable(iterator):
                for chunk in iterator(chunk_size=16 * 1024):
                    if not chunk:
                        continue
                    value = bytes(chunk)
                    size += len(value)
                    if size > limit:
                        raise self._error(
                            code,
                            "The authentication response exceeded its safety limit.",
                            stage=stage,
                            substage=substage,
                            category="protocol",
                        )
                    chunks.append(value)
            else:
                content = getattr(response, "content", None)
                if isinstance(content, bytes):
                    value = content
                else:
                    value = str(getattr(response, "text", "") or "").encode("utf-8")
                if len(value) > limit:
                    raise self._error(
                        code,
                        "The authentication response exceeded its safety limit.",
                        stage=stage,
                        substage=substage,
                        category="protocol",
                    )
                chunks.append(value)
            return b"".join(chunks)
        finally:
            self._dispose(response)

    def _require_2xx(self, response: Any, code: str, stage: str) -> None:
        if _status(response) < 200 or _status(response) >= 300:
            self._dispose(response)
            raise self._error(
                code,
                "The authentication contract resource was rejected.",
                stage=stage,
                substage="navigate",
                category="protocol",
            )

    def _validate_login_action(self, url: str) -> None:
        parsed = _safe_split(url)
        if (
            len(url) > _MAX_URL_LENGTH
            or parsed.scheme != "https"
            or _origin(parsed) != self.contract.account_origin
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.path != LOGIN_ACTION_PATH
        ):
            raise self._error(
                "AUTH_FORM_ORIGIN_REJECTED",
                "The account login form action was rejected.",
                stage="form",
                substage="form_validation",
                category="security",
            )
        try:
            values = parse_qs(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=8,
            )
        except (ValueError, TypeError):
            values = {}
        if set(values) != _FORM_QUERY_KEYS or any(
            len(items) != 1
            or not items[0]
            or len(items[0]) > _MAX_FIELD_VALUE
            or _CONTROL_RE.search(items[0])
            for items in values.values()
        ) or values.get("client_id") != [self.contract.client_id]:
            raise self._error(
                "AUTH_FORM_ORIGIN_REJECTED",
                "The account login form action contract was rejected.",
                stage="form",
                substage="form_validation",
                category="security",
            )

    def _validate_account_url(self, url: str, *, allow_authorize: bool) -> None:
        parsed = _safe_split(url)
        allowed_path = parsed.path.startswith(REALM_PATH_PREFIX)
        if allow_authorize and parsed.path == urlsplit(AUTHORIZATION_ENDPOINT).path:
            allowed_path = True
        if (
            len(url) > _MAX_URL_LENGTH
            or parsed.scheme != "https"
            or _origin(parsed) != self.contract.account_origin
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not allowed_path
        ):
            raise self._error(
                "UNTRUSTED_AUTH_REDIRECT",
                "The account redirect was rejected by the origin policy.",
                stage="authorize",
                substage="navigate",
                category="security",
            )

    def _validate_ecm_script_url(self, url: str) -> None:
        parsed = _safe_split(url)
        if (
            len(url) > _MAX_URL_LENGTH
            or _origin(parsed) != self.policy.aras_origin
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.casefold().startswith("/innovatorserver/")
        ):
            raise self._error(
                "AUTH_CODE_CONTRACT_UNSUPPORTED",
                "The ECM callback dependency was rejected.",
                stage="client",
                substage="navigate",
                category="security",
            )
        self.policy.validate_aras_url(url)

    def _safe_redirect_target(
        self, current: str, location: str, *, account_only: bool
    ) -> str:
        if (
            not location
            or len(location) > _MAX_URL_LENGTH
            or _CONTROL_RE.search(location)
        ):
            raise self._error(
                "AUTH_CALLBACK_INVALID",
                "The account redirect response was invalid.",
                stage="callback" if self._credential_touched else "authorize",
                substage="callback_wait" if self._credential_touched else "navigate",
                category="security",
            )
        target = urljoin(current, location)
        if account_only:
            self._validate_account_url(target, allow_authorize=True)
        elif not self._is_exact_callback(target):
            self._validate_account_url(target, allow_authorize=False)
        return target

    def _is_exact_callback(self, url: str) -> bool:
        try:
            parsed = _safe_split(url)
            expected = urlsplit(self.contract.redirect_uri)
            return (
                not parsed.username
                and not parsed.password
                and not parsed.fragment
                and _origin(parsed) == _origin(expected)
                and parsed.path == CALLBACK_PATH
            )
        except legacy_auth.ArasAuthError:
            return False

    def _dispose(self, response: Any) -> None:
        prepared = getattr(response, "request", None)
        if prepared is not None:
            try:
                prepared.body = None
            except Exception:
                pass
            try:
                prepared.url = ""
            except Exception:
                pass
            try:
                prepared.headers.clear()
            except Exception:
                pass
        try:
            response.url = ""
        except Exception:
            pass
        try:
            response.headers.clear()
        except Exception:
            pass
        try:
            response.history.clear()
        except Exception:
            pass
        try:
            response.cookies.clear()
        except Exception:
            pass
        try:
            response._content = b""
        except Exception:
            pass
        try:
            response.close()
        except Exception:
            pass

    def _emit(
        self,
        stage: str,
        method: str,
        origin: str,
        path: str,
        *,
        status_code: int | None = None,
        error_category: str | None = None,
    ) -> None:
        if self.diagnostic_hook is None:
            return
        # Only fixed, query-free contract coordinates are emitted.  Dynamic
        # form query, redirect Location, code, state, token and cookies never
        # enter diagnostics.
        safe_path = path if "?" not in path and "#" not in path else ""
        self.diagnostic_hook(
            legacy_auth.ArasAuthDiagnosticEvent(
                stage=stage,
                method=method,
                origin=origin,
                path=safe_path,
                status_code=status_code,
                error_category=error_category,
            )
        )

    def _error(
        self,
        code: str,
        safe_message: str,
        *,
        stage: str,
        http_status: int = 502,
        substage: str | None = None,
        category: str | None = None,
    ) -> legacy_auth.ArasAuthError:
        return legacy_auth.ArasAuthError(
            code,
            safe_message,
            stage=stage,
            http_status=http_status,
            substage=substage,
            category=category,
            credential_touched=self._credential_touched,
        )


def _safe_split(url: str) -> Any:
    try:
        parsed = urlsplit(str(url))
        _ = parsed.port
    except (TypeError, ValueError):
        raise legacy_auth.ArasAuthError(
            "UNTRUSTED_AUTH_REDIRECT",
            "The account URL was rejected.",
            stage="authorize",
            substage="navigate",
            category="security",
        ) from None
    if not parsed.scheme or not parsed.hostname:
        raise legacy_auth.ArasAuthError(
            "UNTRUSTED_AUTH_REDIRECT",
            "The account URL was rejected.",
            stage="authorize",
            substage="navigate",
            category="security",
        )
    return parsed


def _origin(parsed: Any) -> str:
    scheme = str(parsed.scheme).casefold()
    host = str(parsed.hostname or "").casefold()
    port = parsed.port
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    if (scheme == "https" and effective_port == 443) or (
        scheme == "http" and effective_port == 80
    ):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{effective_port}"


def _status(response: Any) -> int:
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if str(key).casefold() == name.casefold():
                return str(value or "").strip()
    return ""


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {item for item in value if isinstance(item, str)}


def _valid_callback_value(value: str, limit: int) -> bool:
    return bool(value) and len(value) <= limit and bool(_CALLBACK_VALUE_RE.fullmatch(value))


__all__ = [
    "ACCOUNT_ORIGIN",
    "AUTHORIZATION_ENDPOINT",
    "CALLBACK_PATH",
    "CLIENT_ID",
    "METADATA_URL",
    "OidcCodeContract",
    "REALM_ISSUER",
    "TOKEN_ENDPOINT",
    "ArasAccountCodeAuthClient",
]
