from __future__ import annotations

import copy
import hashlib
import json
import types
from collections import deque
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import services.aras_account_code_auth as code_auth
import services.aras_auth as legacy_auth


ARAS = "http://aras.example/innovatorserver/"
STATE = "unit-test-state"
CODE = "unit-test-code"
USER = "unit-test-user"
PASSWORD = "unit-test-password"
TOKEN = "unit-test-access-token"
B2_AUDIT_CLIENT = code_auth.ArasAccountCodeAuthClient
GRAPH_USERNAME = "graph-user-4f8d2a"
GRAPH_PASSWORD = "graph-password-8bc713"
GRAPH_CODE = "graph-code-d14e62"
GRAPH_STATE = "graph-state-29a7c1"
GRAPH_TOKEN = "graph-token-0be459"
GRAPH_LOCATION = "Location=https://synthetic.invalid/callback?marker=6cc37a"
GRAPH_SENTINELS = (
    GRAPH_USERNAME,
    GRAPH_PASSWORD,
    GRAPH_CODE,
    GRAPH_STATE,
    GRAPH_TOKEN,
    GRAPH_LOCATION,
)
LOGIN_ACTION = (
    code_auth.ACCOUNT_ORIGIN
    + code_auth.LOGIN_ACTION_PATH
    + "?session_code=session&execution=execution&client_id=ecm-front&tab_id=tab"
)
INLINE_SCRIPT = "window.__verifiedCallback = true;"
EXTERNAL_SCRIPT = b"window.__verifiedExternalCallback = true;"
CALLBACK_HTML = (
    '<!doctype html><script src="/innovatorserver/client/callback.js"></script>'
    f"<script>{INLINE_SCRIPT}</script>"
).encode()


class FakePreparedRequest:
    def __init__(self, url: str = "", body: object = None) -> None:
        self.url = url
        self.body = body
        self.headers = {"Authorization": "Bearer request-secret", "Cookie": "sid=secret"}


class FakeCookies(dict):
    def clear(self) -> None:
        super().clear()


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        content: bytes = b"",
        content_type: str = "text/html",
        location: str | None = None,
        url: str = "https://response.invalid/private?code=secret",
        request: FakePreparedRequest | None = None,
    ) -> None:
        self.status_code = status
        self._content = content
        self.headers = {"Content-Type": content_type}
        if location is not None:
            self.headers["Location"] = location
        self.url = url
        self.request = request or FakePreparedRequest(url=url, body="body-secret")
        self.history = ["history-secret"]
        self.cookies = FakeCookies({"sid": "cookie-secret"})
        self.closed = False

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size: int):  # type: ignore[no-untyped-def]
        for offset in range(0, len(self._content), chunk_size):
            yield self._content[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.headers: dict[str, str] = {}
        self.cookies = FakeCookies({"preauth": "private-cookie"})
        self.trust_env = True
        self.closed = False

    def _call(self, method: str, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {"method": method, "url": url, **copy.deepcopy(kwargs)}
        )
        if not self.responses:
            raise AssertionError(f"unexpected {method} request to {urlsplit(url).path}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        response.url = url
        response.request.url = url
        response.request.body = copy.deepcopy(kwargs.get("data"))
        return response

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._call("GET", url, **kwargs)

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._call("POST", url, **kwargs)

    def close(self) -> None:
        self.closed = True


class SyntheticRequestFailure(RuntimeError):
    def __init__(self, response: FakeResponse) -> None:
        super().__init__("synthetic request failure")
        self.request = response.request
        self.response = response


def _sensitive_http_artifact() -> FakeResponse:
    request = FakePreparedRequest(
        url=GRAPH_LOCATION,
        body=(
            "username="
            + GRAPH_USERNAME
            + "&password="
            + GRAPH_PASSWORD
            + "&code="
            + GRAPH_CODE
            + "&state="
            + GRAPH_STATE
        ),
    )
    request.headers = {
        "Authorization": "Bearer " + GRAPH_TOKEN,
        "Cookie": GRAPH_LOCATION,
    }
    history_request = FakePreparedRequest(
        url=GRAPH_LOCATION,
        body=GRAPH_PASSWORD + GRAPH_CODE,
    )
    history = FakeResponse(
        content=(GRAPH_STATE + GRAPH_TOKEN).encode(),
        url=GRAPH_LOCATION,
        request=history_request,
    )
    response = FakeResponse(
        content=(
            GRAPH_USERNAME
            + GRAPH_PASSWORD
            + GRAPH_CODE
            + GRAPH_STATE
            + GRAPH_TOKEN
            + GRAPH_LOCATION
        ).encode(),
        url=GRAPH_LOCATION,
        request=request,
    )
    response.headers = {
        "Location": GRAPH_LOCATION,
        "Authorization": "Bearer " + GRAPH_TOKEN,
        "Set-Cookie": GRAPH_PASSWORD,
    }
    response.cookies = FakeCookies({"sid": GRAPH_STATE})
    response.history = [history]
    return response


def _scan_sensitive_object_graph(root: object) -> tuple[list[str], int, int]:
    """Traverse the final error graph without following frame globals."""
    queue: deque[object] = deque([root])
    seen: set[int] = set()
    findings: list[str] = []
    frame_count = 0
    http_artifact_count = 0
    while queue:
        value = queue.popleft()
        if value is None:
            continue
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)

        if isinstance(value, str):
            findings.extend(secret for secret in GRAPH_SENTINELS if secret in value)
            continue
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
            findings.extend(
                secret for secret in GRAPH_SENTINELS if secret.encode() in raw
            )
            continue
        if isinstance(value, BaseException):
            queue.extend(value.args)
            queue.append(value.__context__)
            queue.append(value.__cause__)
            queue.append(value.__traceback__)
            queue.extend(vars(value).values())
            continue
        if isinstance(value, types.TracebackType):
            queue.append(value.tb_frame)
            queue.append(value.tb_next)
            continue
        if isinstance(value, types.FrameType):
            frame_count += 1
            queue.extend(tuple(value.f_locals.values()))
            continue
        if isinstance(value, dict):
            queue.extend(value.keys())
            queue.extend(value.values())
            continue
        if isinstance(value, (list, tuple, set, frozenset, deque)):
            queue.extend(value)
            continue

        is_response = hasattr(value, "status_code") or hasattr(value, "request")
        is_prepared = hasattr(value, "body") and hasattr(value, "url")
        if is_response or is_prepared:
            http_artifact_count += 1
            for attribute in (
                "request",
                "response",
                "history",
                "cookies",
                "headers",
                "body",
                "url",
                "_content",
                "content",
                "text",
            ):
                try:
                    queue.append(getattr(value, attribute))
                except Exception:
                    pass
    return findings, frame_count, http_artifact_count


def _capture_final_b2_audit_error() -> legacy_auth.ArasAuthError:
    captured = None
    try:
        B2_AUDIT_CLIENT(ARAS, allow_insecure_http=True).login(
            GRAPH_USERNAME,
            GRAPH_PASSWORD,
        )
    except legacy_auth.ArasAuthError as caught:
        captured = caught
    assert captured is not None
    return captured


def _assert_final_error_graph_is_clean(error: legacy_auth.ArasAuthError) -> None:
    assert error.__context__ is None
    assert error.__cause__ is None
    findings, frame_count, _http_count = _scan_sensitive_object_graph(error)
    assert frame_count >= 2
    assert findings == []


def _retain_http_handles(response: FakeResponse) -> tuple[FakePreparedRequest, list[FakeResponse], list[FakePreparedRequest]]:
    historical = list(response.history)
    return response.request, historical, [item.request for item in historical]


def _assert_retained_http_handles_cleared(
    response: FakeResponse,
    request: FakePreparedRequest,
    historical: list[FakeResponse],
    historical_requests: list[FakePreparedRequest],
) -> None:
    assert response._content == b""
    assert response.content == b""
    assert response.text == ""
    assert response.url == ""
    assert response.headers == {}
    assert response.cookies == {}
    assert response.history == []
    assert response.closed is True
    assert request.body is None
    assert request.url == ""
    assert request.headers == {}
    for item, prepared in zip(historical, historical_requests):
        assert item._content == b""
        assert item.content == b""
        assert item.text == ""
        assert item.url == ""
        assert item.headers == {}
        assert item.cookies == {}
        assert item.history == []
        assert item.closed is True
        assert prepared.body is None
        assert prepared.url == ""
        assert prepared.headers == {}


def _json_response(value: object) -> FakeResponse:
    return FakeResponse(
        content=json.dumps(value).encode(),
        content_type="application/json",
    )


def _metadata() -> dict[str, object]:
    return {
        "issuer": code_auth.REALM_ISSUER,
        "authorization_endpoint": code_auth.AUTHORIZATION_ENDPOINT,
        "token_endpoint": code_auth.TOKEN_ENDPOINT,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
    }


def _login_html(*, action: str = LOGIN_ACTION, extra: str = "") -> bytes:
    return (
        '<form id="kc-form-login" method="post" action="'
        + action
        + '"><input type="hidden" name="flow" value="one">'
        '<input type="text" name="username">'
        '<input type="password" name="password">'
        '<input type="submit" name="login" value="Sign In"></form>'
        + extra
    ).encode()


def _patch_callback_fixture(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(code_auth, "CALLBACK_INLINE_BYTES", len(INLINE_SCRIPT.encode()))
    monkeypatch.setattr(
        code_auth,
        "CALLBACK_INLINE_SHA256",
        hashlib.sha256(INLINE_SCRIPT.encode()).hexdigest().upper(),
    )
    monkeypatch.setattr(code_auth, "CALLBACK_EXTERNAL_BYTES", len(EXTERNAL_SCRIPT))
    monkeypatch.setattr(
        code_auth,
        "CALLBACK_EXTERNAL_SHA256",
        hashlib.sha256(EXTERNAL_SCRIPT).hexdigest().upper(),
    )
    monkeypatch.setattr(code_auth, "_new_state", lambda: STATE)


def _success_responses(
    *,
    metadata: dict[str, object] | None = None,
    callback_html: bytes = CALLBACK_HTML,
    external_script: bytes = EXTERNAL_SCRIPT,
    login_html: bytes | None = None,
    credential_status: int = 302,
    callback_location: str | None = None,
    token: str = TOKEN,
    token_scope: str = "openid",
) -> list[FakeResponse]:
    callback = callback_location or (
        ARAS + "client/redirect.html?code=" + CODE + "&state=" + STATE
    )
    return [
        _json_response(metadata or _metadata()),
        FakeResponse(content=callback_html, content_type="text/html; charset=utf-8"),
        FakeResponse(content=external_script, content_type="application/javascript"),
        FakeResponse(content=login_html or _login_html(), content_type="text/html"),
        FakeResponse(status=credential_status, location=callback),
        _json_response(
            {
                "access_token": token,
                "token_type": "Bearer",
                "scope": token_scope,
                "expires_in": 60,
            }
        ),
    ]


def _install_flow(
    monkeypatch,
    responses: list[FakeResponse],
):  # type: ignore[no-untyped-def]
    _patch_callback_fixture(monkeypatch)
    session = FakeSession(responses)
    monkeypatch.setattr(code_auth.requests, "Session", lambda: session)
    validations: list[tuple[object, str, str]] = []

    class Validator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("legacy login must never be used")

        def validate_authenticated_session(self, target, item_type):  # type: ignore[no-untyped-def]
            validations.append((target, item_type, target.headers.get("Authorization", "")))

    monkeypatch.setattr(code_auth.legacy_auth, "ArasPasswordAuthClient", Validator)
    return session, validations


def test_b2_unique_success_contract_and_exact_token_exchange(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events = []
    responses = _success_responses()
    credential_response = responses[4]
    session, validations = _install_flow(monkeypatch, responses)

    result = code_auth.ArasAccountCodeAuthClient(
        ARAS,
        allow_insecure_http=True,
        diagnostic_hook=events.append,
    ).login(USER, PASSWORD, validation_item_type="PAA_O")

    assert result.session is session
    assert session.trust_env is False
    assert session.headers == {"Authorization": "Bearer " + TOKEN}
    assert validations == [(session, "PAA_O", "Bearer " + TOKEN)]
    assert [call["method"] for call in session.calls] == [
        "GET",
        "GET",
        "GET",
        "GET",
        "POST",
        "POST",
    ]
    authorize = session.calls[3]
    assert authorize["url"].split("?", 1)[0] == code_auth.AUTHORIZATION_ENDPOINT
    assert parse_qs(urlsplit(str(authorize["url"])).query) == {
        "client_id": ["ecm-front"],
        "response_type": ["code"],
        "scope": ["openid"],
        "redirect_uri": [ARAS + "client/redirect.html"],
        "state": [STATE],
    }
    credential_posts = [call for call in session.calls if call["url"] == LOGIN_ACTION]
    assert len(credential_posts) == 1
    assert credential_posts[0]["data"] == {
        "flow": "one",
        "username": USER,
        "password": PASSWORD,
        "login": "Sign In",
    }
    token_call = session.calls[-1]
    assert token_call["url"] == code_auth.TOKEN_ENDPOINT
    assert token_call["data"] == {
        "grant_type": "authorization_code",
        "code": CODE,
        "client_id": "ecm-front",
        "redirect_uri": ARAS + "client/redirect.html",
    }
    assert not ({"client_secret", "code_verifier", "code_challenge"} & set(token_call["data"]))
    assert credential_response.closed is True
    assert credential_response.request.body is None
    assert credential_response.request.url == ""
    assert credential_response.request.headers == {}
    assert all(response.closed is True for response in responses)
    assert all(response._content == b"" for response in responses)
    assert all(response.headers == {} for response in responses)
    assert all(response.cookies == {} for response in responses)
    assert all(response.history == [] for response in responses)
    assert all(response.request.body is None for response in responses)
    assert all(response.request.url == "" for response in responses)
    assert all(response.request.headers == {} for response in responses)
    assert all("?" not in event.path and "#" not in event.path for event in events)
    assert all(
        secret not in repr(events)
        for secret in (USER, PASSWORD, CODE, STATE, TOKEN, "private-cookie")
    )

    legacy_auth.close_authenticated_session(session)
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda responses: responses.__setitem__(
                0,
                _json_response({**_metadata(), "token_endpoint": "https://evil.invalid/token"}),
            ),
            "AUTH_METADATA_INVALID",
        ),
        (
            lambda responses: responses.__setitem__(
                1,
                FakeResponse(
                    content=(
                        '<!doctype html><script src="/innovatorserver/client/callback.js"></script>'
                        f"<script>{INLINE_SCRIPT}drift</script>"
                    ).encode(),
                    content_type="text/html",
                ),
            ),
            "AUTH_CODE_CONTRACT_UNSUPPORTED",
        ),
        (
            lambda responses: responses.__setitem__(
                3,
                FakeResponse(
                    content=_login_html(action="https://evil.invalid/collect"),
                    content_type="text/html",
                ),
            ),
            "AUTH_FORM_ORIGIN_REJECTED",
        ),
        (
            lambda responses: responses.__setitem__(
                3,
                FakeResponse(
                    content=_login_html(extra="<script>crypto.subtle.encrypt()</script>"),
                    content_type="text/html",
                ),
            ),
            "AUTH_INTERACTION_REQUIRED",
        ),
    ],
    ids=("metadata", "callback-hash", "form-origin", "client-transform"),
)
def test_precredential_contract_failures_never_post_or_fallback(
    monkeypatch, mutator, expected_code: str
) -> None:  # type: ignore[no-untyped-def]
    responses = _success_responses()
    mutator(responses)
    session, validations = _install_flow(monkeypatch, responses)

    with pytest.raises(legacy_auth.ArasAuthError) as excinfo:
        code_auth.ArasAccountCodeAuthClient(ARAS, allow_insecure_http=True).login(
            USER, PASSWORD
        )

    assert excinfo.value.code == expected_code
    assert excinfo.value.credential_touched is False
    assert not [call for call in session.calls if call["method"] == "POST"]
    assert validations == []
    assert session.closed is True
    assert session.headers == {}
    assert session.cookies == {}
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


def test_credential_307_replay_is_blocked_and_request_is_disposed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = _success_responses(credential_status=307)
    credential_response = responses[4]
    session, validations = _install_flow(monkeypatch, responses)

    with pytest.raises(legacy_auth.ArasAuthError) as excinfo:
        code_auth.ArasAccountCodeAuthClient(ARAS, allow_insecure_http=True).login(
            USER, PASSWORD
        )

    assert excinfo.value.code == "AUTH_CREDENTIAL_REPLAY_BLOCKED"
    assert excinfo.value.credential_touched is True
    assert len([call for call in session.calls if call["method"] == "POST"]) == 1
    assert validations == []
    assert credential_response.closed is True
    assert credential_response.request.body is None
    assert credential_response.request.url == ""
    assert credential_response.request.headers == {}
    assert credential_response.headers == {}
    assert credential_response.cookies == {}
    assert session.closed is True


@pytest.mark.parametrize(
    ("callback", "expected_code"),
    [
        (ARAS + "client/redirect.html?code=" + CODE + "&state=wrong", "AUTH_STATE_MISMATCH"),
        (
            ARAS + "client/redirect.html?code=one&code=two&state=" + STATE,
            "AUTH_CALLBACK_INVALID",
        ),
        (
            ARAS + "client/redirect.html?code=" + CODE + "&state=one&state=two",
            "AUTH_CALLBACK_INVALID",
        ),
        (
            ARAS + "client/redirect.html?code=" + CODE + "&state=" + STATE + "#fragment",
            "UNTRUSTED_AUTH_REDIRECT",
        ),
    ],
)
def test_callback_requires_single_code_single_matching_state(
    monkeypatch, callback: str, expected_code: str
) -> None:  # type: ignore[no-untyped-def]
    session, validations = _install_flow(
        monkeypatch, _success_responses(callback_location=callback)
    )

    with pytest.raises(legacy_auth.ArasAuthError) as excinfo:
        code_auth.ArasAccountCodeAuthClient(ARAS, allow_insecure_http=True).login(
            USER, PASSWORD
        )

    assert excinfo.value.code == expected_code
    assert excinfo.value.credential_touched is True
    assert len([call for call in session.calls if call["method"] == "POST"]) == 1
    assert validations == []
    assert session.closed is True


@pytest.mark.parametrize("token", ["line\nbreak", "carriage\rreturn", "nul\x00byte"])
def test_access_token_control_characters_are_rejected_before_header_injection(
    monkeypatch, token: str
) -> None:  # type: ignore[no-untyped-def]
    session, validations = _install_flow(monkeypatch, _success_responses(token=token))

    with pytest.raises(legacy_auth.ArasAuthError) as excinfo:
        code_auth.ArasAccountCodeAuthClient(ARAS, allow_insecure_http=True).login(
            USER, PASSWORD
        )

    assert excinfo.value.code == "AUTH_TOKEN_INVALID"
    assert "Authorization" not in session.headers
    assert validations == []
    assert session.closed is True


def test_dispose_erases_prepared_request_response_location_body_and_cookie() -> None:
    prepared = FakePreparedRequest(
        "https://account.sgmw.com.cn/private?code=private-code",
        "username=user&password=private-password",
    )
    response = FakeResponse(
        content=b"private response body",
        location="http://aras.example/innovatorserver/client/redirect.html?code=private-code",
        request=prepared,
    )
    client = code_auth.ArasAccountCodeAuthClient(ARAS, allow_insecure_http=True)

    client._dispose(response)

    assert prepared.body is None
    assert prepared.url == ""
    assert prepared.headers == {}
    assert response.url == ""
    assert response.headers == {}
    assert response.history == []
    assert response.cookies == {}
    assert response._content == b""
    assert response.closed is True


def test_public_password_login_uses_scheme_a_and_b2_is_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []
    sentinel_session = SimpleNamespace(headers={}, cookies=FakeCookies(), close=lambda: None)

    class B2MustNotRun:
        def __init__(self, base_url: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise AssertionError("B2 must not be constructed by public password login")

        def login(self, username: str, password: str, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("B2 must not be called by public password login")

    class SchemeAOwner:
        def __init__(self, base_url: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append({"base_url": base_url, **kwargs})

        def authenticate(self, username: str, password: str, item_type: str):
            calls.append(
                {
                    "username": username,
                    "password": password,
                    "validation_item_type": item_type,
                }
            )
            return sentinel_session

        def close(self) -> None:
            pass

    import services.aras_browser_auth as browser_auth

    monkeypatch.setattr(code_auth, "ArasAccountCodeAuthClient", B2MustNotRun)
    monkeypatch.setattr(browser_auth, "ArasBrowserSessionOwner", SchemeAOwner)
    client = legacy_auth.ArasPasswordAuthClient(ARAS, allow_insecure_http=True)

    result = client.login(USER, PASSWORD, validation_item_type="EWO_O")

    assert result.session is sentinel_session
    assert calls[1] == {
        "username": USER,
        "password": PASSWORD,
        "validation_item_type": "EWO_O",
    }
    assert calls[0]["base_url"] == ARAS
    assert calls[0]["allow_insecure_http"] is True


def test_pretouch_retry_classifier_is_exact_typed_and_fail_closed() -> None:
    for code, stage, substage, category in legacy_auth._B2_RETRYABLE_PRETOUCH_ERRORS:
        error = legacy_auth.ArasAuthError(
            code,
            "safe",
            stage=stage,
            substage=substage,
            category=category,
            credential_touched=False,
        )
        assert legacy_auth.is_retryable_b2_pretouch_error(error) is True
        error.credential_touched = True
        assert legacy_auth.is_retryable_b2_pretouch_error(error) is False

    callback_error = legacy_auth.ArasAuthError(
        "AUTH_STATE_MISMATCH",
        "safe",
        stage="callback",
        substage="session_extract",
        category="security",
        credential_touched=False,
    )
    assert legacy_auth.is_retryable_b2_pretouch_error(callback_error) is False

    class LookalikeError(legacy_auth.ArasAuthError):
        pass

    lookalike = LookalikeError(
        "AUTH_METADATA_INVALID",
        "safe",
        stage="metadata",
        substage="navigate",
        category="security",
        credential_touched=False,
    )
    assert legacy_auth.is_retryable_b2_pretouch_error(lookalike) is False


def test_b2_network_failure_diagnostics_and_error_never_echo_dynamic_values(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_callback_fixture(monkeypatch)
    events = []

    class NetworkFailureSession(FakeSession):
        def __init__(self) -> None:
            super().__init__([])

        def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append({"method": "GET", "url": url, **copy.deepcopy(kwargs)})
            raise TimeoutError(
                "private-password private-code private-token Location=https://private.invalid"
            )

    session = NetworkFailureSession()
    monkeypatch.setattr(code_auth.requests, "Session", lambda: session)

    with pytest.raises(legacy_auth.ArasAuthError) as excinfo:
        code_auth.ArasAccountCodeAuthClient(
            ARAS,
            allow_insecure_http=True,
            diagnostic_hook=events.append,
        ).login(USER, PASSWORD)

    assert excinfo.value.code == "AUTH_NETWORK_FAILED"
    assert excinfo.value.stage == "metadata"
    assert excinfo.value.category == "timeout"
    assert excinfo.value.__cause__ is None
    combined = repr(events) + repr(excinfo.value.args) + str(excinfo.value)
    assert "private-password" not in combined
    assert "private-code" not in combined
    assert "private-token" not in combined
    assert "Location=" not in combined
    assert len(events) == 1
    assert events[0].path == urlsplit(code_auth.METADATA_URL).path
    assert session.closed is True


def test_recursive_scan_self_check_reaches_nested_http_artifacts() -> None:
    artifact = _sensitive_http_artifact()
    error = SyntheticRequestFailure(artifact)

    findings, frame_count, http_count = _scan_sensitive_object_graph(error)

    assert set(findings) == set(GRAPH_SENTINELS)
    assert frame_count == 0
    assert http_count >= 4


def test_production_scrubber_clears_retained_no_traceback_attr_only_http_graph() -> None:
    response = _sensitive_http_artifact()
    request, historical, historical_requests = _retain_http_handles(response)
    original = SyntheticRequestFailure(response)
    original.history = [response]
    assert original.__traceback__ is None

    legacy_auth._clear_auth_exception_chain(original)

    assert original.args == ()
    assert original.__traceback__ is None
    assert original.__context__ is None
    assert original.__cause__ is None
    assert original.request is request
    assert original.response is response
    assert original.history == []
    _assert_retained_http_handles_cleared(
        response,
        request,
        historical,
        historical_requests,
    )


def test_production_scrubber_clears_retained_args_history_context_cause_and_cycles() -> None:
    args_response = _sensitive_http_artifact()
    args_handles = _retain_http_handles(args_response)
    context_response = _sensitive_http_artifact()
    context_handles = _retain_http_handles(context_response)
    cause_response = _sensitive_http_artifact()
    cause_handles = _retain_http_handles(cause_response)

    cycle: list[object] = []
    cycle.extend((cycle, {"nested": [args_response]}))
    original = RuntimeError(GRAPH_LOCATION, cycle)
    context = SyntheticRequestFailure(context_response)
    cause = SyntheticRequestFailure(cause_response)
    original.__context__ = context
    original.__cause__ = cause

    legacy_auth._clear_auth_exception_chain(original)

    assert original.args == ()
    assert original.__context__ is None
    assert original.__cause__ is None
    assert context.args == ()
    assert context.__context__ is None
    assert context.__cause__ is None
    assert cause.args == ()
    assert cause.__context__ is None
    assert cause.__cause__ is None
    _assert_retained_http_handles_cleared(
        args_response,
        args_handles[0],
        args_handles[1],
        args_handles[2],
    )
    _assert_retained_http_handles_cleared(
        context_response,
        context_handles[0],
        context_handles[1],
        context_handles[2],
    )
    _assert_retained_http_handles_cleared(
        cause_response,
        cause_handles[0],
        cause_handles[1],
        cause_handles[2],
    )


def test_production_scrubber_preserves_fixed_aras_error_fields_while_clearing_artifact() -> None:
    response = _sensitive_http_artifact()
    handles = _retain_http_handles(response)
    error = legacy_auth.ArasAuthError(
        "AUTH_NETWORK_FAILED",
        "The authentication service could not be reached.",
        stage="metadata",
        http_status=502,
        substage="navigate",
        category="timeout",
        credential_touched=False,
    )
    error.response = response
    expected_args = error.args
    expected_fields = (
        error.code,
        error.stage,
        error.http_status,
        error.substage,
        error.category,
        error.credential_touched,
    )

    legacy_auth._clear_auth_exception_chain(error)

    assert error.args == expected_args
    assert str(error) == "The authentication service could not be reached."
    assert (
        error.code,
        error.stage,
        error.http_status,
        error.substage,
        error.category,
        error.credential_touched,
    ) == expected_fields
    assert error.__context__ is None
    assert error.__cause__ is None
    _assert_retained_http_handles_cleared(
        response,
        handles[0],
        handles[1],
        handles[2],
    )


def test_production_scrubber_depth_and_budget_are_bounded_and_repeatable() -> None:
    depth_allowed = _sensitive_http_artifact()
    depth_allowed_handles = _retain_http_handles(depth_allowed)
    # The retained response graph is two edges deep (history -> request), so
    # starting at depth 6 exercises the inclusive depth-8 boundary.
    legacy_auth._scrub_http_exception_artifact(depth_allowed, depth=6)
    _assert_retained_http_handles_cleared(
        depth_allowed,
        depth_allowed_handles[0],
        depth_allowed_handles[1],
        depth_allowed_handles[2],
    )

    beyond_depth = _sensitive_http_artifact()
    legacy_auth._scrub_http_exception_artifact(beyond_depth, depth=9)
    assert beyond_depth.closed is False
    assert beyond_depth._content != b""

    budgeted = _sensitive_http_artifact()
    budgeted_handles = _retain_http_handles(budgeted)
    wrapper = RuntimeError([budgeted])
    budget = [2]
    legacy_auth._scrub_http_exception_artifact(wrapper, budget=budget)
    assert budget == [0]
    assert wrapper.args == ()
    assert budgeted.closed is False
    assert budgeted._content != b""

    legacy_auth._scrub_http_exception_artifact(budgeted)
    _assert_retained_http_handles_cleared(
        budgeted,
        budgeted_handles[0],
        budgeted_handles[1],
        budgeted_handles[2],
    )


def test_production_scrubber_does_not_traverse_or_modify_arbitrary_business_objects() -> None:
    response = _sensitive_http_artifact()

    class BusinessObject:
        def __init__(self) -> None:
            self.payload = response
            self.label = GRAPH_LOCATION
            self.mutations = 0

        def __iter__(self):
            self.mutations += 1
            raise AssertionError("business object must not be traversed")

    business = BusinessObject()
    original = RuntimeError({"business": business})

    legacy_auth._clear_auth_exception_chain(original)

    assert original.args == ()
    assert business.payload is response
    assert business.label == GRAPH_LOCATION
    assert business.mutations == 0
    assert response.closed is False
    assert response._content != b""


def test_final_outer_error_graph_pre_touch_request_is_clean(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    artifact = _sensitive_http_artifact()
    transport_error = SyntheticRequestFailure(artifact)
    session = FakeSession([transport_error])
    monkeypatch.setattr(code_auth.requests, "Session", lambda: session)
    monkeypatch.setattr(code_auth, "_new_state", lambda: GRAPH_STATE)

    error = _capture_final_b2_audit_error()

    assert error.code == "AUTH_NETWORK_FAILED"
    assert error.credential_touched is False
    _assert_final_error_graph_is_clean(error)
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True


def test_final_outer_error_graph_post_touch_request_and_state_is_clean(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    artifact = _sensitive_http_artifact()
    transport_error = SyntheticRequestFailure(artifact)
    responses = _success_responses()
    responses[4] = FakeResponse(
        status=302,
        location=(
            code_auth.ACCOUNT_ORIGIN
            + code_auth.REALM_PATH_PREFIX
            + "continue?state="
            + GRAPH_STATE
            + "&code="
            + GRAPH_CODE
        ),
    )
    session, validations = _install_flow(
        monkeypatch,
        [*responses[:5], transport_error],
    )
    monkeypatch.setattr(code_auth, "_new_state", lambda: GRAPH_STATE)

    error = _capture_final_b2_audit_error()

    assert error.code == "AUTH_NETWORK_FAILED"
    assert error.credential_touched is True
    _assert_final_error_graph_is_clean(error)
    assert validations == []
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True


def test_final_outer_error_graph_token_payload_is_clean(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    callback = (
        ARAS
        + "client/redirect.html?code="
        + GRAPH_CODE
        + "&state="
        + GRAPH_STATE
    )
    responses = _success_responses(
        callback_location=callback,
        token=GRAPH_TOKEN,
        token_scope="profile",
    )
    token_response = responses[-1]
    session, validations = _install_flow(monkeypatch, responses)
    monkeypatch.setattr(code_auth, "_new_state", lambda: GRAPH_STATE)

    error = _capture_final_b2_audit_error()

    assert error.code == "AUTH_TOKEN_INVALID"
    assert error.credential_touched is True
    _assert_final_error_graph_is_clean(error)
    assert token_response.closed is True
    assert token_response._content == b""
    assert token_response.request.body is None
    assert token_response.request.url == ""
    assert token_response.request.headers == {}
    assert validations == []
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True


def test_final_outer_error_graph_soap_failure_is_clean(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    callback = (
        ARAS
        + "client/redirect.html?code="
        + GRAPH_CODE
        + "&state="
        + GRAPH_STATE
    )
    responses = _success_responses(
        callback_location=callback,
        token=GRAPH_TOKEN,
    )
    session, _validations = _install_flow(monkeypatch, responses)
    monkeypatch.setattr(code_auth, "_new_state", lambda: GRAPH_STATE)
    soap_artifact = _sensitive_http_artifact()

    class SoapFailureValidator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("legacy login must not be used")

        def validate_authenticated_session(self, target, item_type):  # type: ignore[no-untyped-def]
            response = soap_artifact
            assert response is soap_artifact
            assert target.headers["Authorization"] == "Bearer " + GRAPH_TOKEN
            assert item_type == "EWO_O"
            raise legacy_auth.ArasAuthError(
                "AUTH_VALIDATION_FAILED",
                "The Aras session could not be validated.",
                stage="validation",
                http_status=401,
                substage="session_extract",
                category="protocol",
                credential_touched=True,
            )

    monkeypatch.setattr(
        code_auth.legacy_auth,
        "ArasPasswordAuthClient",
        SoapFailureValidator,
    )

    error = _capture_final_b2_audit_error()

    assert error.code == "AUTH_VALIDATION_FAILED"
    assert error.credential_touched is True
    _assert_final_error_graph_is_clean(error)
    assert soap_artifact.closed is True
    assert soap_artifact._content == b""
    assert soap_artifact.headers == {}
    assert soap_artifact.cookies == {}
    assert soap_artifact.history == []
    assert soap_artifact.request.body is None
    assert soap_artifact.request.url == ""
    assert soap_artifact.request.headers == {}
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True
