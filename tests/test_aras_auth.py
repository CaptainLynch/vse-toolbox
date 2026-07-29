from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

import main
import services.aras_auth as auth_service
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from services.aras_auth import (
    ArasAuthError,
    ArasPasswordAuthClient,
    ArasTransportPolicy,
    close_authenticated_session,
)


# This module retains the detailed Scheme-A (legacy implicit/browser) safety
# tests against the production private methods.  The public entry point now
# delegates exclusively to B2 and is covered in test_aras_account_code_auth.py.
_ProductionPasswordAuthClient = ArasPasswordAuthClient


class SchemeACompatibilityAuthClient(_ProductionPasswordAuthClient):
    """Test-only orchestration for the retained private Scheme-A contract."""

    def login(
        self,
        username: str,
        password: str,
        *,
        validation_item_type: str = "EWO_O",
    ):
        if not str(username or "").strip() or not str(password or ""):
            raise ArasAuthError(
                "AUTH_CREDENTIALS_REQUIRED",
                "Both username and password are required.",
                stage="credentials",
                http_status=400,
            )
        session = auth_service.requests.Session()
        session.trust_env = False
        success = False
        try:
            self._request(
                session,
                "GET",
                self._aras_url(auth_service.CLIENT_ROUTE),
                stage="client",
            )
            metadata, trusted_origins = self._discover(session)
            authorize_url, state = self._authorize_url(metadata)
            try:
                callback = self._login_with_requests(
                    session,
                    authorize_url,
                    trusted_origins,
                    username,
                    password,
                )
            except ArasAuthError as error:
                if error.code != "AUTH_BROWSER_REQUIRED":
                    raise
                callback = self._login_with_selenium(
                    authorize_url,
                    trusted_origins,
                    username,
                    password,
                )
            try:
                token, token_type, expires_at = self._parse_callback(callback, state)
            except ArasAuthError as error:
                if error.stage != "callback" or error.substage is not None:
                    raise
                raise ArasAuthError(
                    error.code,
                    error.safe_message,
                    stage=error.stage,
                    http_status=error.http_status,
                    substage="session_extract",
                    category=error.category
                    or (
                        "protocol"
                        if error.code == "AUTH_CALLBACK_INVALID"
                        else "security"
                    ),
                    credential_touched=True,
                ) from None
            session.headers["Authorization"] = token_type + " " + token
            self._validate_session(session, validation_item_type)
            success = True
            return auth_service.ArasLoginResult(
                session=session,
                expires_at=expires_at,
                auth_origin=urlsplit(authorize_url).scheme
                + "://"
                + urlsplit(authorize_url).netloc,
            )
        finally:
            username = ""
            password = ""
            if not success:
                close_authenticated_session(session)


ArasPasswordAuthClient = SchemeACompatibilityAuthClient


ARAS_HTTP = "http://aras.example/innovatorserver/"
ARAS_HTTPS = "https://aras.example/innovatorserver/"
IDP = "https://idp.example"
CALLBACK = ARAS_HTTP + "Client/OAuth/RedirectCallback"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"


def _validation_success(item_type: str) -> str:
    return (
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}">'
        f'<SOAP-ENV:Body><Result><Item type="{item_type}" id="fake-id" />'
        "</Result></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


class FakeCookies(dict):
    def clear(self) -> None:
        super().clear()


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
        json_value: object | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_value = json_value

    def json(self):  # type: ignore[no-untyped-def]
        if isinstance(self._json_value, Exception):
            raise self._json_value
        return self._json_value


class OidcSession:
    def __init__(
        self,
        *,
        state: str = "fixed-state",
        validation_status: int = 200,
        validation_text: str | None = None,
        login_location: str | None = None,
        omit_login_location: bool = False,
        login_body: str = "",
        form_action: str = IDP + "/login",
        metadata: dict[str, object] | None = None,
        authorize_html: str | None = None,
    ) -> None:
        self.state = state
        self.validation_status = validation_status
        self.validation_text = validation_text or _validation_success("EWO_O")
        self.login_location = login_location or (
            CALLBACK
            + "#access_token=fake-access-value&token_type=Bearer&state="
            + state
            + "&expires_in=60"
        )
        self.omit_login_location = omit_login_location
        self.login_body = login_body
        self.form_action = form_action
        self.authorize_html = authorize_html
        self.metadata = metadata or {
            "issuer": IDP,
            "authorization_endpoint": IDP + "/authorize",
        }
        self.headers: dict[str, str] = {}
        self.cookies = FakeCookies({"preauth": "ephemeral-cookie"})
        self.calls: list[dict[str, object]] = []
        self.closed = False
        self.trust_env = True

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "GET", "url": url, **copy.deepcopy(kwargs)})
        if url.endswith("Client/default.aspx"):
            return FakeResponse(url=url)
        if url.endswith("Server/OAuthServerDiscovery.aspx"):
            return FakeResponse(url=url, json_value={"locations": [{"uri": IDP}]})
        if url == IDP + "/.well-known/openid-configuration":
            return FakeResponse(url=url, json_value=self.metadata)
        if url.startswith(IDP + "/authorize?"):
            html = self.authorize_html or (
                '<form method="post" action="'
                + self.form_action
                + '"><input type="hidden" name="flow" value="one">'
                '<input type="text" name="username">'
                '<input type="password" name="password"></form>'
            )
            return FakeResponse(url=url, text=html, headers={"Content-Type": "text/html"})
        raise AssertionError(f"unexpected GET path: {urlsplit(url).path}")

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "POST", "url": url, **copy.deepcopy(kwargs)})
        if url == IDP + "/login":
            headers = {} if self.omit_login_location else {"Location": self.login_location}
            return FakeResponse(url=url, text=self.login_body, headers=headers)
        if url.endswith("Server/InnovatorServer.aspx"):
            return FakeResponse(
                url=url,
                status_code=self.validation_status,
                text=self.validation_text,
                headers={"Content-Type": "text/xml"},
            )
        raise AssertionError(f"unexpected POST path: {urlsplit(url).path}")

    def close(self) -> None:
        self.closed = True


def _install_oidc_session(monkeypatch, session: OidcSession) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(auth_service.requests, "Session", lambda: session)
    token_values = iter(["fixed-state", "fixed-nonce"])
    monkeypatch.setattr(auth_service.secrets, "token_urlsafe", lambda _size: next(token_values))


def test_requests_oidc_end_to_end_validates_read_session_and_cleans_on_close(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession()
    events = []
    _install_oidc_session(monkeypatch, session)

    result = ArasPasswordAuthClient(
        ARAS_HTTP,
        allow_insecure_http=True,
        diagnostic_hook=events.append,
    ).login("fake-user", "fake-password", validation_item_type="EWO_O")

    assert result.session is session
    assert result.validation == "apply_item_read"
    assert session.trust_env is False
    assert session.headers["Authorization"] == "Bearer fake-access-value"
    credential_posts = [call for call in session.calls if call["url"] == IDP + "/login"]
    assert len(credential_posts) == 1
    assert credential_posts[0]["data"] == {
        "flow": "one",
        "username": "fake-user",
        "password": "fake-password",
    }
    validation = session.calls[-1]
    assert validation["method"] == "POST"
    assert 'type="EWO_O" action="get"' in str(validation["data"])
    assert 'page="1"' in str(validation["data"])
    assert 'select="id"' in str(validation["data"])
    assert all(event.origin in {"http://aras.example", IDP} for event in events)
    assert all("fake-password" not in repr(event) for event in events)
    assert all("fake-access-value" not in repr(event) for event in events)

    close_authenticated_session(session)
    assert "Authorization" not in session.headers
    assert session.cookies == {}
    assert session.closed is True


@pytest.mark.parametrize(
    "authorize_html",
    [
        (
            '<form method="post" action="https://idp.example/login" '
            'onsubmit="return encryptPassword()">'
            '<input type="text" name="Username">'
            '<input type="password" name="Password"></form>'
        ),
        (
            '<form method="post" action="https://idp.example/login">'
            '<input type="text" name="Username">'
            '<input type="password">'
            '<input type="hidden" name="EncryptedPassword" value=""></form>'
        ),
        (
            '<form method="post" action="https://idp.example/login">'
            '<input type="text" name="Username">'
            '<input type="hidden" name="Password" value=""></form>'
        ),
        (
            '<form method="post" action="https://idp.example/login">'
            '<input type="text" name="Username">'
            '<input type="password" name="Password"></form>'
            '<script>window.CrYpTo .\n SuBtLe.encrypt();</script>'
        ),
    ],
    ids=(
        "onsubmit-transform",
        "unnamed-visible-plus-encrypted-hidden",
        "hidden-password",
        "page-crypto-case-whitespace",
    ),
)
def test_transformed_password_forms_never_receive_requests_credentials_and_fallback_once(
    monkeypatch,
    authorize_html: str,
) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession(authorize_html=authorize_html)
    _install_oidc_session(monkeypatch, session)
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)
    fallbacks: list[tuple[str, set[str], str, str]] = []

    def browser_fallback(authorize_url, trusted_origins, username, password):  # type: ignore[no-untyped-def]
        fallbacks.append((authorize_url, set(trusted_origins), username, password))
        return CALLBACK + "#access_token=fake-access-value&token_type=Bearer&state=fixed-state"

    monkeypatch.setattr(client, "_login_with_selenium", browser_fallback)

    result = client.login("fake-user", "fake-password")

    credential_posts = [
        call
        for call in session.calls
        if call["method"] == "POST" and call["url"] == IDP + "/login"
    ]
    assert credential_posts == []
    assert len(fallbacks) == 1
    assert fallbacks[0][2:] == ("fake-user", "fake-password")
    assert result.session is session
    close_authenticated_session(session)


def test_plain_visible_password_form_stays_on_requests_path_without_browser_fallback(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession()
    _install_oidc_session(monkeypatch, session)
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)

    def unexpected_browser(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("plain password form must not use browser fallback")

    monkeypatch.setattr(client, "_login_with_selenium", unexpected_browser)
    result = client.login("fake-user", "fake-password")

    credential_posts = [
        call
        for call in session.calls
        if call["method"] == "POST" and call["url"] == IDP + "/login"
    ]
    assert len(credential_posts) == 1
    assert credential_posts[0]["data"]["password"] == "fake-password"  # type: ignore[index]
    close_authenticated_session(result.session)


@pytest.mark.parametrize(
    ("status", "text", "expected_code"),
    [
        (403, "permission body should stay private", "ARAS_PERMISSION_DENIED"),
        (401, "session body should stay private", "AUTH_VALIDATION_FAILED"),
        (200, "<html>login again</html>", "AUTH_VALIDATION_FAILED"),
        (200, "not xml", "AUTH_VALIDATION_FAILED"),
    ],
)
def test_validation_failures_are_stable_and_destroy_session(
    monkeypatch, status: int, text: str, expected_code: str
) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession(validation_status=status, validation_text=text)
    _install_oidc_session(monkeypatch, session)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True).login(
            "fake-user", "fake-password"
        )

    assert excinfo.value.code == expected_code
    assert text not in str(excinfo.value)
    assert session.closed is True
    assert session.cookies == {}
    assert "Authorization" not in session.headers


def test_callback_state_mismatch_is_rejected_and_session_is_destroyed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession(state="wrong-state")
    _install_oidc_session(monkeypatch, session)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True).login(
            "fake-user", "fake-password"
        )

    assert excinfo.value.code == "AUTH_STATE_MISMATCH"
    assert session.closed is True
    assert session.cookies == {}


class ValidationSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, **copy.deepcopy(kwargs)})
        return self.response


@pytest.mark.parametrize("item_type", ["EWO_O", "PAA_O"])
def test_validation_accepts_only_expected_soap_item_and_uses_read_only_applyitem(
    item_type: str,
) -> None:
    response = FakeResponse(
        url=ARAS_HTTP + "Server/InnovatorServer.aspx",
        text=_validation_success(item_type),
        headers={"Content-Type": "text/xml"},
    )
    session = ValidationSession(response)
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)

    client._validate_session(session, item_type)

    assert len(session.calls) == 1
    request = session.calls[0]
    assert request["allow_redirects"] is False
    assert request["headers"] == {
        "Content-Type": "text/xml; charset=UTF-8",
        "SOAPAction": "ApplyItem",
    }
    body = str(request["data"])
    assert f'type="{item_type}" action="get"' in body
    for forbidden in ("add", "update", "delete", "purge", "ApplyMethod"):
        assert forbidden not in body


@pytest.mark.parametrize(
    ("status", "text", "expected_code"),
    [
        (404, _validation_success("EWO_O"), "AUTH_VALIDATION_FAILED"),
        (418, _validation_success("EWO_O"), "AUTH_VALIDATION_FAILED"),
        (
            200,
            '<Envelope><Body><Result><Item type="EWO_O" /></Result></Body></Envelope>',
            "AUTH_VALIDATION_FAILED",
        ),
        (
            200,
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"><SOAP-ENV:Body>'
            "<SOAP-ENV:Fault><faultstring>private detail</faultstring></SOAP-ENV:Fault>"
            "</SOAP-ENV:Body></SOAP-ENV:Envelope>",
            "ARAS_PERMISSION_DENIED",
        ),
        (
            200,
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"></SOAP-ENV:Envelope>',
            "AUTH_VALIDATION_FAILED",
        ),
        (
            200,
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"><SOAP-ENV:Body>'
            "<Other /></SOAP-ENV:Body></SOAP-ENV:Envelope>",
            "AUTH_VALIDATION_FAILED",
        ),
        (
            200,
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"><SOAP-ENV:Body>'
            '<Result><Item type="PAA_O" /></Result></SOAP-ENV:Body></SOAP-ENV:Envelope>',
            "AUTH_VALIDATION_FAILED",
        ),
        (
            200,
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"><SOAP-ENV:Body>'
            "<Result /></SOAP-ENV:Body></SOAP-ENV:Envelope>",
            "AUTH_VALIDATION_FAILED",
        ),
    ],
    ids=(
        "404",
        "other-4xx",
        "non-soap-xml",
        "soap-fault",
        "missing-body",
        "missing-result",
        "wrong-item-type",
        "missing-item",
    ),
)
def test_validation_rejects_every_non_authoritative_success_shape(
    status: int,
    text: str,
    expected_code: str,
) -> None:
    response = FakeResponse(
        url=ARAS_HTTP + "Server/InnovatorServer.aspx",
        status_code=status,
        text=text,
        headers={"Content-Type": "text/xml"},
    )
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)

    with pytest.raises(ArasAuthError) as excinfo:
        client._validate_session(ValidationSession(response), "EWO_O")

    assert excinfo.value.code == expected_code
    assert "private detail" not in str(excinfo.value)


def test_rejected_credentials_do_not_echo_response_body_or_retry_in_client(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    private_body = "rejected credentials: " + "fake-password"
    session = OidcSession(omit_login_location=True, login_body=private_body)
    _install_oidc_session(monkeypatch, session)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True).login(
            "fake-user", "fake-password"
        )

    assert excinfo.value.code == "AUTH_CREDENTIALS_REJECTED"
    assert private_body not in str(excinfo.value)
    assert "fake-password" not in str(excinfo.value)
    assert len([call for call in session.calls if call["url"] == IDP + "/login"]) == 1
    assert session.closed is True


def test_transport_policy_defaults_to_refusing_http_and_allows_only_approved_origin() -> None:
    with pytest.raises(ArasAuthError) as excinfo:
        ArasTransportPolicy(ARAS_HTTP)
    assert excinfo.value.code == "INSECURE_HTTP_NOT_ALLOWED"

    policy = ArasTransportPolicy(ARAS_HTTP, allow_insecure_http=True)
    assert policy.validate_aras_url(ARAS_HTTP + "Server/InnovatorServer.aspx").startswith(
        ARAS_HTTP
    )
    for candidate in (
        "http://other.example/innovatorserver/Server/InnovatorServer.aspx",
        "http://aras.example:8080/innovatorserver/Server/InnovatorServer.aspx",
        "http://user:pass@aras.example/innovatorserver/Server/InnovatorServer.aspx",
        "http://aras.example.evil/innovatorserver/Server/InnovatorServer.aspx",
    ):
        with pytest.raises(ArasAuthError) as rejected:
            policy.validate_aras_url(candidate)
        assert rejected.value.code == "INSECURE_HTTP_HOST_MISMATCH"


def test_auth_redirect_policy_rejects_cross_host_http_and_https_downgrade() -> None:
    policy = ArasTransportPolicy(ARAS_HTTPS)
    trusted = {"https://aras.example", IDP}
    assert policy.validate_auth_url(IDP + "/authorize", trusted, code="UNTRUSTED")

    for candidate in (
        "https://other.example/authorize",
        "http://idp.example/authorize",
        "http://aras.example/innovatorserver/Client/OAuth/RedirectCallback",
    ):
        with pytest.raises(ArasAuthError) as excinfo:
            policy.validate_auth_url(candidate, trusted, code="UNTRUSTED_AUTH_REDIRECT")
        assert excinfo.value.code == "UNTRUSTED_AUTH_REDIRECT"


def test_metadata_issuer_and_unrelated_endpoints_never_expand_credential_origins() -> None:
    session = OidcSession(
        metadata={
            "issuer": "https://malicious-issuer.example",
            "authorization_endpoint": IDP + "/authorize",
            "token_endpoint": "https://malicious-token.example/token",
            "userinfo_endpoint": "https://malicious-userinfo.example/user",
            "end_session_endpoint": "http://malicious-http.example/logout",
        }
    )
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)

    metadata, trusted = client._discover(session)

    assert metadata["authorization_endpoint"] == IDP + "/authorize"
    assert trusted == {"http://aras.example", IDP}
    assert all("malicious" not in origin for origin in trusted)


def test_metadata_authorization_endpoint_must_be_https_or_exact_approved_aras_origin() -> None:
    session = OidcSession(
        metadata={
            "issuer": IDP,
            "authorization_endpoint": "http://idp.example/authorize",
        }
    )
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)

    with pytest.raises(ArasAuthError) as excinfo:
        client._discover(session)

    assert excinfo.value.code == "AUTH_METADATA_INVALID"


def test_untrusted_login_form_action_is_rejected_before_credentials_are_sent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession(form_action="https://untrusted.example/collect")
    _install_oidc_session(monkeypatch, session)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True).login(
            "fake-user", "fake-password"
        )

    assert excinfo.value.code == "AUTH_METADATA_INVALID" or excinfo.value.code == "AUTH_FORM_ORIGIN_REJECTED"
    assert not any(call["method"] == "POST" and "untrusted" in str(call["url"]) for call in session.calls)
    assert session.closed is True


def test_authorize_redirect_loop_stops_at_configured_limit_without_posting_credentials() -> None:
    class RedirectLoopSession:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url: str, **_kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            return FakeResponse(url=url, status_code=302, headers={"Location": "/authorize"})

    session = RedirectLoopSession()
    client = ArasPasswordAuthClient(ARAS_HTTPS, max_redirects=2)

    with pytest.raises(ArasAuthError) as excinfo:
        client._login_with_requests(
            session,
            IDP + "/authorize",
            {"https://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_REDIRECT_LIMIT"
    assert session.calls == 3


def test_cli_submits_credentials_once_and_never_retries_failures(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    attempts: list[tuple[str, str]] = []

    class RejectingAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, username: str, password: str, **_kwargs):  # type: ignore[no-untyped-def]
            attempts.append((username, password))
            raise ArasAuthError(
                "AUTH_CREDENTIALS_REJECTED",
                "Credentials were rejected.",
                stage="credentials",
                http_status=401,
            )

    answers = iter(["fake-user-1", "fake-password-1"])
    monkeypatch.setattr(main, "ArasPasswordAuthClient", RejectingAuth)
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: next(answers))
    with pytest.raises(ArasAuthError):
        main._login_aras_with_password("https://aras.example", "EWO_O")
    assert len(attempts) == 1

    attempts.clear()

    class TransportFailure(RejectingAuth):
        def login(self, username: str, password: str, **_kwargs):  # type: ignore[no-untyped-def]
            attempts.append((username, password))
            raise ArasAuthError(
                "AUTH_NETWORK_FAILED",
                "Authentication service unavailable.",
                stage="authorize",
            )

    answers = iter(["fake-user", "fake-password"])
    monkeypatch.setattr(main, "ArasPasswordAuthClient", TransportFailure)
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: next(answers))
    with pytest.raises(ArasAuthError):
        main._login_aras_with_password("https://aras.example", "EWO_O")
    assert len(attempts) == 1


def test_cli_internal_requests_to_browser_switch_uses_one_credential_prompt_cycle(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    prompt_labels: list[str] = []
    answers = iter(["fake-user", "fake-password"])
    auth_transitions: list[str] = []
    session = SimpleNamespace()
    crawler = SimpleNamespace(session=session)

    class BrowserSwitchingAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, _username: str, _password: str, **_kwargs):  # type: ignore[no-untyped-def]
            auth_transitions.extend(["requests", "browser"])
            return SimpleNamespace(session=session)

    def prompt(prompt_text: str, **_kwargs):  # type: ignore[no-untyped-def]
        prompt_labels.append(str(prompt_text))
        return next(answers)

    monkeypatch.setattr(main, "ArasPasswordAuthClient", BrowserSwitchingAuth)
    monkeypatch.setattr(main, "ArasCrawlerClient", lambda *_args, **_kwargs: crawler)
    monkeypatch.setattr(main.Prompt, "ask", prompt)

    result = main._login_aras_with_password(ARAS_HTTPS, "EWO_O")

    assert result is crawler
    assert auth_transitions == ["requests", "browser"]
    assert prompt_labels == ["Aras 用户名", "Aras 密码"]


def test_cli_http_confirmation_defaults_to_refusal_before_prompting_for_credentials(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    prompts: list[str] = []
    monkeypatch.setattr(main.Confirm, "ask", lambda *_args, **kwargs: kwargs.get("default"))
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda prompt, **_kwargs: prompts.append(str(prompt)) or "should-not-be-used",
    )

    with pytest.raises(RuntimeError, match="INSECURE_HTTP_NOT_ALLOWED"):
        main._login_aras_with_password(ARAS_HTTP, "EWO_O")

    assert prompts == []


def test_selenium_fallback_touches_only_visible_enabled_controls_clicks_submit_and_cleans_up(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    callback = CALLBACK + "#access_token=fake&token_type=Bearer&state=fixed-state"
    profile = tmp_path / "ephemeral-browser-profile"
    cleanup: list[object] = []

    class FakeOptions:
        def add_argument(self, value: str) -> None:
            cleanup.append(("option", value))

        def set_capability(self, *_args) -> None:  # type: ignore[no-untyped-def]
            pass

    class FakeInput:
        def __init__(
            self,
            driver,
            label: str,
            input_type: str,
            *,
            displayed: bool = True,
            enabled: bool = True,
        ) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver
            self.label = label
            self.input_type = input_type
            self.displayed = displayed
            self.enabled = enabled
            self.form = None

        def is_displayed(self) -> bool:
            return self.displayed

        def is_enabled(self) -> bool:
            return self.enabled

        def get_attribute(self, name: str) -> str:
            return self.input_type if name == "type" else ""

        def clear(self) -> None:
            cleanup.append(("clear", self.label))

        def send_keys(self, value: str) -> None:
            cleanup.append(("send_keys", self.label, value))

        def find_element(self, *_args):  # type: ignore[no-untyped-def]
            return self.form

    class FakeSubmit:
        def __init__(self, driver, label: str, *, displayed: bool = True) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver
            self.label = label
            self.displayed = displayed

        def is_displayed(self) -> bool:
            return self.displayed

        def is_enabled(self) -> bool:
            return True

        def get_attribute(self, name: str) -> str:
            return {"type": "submit", "formmethod": "", "formaction": ""}.get(name, "")

        def click(self) -> None:
            cleanup.append(("click", self.label))
            self.driver.current_url = callback

    class FakeForm:
        def __init__(self, driver) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver

        def get_attribute(self, name: str) -> str:
            return {"method": "post", "action": IDP + "/login"}.get(name, "")

        def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
            if selector == "input[type='password']":
                return [
                    self.driver.hidden_password,
                    self.driver.disabled_password,
                    self.driver.password_input,
                ]
            if "button[type='submit']" in selector:
                return [self.driver.hidden_submit, self.driver.submit]
            return [self.driver.username_input]

    class FakeDriver:
        def __init__(self) -> None:
            self.current_url = IDP + "/authorize"
            self.username_input = FakeInput(self, "username", "text")
            self.password_input = FakeInput(self, "visible-password", "password")
            self.hidden_password = FakeInput(
                self, "hidden-password", "password", displayed=False
            )
            self.disabled_password = FakeInput(
                self, "disabled-password", "password", enabled=False
            )
            self.submit = FakeSubmit(self, "visible-submit")
            self.hidden_submit = FakeSubmit(self, "hidden-submit", displayed=False)
            self.form = FakeForm(self)
            for element in (
                self.password_input,
                self.hidden_password,
                self.disabled_password,
            ):
                element.form = self.form

        def set_page_load_timeout(self, _timeout: float) -> None:
            pass

        def get(self, url: str) -> None:
            self.current_url = url

        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            cleanup.append(("cdp", command, params))
            if command == "Page.navigate":
                self.current_url = params["url"]
                return {"frameId": "authorize-frame"}
            return {"identifier": "callback-capture"}

        def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
            if "password" in selector:
                return [self.hidden_password, self.disabled_password, self.password_input]
            if selector == "button,input[type='submit'],input[type='image']":
                return [self.hidden_submit, self.submit]
            return []

        def execute_script(self, script: str, *args):  # type: ignore[no-untyped-def]
            if "const expectedOrigin=arguments[0]" in script:
                return [False, ""]
            if "arguments[0].form === arguments[1]" in script:
                return args[0] in {self.hidden_submit, self.submit} and args[1] is self.form
            cleanup.append(("script", script))
            return None

        def delete_all_cookies(self) -> None:
            cleanup.append("cookies")

        def quit(self) -> None:
            cleanup.append("quit")

    class FakeWait:
        def __init__(self, driver, _timeout: float) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver

        def until(self, predicate):  # type: ignore[no-untyped-def]
            return predicate(self.driver)

    driver = FakeDriver()
    monkeypatch.setattr(auth_service.tempfile, "mkdtemp", lambda **_kwargs: str(profile))
    monkeypatch.setattr(auth_service.shutil, "rmtree", lambda path, **_kwargs: cleanup.append(("rmtree", Path(path))))
    monkeypatch.setattr(auth_service.time, "sleep", lambda _seconds: None)
    browser_constructors: list[str] = []

    def construct_chrome(**_kwargs):  # type: ignore[no-untyped-def]
        browser_constructors.append("chrome")
        return driver

    def reject_edge(**_kwargs):  # type: ignore[no-untyped-def]
        browser_constructors.append("edge")
        raise AssertionError("Edge fallback must not run after Chrome success")

    monkeypatch.setattr("selenium.webdriver.ChromeOptions", FakeOptions)
    monkeypatch.setattr("selenium.webdriver.Chrome", construct_chrome)
    monkeypatch.setattr("selenium.webdriver.Edge", reject_edge)
    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", FakeWait)

    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)
    result = client._login_with_selenium(
        IDP + "/authorize",
        {"http://aras.example", IDP},
        "fake-user",
        "fake-password",
    )

    assert result == callback
    assert any(item[0] == "script" and "localStorage.clear" in item[1] for item in cleanup if isinstance(item, tuple))
    assert "cookies" in cleanup
    assert "quit" in cleanup
    assert ("clear", "username") in cleanup
    assert ("clear", "visible-password") in cleanup
    assert not any(
        isinstance(item, tuple)
        and item[0] in {"clear", "send_keys"}
        and item[1] in {"hidden-password", "disabled-password"}
        for item in cleanup
    )
    assert ("click", "visible-submit") in cleanup
    assert ("click", "hidden-submit") not in cleanup
    assert "submit" not in cleanup
    assert ("rmtree", profile) in cleanup
    assert browser_constructors == ["chrome"]


class _ScenarioElement:
    def __init__(
        self,
        driver,
        label: str,
        attributes: dict[str, str],
        *,
        displayed: bool = True,
        enabled: bool = True,
        owner=None,
    ) -> None:  # type: ignore[no-untyped-def]
        self.driver = driver
        self.label = label
        self.attributes = attributes
        self.displayed = displayed
        self.enabled = enabled
        self.owner = owner

    def is_displayed(self) -> bool:
        return self.displayed

    def is_enabled(self) -> bool:
        return self.enabled

    def get_attribute(self, name: str) -> str:
        return self.attributes.get(name, "")

    def find_element(self, *_args):  # type: ignore[no-untyped-def]
        return self.owner

    def clear(self) -> None:
        self.driver.events.append(("clear", self.label))

    def send_keys(self, _value: str) -> None:
        self.driver.events.append(("send_keys", self.label))

    def click(self) -> None:
        self.driver.events.append(("click", self.label))
        self.driver.current_url = self.driver.callback


class _ScenarioForm:
    def __init__(
        self,
        driver,
        *,
        onsubmit: str = "",
        marker_fields: list[_ScenarioElement] | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        self.driver = driver
        self.onsubmit = onsubmit
        self.marker_fields = marker_fields or []

    def get_attribute(self, name: str) -> str:
        return {
            "method": "post",
            "action": IDP + "/login",
            "onsubmit": self.onsubmit,
        }.get(name, "")

    def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
        self.driver.events.append(("form-find", selector))
        if selector == "input[type='password']":
            return [self.driver.password]
        if selector == "input[name]":
            return self.marker_fields
        return [self.driver.username]


class _ScenarioDriver:
    def __init__(
        self,
        *,
        submitter_specs: list[dict[str, object]] | None = None,
        onsubmit: str = "",
        marker_specs: list[dict[str, str]] | None = None,
        request_submit_supported: bool = True,
        page_source: str = "",
    ) -> None:
        self.current_url = IDP + "/authorize"
        self.page_source = page_source
        self.callback = CALLBACK + "#access_token=fake&token_type=Bearer&state=fixed-state"
        self.events: list[tuple[str, str]] = []
        self.request_submit_supported = request_submit_supported
        marker_fields = [
            _ScenarioElement(self, f"marker-{index}", spec)
            for index, spec in enumerate(marker_specs or [])
        ]
        self.form = _ScenarioForm(self, onsubmit=onsubmit, marker_fields=marker_fields)
        self.username = _ScenarioElement(self, "username", {"type": "text"}, owner=self.form)
        self.password = _ScenarioElement(
            self, "password", {"type": "password"}, owner=self.form
        )
        self.submitters = []
        for index, spec in enumerate(submitter_specs or []):
            attributes = {
                "type": str(spec.get("type", "submit")),
                "formaction": str(spec.get("formaction", "")),
                "formmethod": str(spec.get("formmethod", "")),
            }
            owner = self.form if spec.get("owns_form", True) else object()
            self.submitters.append(
                _ScenarioElement(
                    self,
                    str(spec.get("label", f"submitter-{index}")),
                    attributes,
                    displayed=bool(spec.get("displayed", True)),
                    enabled=bool(spec.get("enabled", True)),
                    owner=owner,
                )
            )

    def set_page_load_timeout(self, _timeout: float) -> None:
        pass

    def get(self, url: str) -> None:
        self.events.append(("get", url))
        self.current_url = url

    def execute_cdp_cmd(self, command: str, params: dict[str, str]):
        self.events.append(("cdp", command))
        if command == "Page.addScriptToEvaluateOnNewDocument":
            assert "source" in params
            return {"identifier": "callback-capture"}
        assert command == "Page.navigate"
        assert params == {"url": IDP + "/authorize"} or params["url"].startswith(
            IDP + "/authorize?"
        )
        self.current_url = params["url"]
        return {"frameId": "authorize-frame"}

    def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
        if selector == "input[type='password']":
            return [self.password]
        if selector == "button,input[type='submit'],input[type='image']":
            self.events.append(("enumerate-submitters", "all"))
            return self.submitters
        return []

    def execute_script(self, script: str, *args):  # type: ignore[no-untyped-def]
        if "const expectedOrigin=arguments[0]" in script:
            self.events.append(("callback-read", "memory"))
            return [False, ""]
        if "arguments[0].form === arguments[1]" in script:
            self.events.append(("check-form-owner", args[0].label))
            return args[0].owner is args[1]
        if "typeof arguments[0].requestSubmit" in script:
            self.events.append(("request-submit-check", "form"))
            return self.request_submit_supported
        if "arguments[0].requestSubmit();" in script:
            self.events.append(("request-submit", "submit-event"))
            self.current_url = self.callback
            return None
        self.events.append(("cleanup", "storage"))
        return None

    def delete_all_cookies(self) -> None:
        self.events.append(("cleanup", "cookies"))

    def quit(self) -> None:
        self.events.append(("cleanup", "driver"))


def _install_selenium_scenario(monkeypatch, tmp_path, driver: _ScenarioDriver) -> None:  # type: ignore[no-untyped-def]
    class Options:
        def add_argument(self, _value: str) -> None:
            pass

        def set_capability(self, *_args) -> None:  # type: ignore[no-untyped-def]
            pass

    class Wait:
        def __init__(self, scenario, _timeout: float) -> None:  # type: ignore[no-untyped-def]
            self.scenario = scenario

        def until(self, predicate):  # type: ignore[no-untyped-def]
            return predicate(self.scenario)

    monkeypatch.setattr(
        auth_service.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / "submitter-scenario-profile"),
    )
    monkeypatch.setattr(auth_service.shutil, "rmtree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auth_service.time, "sleep", lambda _seconds: None)
    def construct_chrome(**_kwargs):  # type: ignore[no-untyped-def]
        assert not any(event == ("construct", "edge") for event in driver.events)
        driver.events.append(("construct", "chrome"))
        return driver

    def reject_edge(**_kwargs):  # type: ignore[no-untyped-def]
        driver.events.append(("construct", "edge"))
        raise AssertionError("Edge fallback must not run after Chrome success")

    monkeypatch.setattr("selenium.webdriver.ChromeOptions", Options)
    monkeypatch.setattr("selenium.webdriver.Chrome", construct_chrome)
    monkeypatch.setattr("selenium.webdriver.Edge", reject_edge)
    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", Wait)


def _assert_chrome_only(events: list[tuple[str, str]]) -> None:
    assert events.count(("construct", "chrome")) == 1
    assert ("construct", "edge") not in events


class _ProductionCallbackSubmitter(_ScenarioElement):
    def click(self) -> None:
        self.driver.events.append(("click", self.label))
        self.driver.complete_callback_navigation()


class _ProductionCallbackFlowDriver(_ScenarioDriver):
    """Stateful fake exercising the production Selenium callback control flow."""

    def __init__(
        self,
        *,
        captured_search: str = "",
        captured_hash: str = "",
        landing_url: str = CALLBACK,
    ) -> None:
        super().__init__()
        self.captured_search = captured_search
        self.captured_hash = captured_hash
        self.landing_url = landing_url
        self.callback_memory: tuple[str, str] | None = None
        self.submitters = [
            _ProductionCallbackSubmitter(
                self,
                "safe-production-submitter",
                {
                    "type": "submit",
                    "formaction": IDP + "/login",
                    "formmethod": "post",
                },
                owner=self.form,
            )
        ]

    def complete_callback_navigation(self) -> None:
        full_landing = self.landing_url + self.captured_search + self.captured_hash
        self.current_url = full_landing
        if auth_service._is_exact_callback(full_landing, CALLBACK):
            self.callback_memory = (self.captured_search, self.captured_hash)
            channel_mask = (
                ("search" if self.captured_search else "")
                + ("+" if self.captured_search and self.captured_hash else "")
                + ("hash" if self.captured_hash else "")
            )
            self.events.append(("document-start-capture", channel_mask))
        else:
            self.events.append(("document-start-skip", "wrong-origin-or-path"))
        # Simulate callback-page code clearing both channels immediately.
        parsed = urlsplit(full_landing)
        self.current_url = auth_service.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        )
        self.events.append(("replace-state-clear", "search+hash"))

    def execute_script(self, script: str, *args):  # type: ignore[no-untyped-def]
        if "const expectedOrigin=arguments[0]" in script:
            touched = any(
                event[0] in {"clear", "send_keys", "click", "request-submit"}
                for event in self.events
            )
            phase = "post-submit" if touched else "pre-touch-health"
            if not auth_service._is_exact_callback(self.current_url, CALLBACK):
                self.events.append(("callback-read-rejected", phase))
                return [False, "", ""]
            captured = self.callback_memory
            self.callback_memory = None
            self.events.append(("callback-read-once", phase))
            if captured is None:
                return [True, "", ""]
            return [True, captured[0], captured[1]]
        if "delete window[arguments[0]]" in script:
            state = "already-deleted" if self.callback_memory is None else "present"
            self.events.append(("cleanup-memory", state))
            self.callback_memory = None
            return None
        return super().execute_script(script, *args)

    def find_element(self, *_args):  # type: ignore[no-untyped-def]
        return SimpleNamespace(text="")


def _browser_processing_oidc_session() -> OidcSession:
    return OidcSession(
        authorize_html=(
            '<form method="post" action="https://idp.example/login" '
            'onsubmit="return encryptPassword()">'
            '<input type="text" name="Username">'
            '<input type="password" name="Password"></form>'
        )
    )


@pytest.mark.parametrize(
    ("captured_search", "captured_hash", "channel_mask"),
    [
        (
            "",
            "#access_token=synthetic-fragment&token_type=Bearer&state=fixed-state",
            "hash",
        ),
        (
            "?access_token=synthetic-query&token_type=Bearer&state=fixed-state",
            "",
            "search",
        ),
    ],
    ids=("fragment", "query"),
)
def test_full_production_browser_control_flow_captures_cleared_single_channel_and_authenticates(
    monkeypatch,
    tmp_path,
    captured_search: str,
    captured_hash: str,
    channel_mask: str,
) -> None:  # type: ignore[no-untyped-def]
    session = _browser_processing_oidc_session()
    driver = _ProductionCallbackFlowDriver(
        captured_search=captured_search,
        captured_hash=captured_hash,
    )
    _install_oidc_session(monkeypatch, session)
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    result = ArasPasswordAuthClient(
        ARAS_HTTP, allow_insecure_http=True
    ).login("synthetic-user", "synthetic-password")

    event_names = [event[0] for event in driver.events]
    hook_index = driver.events.index(("cdp", "Page.addScriptToEvaluateOnNewDocument"))
    navigate_index = driver.events.index(("cdp", "Page.navigate"))
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert hook_index < navigate_index
    assert navigate_index < event_names.index("callback-read-rejected")
    assert event_names.index("callback-read-rejected") < event_names.index("clear")
    assert event_names.index("clear") < event_names.index("click")
    assert event_names.index("click") < event_names.index("document-start-capture")
    assert event_names.index("document-start-capture") < event_names.index("replace-state-clear")
    assert event_names.index("replace-state-clear") < event_names.index("callback-read-once")
    assert ("document-start-capture", channel_mask) in driver.events
    assert ("callback-read-once", "post-submit") in driver.events
    assert ("cleanup-memory", "already-deleted") in driver.events
    assert driver.callback_memory is None
    _assert_chrome_only(driver.events)
    assert result.session is session
    assert session.headers["Authorization"].startswith("Bearer synthetic-")
    assert session.calls[-1]["url"].endswith("Server/InnovatorServer.aspx")
    close_authenticated_session(result.session)


def test_full_production_browser_control_flow_preserves_both_channels_and_rejects_ambiguity(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    session = _browser_processing_oidc_session()
    driver = _ProductionCallbackFlowDriver(
        captured_search=(
            "?access_token=synthetic-query&token_type=Bearer&state=fixed-state"
        ),
        captured_hash=(
            "#access_token=synthetic-fragment&token_type=Bearer&state=fixed-state"
        ),
    )
    _install_oidc_session(monkeypatch, session)
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(
            ARAS_HTTP, allow_insecure_http=True
        ).login("synthetic-user", "synthetic-password")

    event_names = [event[0] for event in driver.events]
    hook_index = driver.events.index(("cdp", "Page.addScriptToEvaluateOnNewDocument"))
    navigate_index = driver.events.index(("cdp", "Page.navigate"))
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert hook_index < navigate_index
    assert navigate_index < event_names.index("callback-read-rejected")
    assert event_names.index("callback-read-rejected") < event_names.index("clear")
    assert event_names.index("clear") < event_names.index("click")
    assert event_names.index("click") < event_names.index("document-start-capture")
    assert event_names.index("document-start-capture") < event_names.index("replace-state-clear")
    assert event_names.index("replace-state-clear") < event_names.index("callback-read-once")
    assert ("document-start-capture", "search+hash") in driver.events
    assert ("callback-read-once", "post-submit") in driver.events
    assert ("cleanup-memory", "already-deleted") in driver.events
    assert driver.callback_memory is None
    _assert_chrome_only(driver.events)
    assert excinfo.value.code == "AUTH_CALLBACK_INVALID"
    assert excinfo.value.substage == "session_extract"
    assert excinfo.value.category == "protocol"
    assert session.closed is True
    assert session.cookies == {}
    assert "Authorization" not in session.headers


@pytest.mark.parametrize(
    ("landing_url", "expected_code", "expected_category"),
    [
        (
            "https://untrusted.invalid/not-a-callback",
            "UNTRUSTED_AUTH_REDIRECT",
            "security",
        ),
        (
            CALLBACK + "-wrong-path",
            "AUTH_BROWSER_FAILED",
            "timeout",
        ),
    ],
    ids=("wrong-origin", "wrong-path"),
)
def test_full_production_browser_control_flow_never_reads_wrong_origin_or_path_capture(
    monkeypatch,
    tmp_path,
    landing_url: str,
    expected_code: str,
    expected_category: str,
) -> None:  # type: ignore[no-untyped-def]
    session = _browser_processing_oidc_session()
    driver = _ProductionCallbackFlowDriver(
        captured_hash=(
            "#access_token=must-not-be-read&token_type=Bearer&state=fixed-state"
        ),
        landing_url=landing_url,
    )
    _install_oidc_session(monkeypatch, session)
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(
            ARAS_HTTP,
            allow_insecure_http=True,
            timeout=1,
        ).login("synthetic-user", "synthetic-password")

    post_submit_rejections = [
        event
        for event in driver.events
        if event == ("callback-read-rejected", "post-submit")
    ]
    assert ("document-start-skip", "wrong-origin-or-path") in driver.events
    assert post_submit_rejections
    assert not any(event[0] == "document-start-capture" for event in driver.events)
    assert not any(event[0] == "callback-read-once" for event in driver.events)
    assert driver.callback_memory is None
    _assert_chrome_only(driver.events)
    assert excinfo.value.code == expected_code
    assert excinfo.value.substage == "callback_wait"
    assert excinfo.value.category == expected_category
    assert session.closed is True
    assert session.cookies == {}
    assert "Authorization" not in session.headers


@pytest.mark.parametrize(
    ("malicious_spec", "expected_code"),
    [
        (
            {
                "label": "external-cross-origin",
                "formaction": "https://evil.example/collect",
                "owns_form": True,
            },
            "AUTH_FORM_ORIGIN_REJECTED",
        ),
        (
            {"label": "external-get", "formmethod": "get", "owns_form": True},
            "AUTH_FORM_INVALID",
        ),
        (
            {
                "label": "hidden-evil-default",
                "displayed": False,
                "formaction": "https://evil.example/collect",
            },
            "AUTH_FORM_ORIGIN_REJECTED",
        ),
        (
            {
                "label": "disabled-evil-default",
                "enabled": False,
                "formmethod": "get",
            },
            "AUTH_FORM_INVALID",
        ),
    ],
    ids=("external-formaction", "external-formmethod", "hidden-default", "disabled-default"),
)
def test_every_related_submitter_is_validated_before_any_credential_touch(
    monkeypatch,
    tmp_path,
    malicious_spec: dict[str, object],
    expected_code: str,
) -> None:  # type: ignore[no-untyped-def]
    driver = _ScenarioDriver(
        submitter_specs=[
            {"label": "safe-visible", "formaction": IDP + "/login", "formmethod": "post"},
            malicious_spec,
        ]
    )
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == expected_code
    assert ("enumerate-submitters", "all") in driver.events
    assert not any(event[0] in {"clear", "send_keys", "click", "request-submit"} for event in driver.events)
    assert {("cleanup", "storage"), ("cleanup", "cookies"), ("cleanup", "driver")}.issubset(
        driver.events
    )
    _assert_chrome_only(driver.events)


@pytest.mark.parametrize(
    ("onsubmit", "marker_specs"),
    [
        ("return encryptPassword()", []),
        ("", [{"name": "EncryptedPassword", "type": "hidden"}]),
        ("", [{"name": "Password", "type": "hidden"}]),
    ],
    ids=("onsubmit", "encrypted-field", "hidden-password-field"),
)
def test_request_submit_is_refused_before_credentials_when_processing_markers_exist(
    monkeypatch,
    tmp_path,
    onsubmit: str,
    marker_specs: list[dict[str, str]],
) -> None:  # type: ignore[no-untyped-def]
    driver = _ScenarioDriver(onsubmit=onsubmit, marker_specs=marker_specs)
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_FORM_INVALID"
    assert ("enumerate-submitters", "all") in driver.events
    assert not any(event[0] in {"clear", "send_keys", "click", "request-submit"} for event in driver.events)
    _assert_chrome_only(driver.events)


@pytest.mark.parametrize(
    "page_source",
    [
        "<script>window.CrYpTo .\n SuBtLe.encrypt()</script>",
        "<script>EnCrYpT \t PaSsWoRd()</script>",
        "<script>PASSWORD \r\n Encrypt()</script>",
        "<script>password \t CIPHER()</script>",
        "<script>Encrypted \n Password = value</script>",
    ],
    ids=(
        "crypto-subtle",
        "encrypt-password",
        "password-encrypt",
        "password-cipher",
        "encrypted-password",
    ),
)
def test_page_level_crypto_marker_blocks_request_submit_before_any_credential_touch(
    monkeypatch,
    tmp_path,
    page_source: str,
) -> None:  # type: ignore[no-untyped-def]
    driver = _ScenarioDriver(page_source=page_source)
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_FORM_INVALID"
    assert ("enumerate-submitters", "all") in driver.events
    assert not any(
        event[0]
        in {"clear", "send_keys", "click", "request-submit-check", "request-submit"}
        for event in driver.events
    )
    assert {("cleanup", "storage"), ("cleanup", "cookies"), ("cleanup", "driver")}.issubset(
        driver.events
    )


def test_selenium_plain_form_without_submitter_uses_request_submit_and_preserves_submit_event(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    callback = CALLBACK + "#access_token=fake&token_type=Bearer&state=fixed-state"
    profile = tmp_path / "enter-fallback-profile"
    events: list[tuple[str, str]] = []

    class Options:
        def add_argument(self, _value: str) -> None:
            pass

        def set_capability(self, *_args) -> None:  # type: ignore[no-untyped-def]
            pass

    class Control:
        def __init__(self, driver, label: str, input_type: str) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver
            self.label = label
            self.input_type = input_type
            self.form = None

        def is_displayed(self) -> bool:
            return True

        def is_enabled(self) -> bool:
            return True

        def get_attribute(self, name: str) -> str:
            return self.input_type if name == "type" else ""

        def clear(self) -> None:
            events.append(("clear", self.label))

        def send_keys(self, _value: str) -> None:
            events.append(("send_keys", self.label))

        def find_element(self, *_args):  # type: ignore[no-untyped-def]
            return self.form

    class Form:
        def __init__(self, driver) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver

        def get_attribute(self, name: str) -> str:
            return {"method": "post", "action": IDP + "/login"}.get(name, "")

        def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
            if selector == "input[type='password']":
                return [self.driver.password]
            if "button[type='submit']" in selector:
                return []
            return [self.driver.username]

    class Driver:
        def __init__(self) -> None:
            self.current_url = IDP + "/authorize"
            self.page_source = ""
            self.username = Control(self, "username", "text")
            self.password = Control(self, "password", "password")
            self.form = Form(self)
            self.password.form = self.form

        def set_page_load_timeout(self, _timeout: float) -> None:
            pass

        def get(self, url: str) -> None:
            self.current_url = url

        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            events.append(("cdp", command))
            if command == "Page.addScriptToEvaluateOnNewDocument":
                assert "source" in params
                return {"identifier": "callback-capture"}
            assert command == "Page.navigate"
            self.current_url = params["url"]
            return {"frameId": "authorize-frame"}

        def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
            return [self.password] if "password" in selector else []

        def execute_script(self, script: str, *_args):  # type: ignore[no-untyped-def]
            if "const expectedOrigin=arguments[0]" in script:
                return [False, ""]
            if "typeof arguments[0].requestSubmit" in script:
                events.append(("request-submit-check", "form"))
                return True
            if "arguments[0].requestSubmit();" in script:
                events.append(("request-submit", "submit-event"))
                self.current_url = callback
                return None
            events.append(("cleanup", "storage"))
            return None

        def delete_all_cookies(self) -> None:
            events.append(("cleanup", "cookies"))

        def quit(self) -> None:
            events.append(("cleanup", "driver"))

    class Wait:
        def __init__(self, driver, _timeout: float) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver

        def until(self, predicate):  # type: ignore[no-untyped-def]
            return predicate(self.driver)

    driver = Driver()
    browser_constructors: list[str] = []
    monkeypatch.setattr(auth_service.tempfile, "mkdtemp", lambda **_kwargs: str(profile))
    monkeypatch.setattr(auth_service.shutil, "rmtree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auth_service.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr("selenium.webdriver.ChromeOptions", Options)
    monkeypatch.setattr(
        "selenium.webdriver.Chrome",
        lambda **_kwargs: browser_constructors.append("chrome") or driver,
    )
    monkeypatch.setattr(
        "selenium.webdriver.Edge",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Edge fallback must not run after Chrome success")
        ),
    )
    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", Wait)

    result = ArasPasswordAuthClient(
        ARAS_HTTP, allow_insecure_http=True
    )._login_with_selenium(
        IDP + "/authorize",
        {"http://aras.example", IDP},
        "fake-user",
        "fake-password",
    )

    assert result == callback
    assert events.count(("send_keys", "password")) == 1
    assert ("request-submit-check", "form") in events
    assert ("request-submit", "submit-event") in events
    assert not any(event[0] == "click" for event in events)
    assert {("cleanup", "storage"), ("cleanup", "cookies"), ("cleanup", "driver")}.issubset(
        events
    )
    assert browser_constructors == ["chrome"]


def test_auth_diagnostic_report_disallows_unsafe_raw_mode_and_contains_no_secret(tmp_path) -> None:
    with pytest.raises(ValueError):
        MarkdownDiagnosticReport(
            options=DiagnosticOptions(enabled=True, unsafe_raw=True),
            base_url=ARAS_HTTP,
            mode="ewo-auth",
            allow_unsafe_raw=False,
            output_dir=tmp_path,
        )

    secret_value = "fictional-" + "password-value"
    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=False),
        base_url=ARAS_HTTP,
        mode="ewo-auth",
        inputs={"password": secret_value, "authorization": "Bearer fictional-token"},
        allow_unsafe_raw=False,
        output_dir=tmp_path,
    )
    report.record_exception(RuntimeError("password=" + secret_value))
    path = report.save("failed")
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert secret_value not in text
    assert "fictional-token" not in text
    assert "[redacted]" in text


def test_selenium_rejects_untrusted_form_action_before_touching_credential_controls(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    touched: list[str] = []
    profile = tmp_path / "untrusted-form-profile"

    class Options:
        def add_argument(self, _value: str) -> None:
            pass

        def set_capability(self, *_args) -> None:  # type: ignore[no-untyped-def]
            pass

    class Form:
        def get_attribute(self, name: str) -> str:
            return {"method": "post", "action": "https://untrusted.example/collect"}.get(
                name, ""
            )

        def find_elements(self, *_args):  # type: ignore[no-untyped-def]
            touched.append("find-form-inputs")
            return []

    form = Form()

    class Candidate:
        def is_displayed(self) -> bool:
            return True

        def is_enabled(self) -> bool:
            return True

        def get_attribute(self, name: str) -> str:
            return "password" if name == "type" else ""

        def find_element(self, *_args):  # type: ignore[no-untyped-def]
            return form

        def clear(self) -> None:
            touched.append("clear")

        def send_keys(self, _value: str) -> None:
            touched.append("send_keys")

    class Driver:
        current_url = IDP + "/authorize"

        def set_page_load_timeout(self, _timeout: float) -> None:
            pass

        def get(self, url: str) -> None:
            self.current_url = url

        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            if command == "Page.addScriptToEvaluateOnNewDocument":
                touched.append("cdp-hook")
                assert "source" in params
                return {"identifier": "callback-capture"}
            touched.append("cdp-navigate")
            assert command == "Page.navigate"
            self.current_url = params["url"]
            return {"frameId": "authorize-frame"}

        def find_elements(self, *_args):  # type: ignore[no-untyped-def]
            return [Candidate()]

        def execute_script(self, script: str, *_args):  # type: ignore[no-untyped-def]
            if "const expectedOrigin=arguments[0]" in script:
                return [False, ""]
            touched.append("cleanup-storage")
            return None

        def delete_all_cookies(self) -> None:
            touched.append("cleanup-cookies")

        def quit(self) -> None:
            touched.append("quit")

    class Wait:
        def __init__(self, driver, _timeout: float) -> None:  # type: ignore[no-untyped-def]
            self.driver = driver

        def until(self, predicate):  # type: ignore[no-untyped-def]
            return predicate(self.driver)

    driver = Driver()
    browser_constructors: list[str] = []
    monkeypatch.setattr(auth_service.tempfile, "mkdtemp", lambda **_kwargs: str(profile))
    monkeypatch.setattr(auth_service.shutil, "rmtree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("selenium.webdriver.ChromeOptions", Options)
    monkeypatch.setattr(
        "selenium.webdriver.Chrome",
        lambda **_kwargs: browser_constructors.append("chrome") or driver,
    )
    monkeypatch.setattr(
        "selenium.webdriver.Edge",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Edge fallback must not run after Chrome success")
        ),
    )
    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", Wait)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_FORM_ORIGIN_REJECTED"
    assert not {"clear", "send_keys", "find-form-inputs"}.intersection(touched)
    assert {"cleanup-storage", "cleanup-cookies", "quit"}.issubset(touched)
    assert browser_constructors == ["chrome"]


@pytest.mark.parametrize("substage", sorted(auth_service.BROWSER_AUTH_SUBSTAGES))
def test_browser_auth_error_preserves_only_allowlisted_substages(substage: str) -> None:
    error = ArasAuthError(
        "AUTH_BROWSER_FAILED",
        "safe",
        stage="browser",
        substage=substage,
    )

    assert error.substage == substage


@pytest.mark.parametrize("category", sorted(auth_service.BROWSER_EXCEPTION_CATEGORIES))
def test_browser_auth_error_preserves_only_allowlisted_categories(category: str) -> None:
    error = ArasAuthError(
        "AUTH_BROWSER_FAILED",
        "safe",
        stage="browser",
        category=category,
    )

    assert error.category == category


def test_browser_auth_error_drops_unknown_diagnostics() -> None:
    error = ArasAuthError(
        "AUTH_BROWSER_FAILED",
        "safe",
        stage="browser",
        substage="private-selector-state",
        category="private-driver-message",
    )

    assert error.substage is None
    assert error.category is None


def test_browser_exception_categories_are_stable_and_message_free() -> None:
    from selenium.common.exceptions import TimeoutException, WebDriverException

    assert auth_service._browser_exception_category(TimeoutException("private-url")) == "timeout"
    assert auth_service._browser_exception_category(WebDriverException("private-body")) == "webdriver"
    assert auth_service._browser_exception_category(RuntimeError("private-selector")) == "unexpected"


def test_chrome_start_failure_cleans_its_profile_before_isolated_edge_fallback_and_both_fail_safely(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    from selenium.common.exceptions import WebDriverException

    options_created: list[tuple[str, object]] = []
    constructors: list[str] = []
    profiles_created: list[Path] = []
    profiles_removed: list[Path] = []
    chrome_profile = tmp_path / "chrome-profile"
    edge_profile = tmp_path / "edge-profile"

    class Options:
        page_load_strategy = "normal"

        def __init__(self, browser: str) -> None:
            self.browser = browser
            self.page_load_strategy = "normal"
            options_created.append((browser, self))

        def add_argument(self, _value: str) -> None:
            pass

    def make_profile(*, prefix: str) -> str:
        if prefix == "vse-aras-auth-chrome-":
            path = chrome_profile
        elif prefix == "vse-aras-auth-edge-":
            assert profiles_removed == [chrome_profile]
            path = edge_profile
        else:  # pragma: no cover - protects the test contract
            raise AssertionError("unexpected browser profile prefix")
        profiles_created.append(path)
        return str(path)

    monkeypatch.setattr(auth_service.tempfile, "mkdtemp", make_profile)
    monkeypatch.setattr(
        auth_service.shutil,
        "rmtree",
        lambda path, **_kwargs: profiles_removed.append(Path(path)),
    )
    monkeypatch.setattr("selenium.webdriver.EdgeOptions", lambda: Options("edge"))
    monkeypatch.setattr("selenium.webdriver.ChromeOptions", lambda: Options("chrome"))
    monkeypatch.setattr(
        "selenium.webdriver.Chrome",
        lambda **_kwargs: constructors.append("chrome")
        or (_ for _ in ()).throw(RuntimeError("opaque-chrome-start-detail")),
    )
    monkeypatch.setattr(
        "selenium.webdriver.Edge",
        lambda **_kwargs: constructors.append("edge")
        or (_ for _ in ()).throw(WebDriverException("opaque-edge-start-detail")),
    )

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_BROWSER_UNAVAILABLE"
    assert excinfo.value.stage == "browser"
    assert excinfo.value.substage == "driver_start"
    assert excinfo.value.category == "webdriver"
    assert str(excinfo.value) == (
        "Browser automation is unavailable for this Aras login page."
    )
    assert "opaque" not in str(excinfo.value)
    assert constructors == ["chrome", "edge"]
    assert [browser for browser, _options in options_created] == ["chrome", "edge"]
    assert all(options.page_load_strategy == "none" for _browser, options in options_created)
    assert profiles_created == [chrome_profile, edge_profile]
    assert chrome_profile != edge_profile
    assert profiles_removed == [chrome_profile, edge_profile]


def test_chrome_constructor_failure_uses_one_isolated_edge_fallback_only_after_chrome_cleanup(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    constructors: list[str] = []
    profiles_created: list[Path] = []
    profiles_removed: list[Path] = []
    chrome_activity = {"hook": 0, "navigate": 0, "dom": 0, "credential": 0}
    chrome_profile = tmp_path / "failed-chrome-profile"
    edge_profile = tmp_path / "edge-fallback-profile"
    driver = _ScenarioDriver(
        submitter_specs=[
            {"label": "safe", "formaction": IDP + "/login", "formmethod": "post"}
        ]
    )

    class Options:
        page_load_strategy = "normal"

        def add_argument(self, _value: str) -> None:
            pass

    class Wait:
        def __init__(self, scenario, _timeout: float) -> None:  # type: ignore[no-untyped-def]
            self.scenario = scenario

        def until(self, predicate):  # type: ignore[no-untyped-def]
            return predicate(self.scenario)

    def make_profile(*, prefix: str) -> str:
        if prefix == "vse-aras-auth-chrome-":
            path = chrome_profile
        elif prefix == "vse-aras-auth-edge-":
            assert profiles_removed == [chrome_profile]
            path = edge_profile
        else:  # pragma: no cover - protects the test contract
            raise AssertionError("unexpected browser profile prefix")
        profiles_created.append(path)
        return str(path)

    def fail_chrome(**_kwargs):  # type: ignore[no-untyped-def]
        constructors.append("chrome")
        raise RuntimeError("opaque-chrome-start-detail")

    def construct_edge(**_kwargs):  # type: ignore[no-untyped-def]
        constructors.append("edge")
        return driver

    monkeypatch.setattr(auth_service.tempfile, "mkdtemp", make_profile)
    monkeypatch.setattr(
        auth_service.shutil,
        "rmtree",
        lambda path, **_kwargs: profiles_removed.append(Path(path)),
    )
    monkeypatch.setattr(auth_service.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr("selenium.webdriver.ChromeOptions", Options)
    monkeypatch.setattr("selenium.webdriver.EdgeOptions", Options)
    monkeypatch.setattr("selenium.webdriver.Chrome", fail_chrome)
    monkeypatch.setattr("selenium.webdriver.Edge", construct_edge)
    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", Wait)

    callback = ArasPasswordAuthClient(
        ARAS_HTTP, allow_insecure_http=True
    )._login_with_selenium(
        IDP + "/authorize",
        {"http://aras.example", IDP},
        "fake-user",
        "fake-password",
    )

    assert callback == driver.callback
    assert constructors == ["chrome", "edge"]
    assert profiles_created == [chrome_profile, edge_profile]
    assert profiles_removed == [chrome_profile, edge_profile]
    assert chrome_profile != edge_profile
    assert chrome_activity == {"hook": 0, "navigate": 0, "dom": 0, "credential": 0}
    assert driver.events.count(("cdp", "Page.addScriptToEvaluateOnNewDocument")) == 1
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert ("cleanup", "driver") in driver.events


def test_callback_capture_hook_is_installed_before_first_authorize_navigation_and_credential_touch(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    driver = _ScenarioDriver(
        submitter_specs=[
            {"label": "safe", "formaction": IDP + "/login", "formmethod": "post"}
        ]
    )
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    callback = ArasPasswordAuthClient(
        ARAS_HTTP, allow_insecure_http=True
    )._login_with_selenium(
        IDP + "/authorize",
        {"http://aras.example", IDP},
        "fake-user",
        "fake-password",
    )

    event_names = [event[0] for event in driver.events]
    assert callback == driver.callback
    hook_index = driver.events.index(("cdp", "Page.addScriptToEvaluateOnNewDocument"))
    navigate_index = driver.events.index(("cdp", "Page.navigate"))
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert hook_index < navigate_index
    assert navigate_index < event_names.index("callback-read")
    assert event_names.index("callback-read") < event_names.index("clear")


@pytest.mark.parametrize(
    ("raw_error", "expected_category"),
    [
        ("net::ERR_UNSAFE_PORT", "browser_policy"),
        ("net::ERR_BLOCKED_BY_ADMINISTRATOR", "browser_policy"),
        ("net::ERR_BLOCKED_BY_CLIENT", "browser_policy"),
        ("browser policy refusal", "browser_policy"),
        ("net::ERR_PROXY_CONNECTION_FAILED", "proxy"),
        ("net::ERR_TUNNEL_CONNECTION_FAILED", "proxy"),
        ("net::ERR_NAME_NOT_RESOLVED", "dns"),
        ("DNS lookup failed", "dns"),
        ("net::ERR_CERT_AUTHORITY_INVALID", "tls"),
        ("TLS handshake failed", "tls"),
        ("net::ERR_CONNECTION_REFUSED", "connect"),
        ("net::ERR_TIMED_OUT", "connect"),
        ("opaque-navigation-failure", "network_unknown"),
        ("", None),
    ],
)
def test_browser_navigation_error_text_is_reduced_to_fixed_internal_category(
    raw_error: str, expected_category: str | None
) -> None:
    assert auth_service._browser_navigation_error_category(raw_error) == expected_category


@pytest.mark.parametrize(
    ("raw_error", "expected_code", "expected_category", "expected_message"),
    [
        (
            "net::ERR_UNSAFE_PORT opaque-policy-detail",
            "AUTH_BROWSER_POLICY_BLOCKED",
            "security",
            "Browser policy blocked the authentication page.",
        ),
        (
            "net::ERR_PROXY_CONNECTION_FAILED opaque-proxy-detail",
            "AUTH_BROWSER_NETWORK_FAILED",
            "webdriver",
            "The browser could not reach the authentication service.",
        ),
        (
            "net::ERR_NAME_NOT_RESOLVED opaque-dns-detail",
            "AUTH_BROWSER_NETWORK_FAILED",
            "webdriver",
            "The browser could not reach the authentication service.",
        ),
        (
            "net::ERR_CERT_AUTHORITY_INVALID opaque-tls-detail",
            "AUTH_BROWSER_NETWORK_FAILED",
            "webdriver",
            "The browser could not reach the authentication service.",
        ),
        (
            "net::ERR_CONNECTION_REFUSED opaque-connect-detail",
            "AUTH_BROWSER_NETWORK_FAILED",
            "webdriver",
            "The browser could not reach the authentication service.",
        ),
        (
            "opaque-unknown-errorText-detail",
            "AUTH_BROWSER_NETWORK_FAILED",
            "webdriver",
            "The browser could not reach the authentication service.",
        ),
    ],
)
def test_cdp_navigation_failures_expose_only_fixed_safe_auth_errors(
    raw_error: str,
    expected_code: str,
    expected_category: str,
    expected_message: str,
) -> None:
    class Driver:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str]]] = []

        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            self.calls.append((command, params))
            return {"frameId": "authorize-frame", "errorText": raw_error}

    driver = Driver()
    with pytest.raises(ArasAuthError) as excinfo:
        auth_service._navigate_authorize_with_cdp(driver, IDP + "/authorize")

    error = excinfo.value
    assert driver.calls == [("Page.navigate", {"url": IDP + "/authorize"})]
    assert error.code == expected_code
    assert error.stage == "browser"
    assert error.substage == "navigate"
    assert error.category == expected_category
    assert str(error) == expected_message
    assert raw_error not in str(error)
    assert raw_error not in repr(vars(error))

    traceback = error.__traceback__
    assert traceback is not None
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    frame_locals = traceback.tb_frame.f_locals
    assert frame_locals["raw_error"] == ""
    assert frame_locals["navigation_result"] is None
    assert raw_error not in repr(frame_locals)


def test_cdp_navigation_success_is_exactly_one_safe_navigate_call() -> None:
    class Driver:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str]]] = []

        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            self.calls.append((command, params))
            return {"frameId": "authorize-frame", "loaderId": "authorize-loader"}

    driver = Driver()
    assert auth_service._navigate_authorize_with_cdp(driver, IDP + "/authorize") is None
    assert driver.calls == [("Page.navigate", {"url": IDP + "/authorize"})]


@pytest.mark.parametrize("bad_result", [None, [], "not-a-cdp-mapping"])
def test_cdp_navigation_rejects_malformed_results_with_fixed_protocol_error(
    bad_result: object,
) -> None:
    class Driver:
        def execute_cdp_cmd(self, *_args):  # type: ignore[no-untyped-def]
            return bad_result

    with pytest.raises(ArasAuthError) as excinfo:
        auth_service._navigate_authorize_with_cdp(Driver(), IDP + "/authorize")

    assert excinfo.value.code == "AUTH_BROWSER_NETWORK_FAILED"
    assert excinfo.value.stage == "browser"
    assert excinfo.value.substage == "navigate"
    assert excinfo.value.category == "protocol"


def test_cdp_navigation_webdriver_exception_does_not_expose_raw_detail() -> None:
    from selenium.common.exceptions import WebDriverException

    raw_detail = "opaque-driver-errorText-detail"

    class Driver:
        def execute_cdp_cmd(self, *_args):  # type: ignore[no-untyped-def]
            raise WebDriverException(raw_detail)

    with pytest.raises(ArasAuthError) as excinfo:
        auth_service._navigate_authorize_with_cdp(Driver(), IDP + "/authorize")

    assert excinfo.value.code == "AUTH_BROWSER_NETWORK_FAILED"
    assert excinfo.value.stage == "browser"
    assert excinfo.value.substage == "navigate"
    assert excinfo.value.category == "webdriver"
    assert raw_detail not in str(excinfo.value)
    assert raw_detail not in repr(vars(excinfo.value))


def test_browser_policy_navigation_fails_before_wait_form_or_credential_touch(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    raw_detail = "net::ERR_UNSAFE_PORT opaque-selector-credential-detail"

    class Driver(_ScenarioDriver):
        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            self.events.append(("cdp", command))
            if command == "Page.addScriptToEvaluateOnNewDocument":
                return {"identifier": "callback-capture"}
            assert command == "Page.navigate"
            return {"frameId": "authorize-frame", "errorText": raw_detail}

        def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
            self.events.append(("driver-find", selector))
            return super().find_elements(_by, selector)

    driver = Driver(
        submitter_specs=[
            {"label": "safe", "formaction": IDP + "/login", "formmethod": "post"}
        ]
    )
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert driver.events[:3] == [
        ("construct", "chrome"),
        ("cdp", "Page.addScriptToEvaluateOnNewDocument"),
        ("cdp", "Page.navigate"),
    ]
    assert ("construct", "edge") not in driver.events
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert not any(
        event[0]
        in {
            "callback-read",
            "driver-find",
            "enumerate-submitters",
            "check-form-owner",
            "clear",
            "send_keys",
            "click",
            "request-submit-check",
            "request-submit",
        }
        for event in driver.events
    )
    assert ("cleanup", "cookies") in driver.events
    assert ("cleanup", "driver") in driver.events
    assert excinfo.value.code == "AUTH_BROWSER_POLICY_BLOCKED"
    assert excinfo.value.stage == "browser"
    assert excinfo.value.substage == "navigate"
    assert excinfo.value.category == "security"
    assert raw_detail not in str(excinfo.value)
    assert raw_detail not in repr(driver.events)


def test_chrome_network_navigation_failure_never_constructs_edge_or_touches_dom(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    class Driver(_ScenarioDriver):
        def execute_cdp_cmd(self, command: str, params: dict[str, str]):
            self.events.append(("cdp", command))
            if command == "Page.addScriptToEvaluateOnNewDocument":
                return {"identifier": "callback-capture"}
            assert command == "Page.navigate"
            return {
                "frameId": "authorize-frame",
                "errorText": "net::ERR_PROXY_CONNECTION_FAILED opaque-detail",
            }

        def find_elements(self, _by, selector: str):  # type: ignore[no-untyped-def]
            self.events.append(("driver-find", selector))
            return super().find_elements(_by, selector)

    driver = Driver()
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_BROWSER_NETWORK_FAILED"
    assert excinfo.value.substage == "navigate"
    assert excinfo.value.category == "webdriver"
    _assert_chrome_only(driver.events)
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert not any(
        event[0]
        in {
            "driver-find",
            "callback-read",
            "clear",
            "send_keys",
            "click",
            "request-submit",
        }
        for event in driver.events
    )


def test_chrome_credential_page_timeout_never_constructs_edge_or_touches_credentials(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    from selenium.common.exceptions import TimeoutException

    class TimeoutWait:
        def __init__(self, _driver, _timeout: float) -> None:  # type: ignore[no-untyped-def]
            pass

        def until(self, _predicate):  # type: ignore[no-untyped-def]
            raise TimeoutException("opaque-credential-page-timeout")

    driver = _ScenarioDriver()
    _install_selenium_scenario(monkeypatch, tmp_path, driver)
    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", TimeoutWait)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_BROWSER_FAILED"
    assert excinfo.value.substage == "credential_page"
    assert excinfo.value.category == "timeout"
    assert "opaque" not in str(excinfo.value)
    _assert_chrome_only(driver.events)
    assert driver.events.count(("cdp", "Page.navigate")) == 1
    assert not any(
        event[0] in {"clear", "send_keys", "click", "request-submit"}
        for event in driver.events
    )


def test_navigation_error_text_is_not_logged_or_persisted_by_auth_source() -> None:
    source = Path("services/aras_auth.py").read_text(encoding="utf-8-sig")
    navigate_source = source.split("def _navigate_authorize_with_cdp", 1)[1].split(
        "def _read_callback_capture", 1
    )[0]

    assert 'raw_error = ""' in navigate_source
    assert "navigation_result = None" in navigate_source
    assert "logger." not in navigate_source
    assert "print(" not in navigate_source
    assert "get_log(" not in source
    assert "goog:loggingPrefs" not in source


def test_callback_capture_script_is_exact_memory_only_and_stops_callback_page() -> None:
    script = auth_service._callback_capture_script(CALLBACK)
    lowered = script.casefold()

    assert 'const expectedOrigin="http://aras.example"' in script
    assert 'const expectedPath="/innovatorserver/Client/OAuth/RedirectCallback"' in script
    assert "window.location.origin !== expectedOrigin" in script
    assert "window.location.pathname !== expectedPath" in script
    assert "window.location.hash || window.location.search" in script
    assert "Object.defineProperty(window,memoryKey" in script
    assert "writable:false" in script
    assert "configurable:true" in script
    assert "window.stop()" in script
    for forbidden in (
        "localstorage",
        "sessionstorage",
        "window.name",
        "console.",
        "performance.",
        "indexeddb",
        "document.cookie",
        "filesystem",
    ):
        assert forbidden not in lowered


def test_callback_capture_memory_is_exactly_scoped_reconstructed_and_deleted_after_read() -> None:
    class Driver:
        def __init__(self) -> None:
            self.results = iter(
                [
                    [True, "#access_token=fake&token_type=Bearer&state=fixed-state"],
                    [True, ""],
                    [False, ""],
                ]
            )
            self.calls: list[tuple[object, ...]] = []

        def execute_script(self, _script: str, *args):  # type: ignore[no-untyped-def]
            self.calls.append(args)
            return next(self.results)

    driver = Driver()

    captured = auth_service._read_callback_capture(driver, CALLBACK)
    deleted = auth_service._read_callback_capture(driver, CALLBACK)
    wrong_origin_or_path = auth_service._read_callback_capture(driver, CALLBACK)

    assert captured == CALLBACK + "#access_token=fake&token_type=Bearer&state=fixed-state"
    assert deleted is None
    assert wrong_origin_or_path is None
    assert all(
        args == (
            "http://aras.example",
            "/innovatorserver/Client/OAuth/RedirectCallback",
            auth_service._CALLBACK_MEMORY_KEY,
        )
        for args in driver.calls
    )


@pytest.mark.parametrize("bad_result", [None, {}, [], [True], [True, "bad-prefix"]])
def test_callback_capture_read_rejects_malformed_protocol_results(bad_result) -> None:  # type: ignore[no-untyped-def]
    class Driver:
        def execute_script(self, *_args):  # type: ignore[no-untyped-def]
            return bad_result

    with pytest.raises(ArasAuthError) as excinfo:
        auth_service._read_callback_capture(Driver(), CALLBACK)

    assert excinfo.value.code == "AUTH_BROWSER_FAILED"
    assert excinfo.value.substage == "callback_wait"
    assert excinfo.value.category == "protocol"


def test_callback_capture_install_failure_is_fail_closed_before_credential_touch(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    from selenium.common.exceptions import WebDriverException

    class Driver(_ScenarioDriver):
        def execute_cdp_cmd(self, *_args):  # type: ignore[no-untyped-def]
            self.events.append(("cdp-failed", "install"))
            raise WebDriverException("private-cdp-install-message")

    driver = Driver()
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_BROWSER_FAILED"
    assert excinfo.value.substage == "navigate"
    assert excinfo.value.category == "webdriver"
    assert not any(
        event[0] in {"get", "clear", "send_keys", "click", "request-submit"}
        for event in driver.events
    )
    _assert_chrome_only(driver.events)


@pytest.mark.parametrize("bad_result", [None, {}, {"identifier": ""}, []])
def test_callback_capture_install_rejects_missing_cdp_identifier(bad_result) -> None:  # type: ignore[no-untyped-def]
    class Driver:
        def execute_cdp_cmd(self, *_args):  # type: ignore[no-untyped-def]
            return bad_result

    with pytest.raises(ArasAuthError) as excinfo:
        auth_service._install_callback_capture_hook(Driver(), CALLBACK)

    assert excinfo.value.code == "AUTH_BROWSER_FAILED"
    assert excinfo.value.substage == "navigate"
    assert excinfo.value.category == "protocol"


def test_callback_capture_read_failure_is_fail_closed_before_credential_touch(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    from selenium.common.exceptions import WebDriverException

    class Driver(_ScenarioDriver):
        def execute_script(self, script: str, *args):  # type: ignore[no-untyped-def]
            if "const expectedOrigin=arguments[0]" in script:
                self.events.append(("callback-read-failed", "memory"))
                raise WebDriverException("private-cdp-read-message")
            return super().execute_script(script, *args)

    driver = Driver(
        submitter_specs=[
            {"label": "safe", "formaction": IDP + "/login", "formmethod": "post"}
        ]
    )
    _install_selenium_scenario(monkeypatch, tmp_path, driver)

    with pytest.raises(ArasAuthError) as excinfo:
        ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)._login_with_selenium(
            IDP + "/authorize",
            {"http://aras.example", IDP},
            "fake-user",
            "fake-password",
        )

    assert excinfo.value.code == "AUTH_BROWSER_FAILED"
    assert excinfo.value.substage == "callback_wait"
    assert excinfo.value.category == "webdriver"
    assert not any(
        event[0] in {"clear", "send_keys", "click", "request-submit"}
        for event in driver.events
    )
    _assert_chrome_only(driver.events)


def test_browser_callback_bad_state_is_security_failure_at_session_extract(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session = OidcSession(
        authorize_html=(
            '<form method="post" action="https://idp.example/login" '
            'onsubmit="return encryptPassword()">'
            '<input type="text" name="Username">'
            '<input type="password" name="Password"></form>'
        )
    )
    _install_oidc_session(monkeypatch, session)
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)
    monkeypatch.setattr(
        client,
        "_login_with_selenium",
        lambda *_args: CALLBACK
        + "#access_token=fake&token_type=Bearer&state=wrong-state",
    )

    with pytest.raises(ArasAuthError) as excinfo:
        client.login("fake-user", "fake-password")

    assert excinfo.value.code == "AUTH_STATE_MISMATCH"
    assert excinfo.value.substage == "session_extract"
    assert excinfo.value.category == "security"
    assert session.closed is True
    assert session.cookies == {}


def test_query_callback_capture_is_parsed_after_exact_second_validation() -> None:
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)
    callback = CALLBACK + "?access_token=fake&token_type=Bearer&state=fixed-state"

    token, token_type, expires_at = client._parse_callback(callback, "fixed-state")

    assert token == "fake"
    assert token_type == "Bearer"
    assert expires_at is None


def test_callback_rejects_ambiguous_query_and_fragment_payloads() -> None:
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)
    callback = (
        CALLBACK
        + "?access_token=query-token&token_type=Bearer&state=fixed-state"
        + "#access_token=fragment-token&token_type=Bearer&state=fixed-state"
    )

    with pytest.raises(ArasAuthError) as excinfo:
        client._parse_callback(callback, "fixed-state")

    assert excinfo.value.code == "AUTH_CALLBACK_INVALID"


@pytest.mark.parametrize(
    "callback",
    [
        ARAS_HTTP + "Client/OAuth/redirectcallback#access_token=fake&state=fixed-state",
        CALLBACK + "/#access_token=fake&state=fixed-state",
    ],
    ids=("wrong-path-case", "trailing-slash"),
)
def test_callback_python_second_validation_requires_exact_origin_and_path(callback: str) -> None:
    client = ArasPasswordAuthClient(ARAS_HTTP, allow_insecure_http=True)

    with pytest.raises(ArasAuthError) as excinfo:
        client._parse_callback(callback, "fixed-state")

    assert excinfo.value.code == "UNTRUSTED_AUTH_REDIRECT"


def test_auth_source_has_no_embedded_credentials_or_persistence() -> None:
    source = Path("services/aras_auth.py").read_text(encoding="utf-8-sig")
    lowered = source.casefold()
    assert "localstorage.setitem" not in lowered
    assert "sessionstorage.setitem" not in lowered
    assert ".env" not in source
    assert "config.set" not in lowered
    assert "window.localStorage.clear(); window.sessionStorage.clear();" in source
    assert "driver.delete_all_cookies()" in source
    assert "driver.quit()" in source
    assert "form.submit(" not in source
    assert "Keys.ENTER" not in source
    assert "safe_submitters[0].click()" in source
    assert 'driver.execute_script("arguments[0].requestSubmit();", form)' in source
