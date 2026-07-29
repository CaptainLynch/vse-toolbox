from __future__ import annotations

import inspect
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest

import services.aras_auth as auth_service
import services.aras_browser_auth as browser_auth
import services.aras_browser_transport as browser_transport
from services.aras_browser_transport import (
    BrowserArasSession,
    BrowserTransportError,
    CAP_ALL,
)
from services.aras_crawler import ArasCrawlerClient, EWOReportFilters, PAAReportFilters
from services.aras_report_export import ArasReportExportError


BASE = "http://ecm.example.test/innovatorserver"


def _soap(item_type: str, number: str = "R-1") -> str:
    return (
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
        "<SOAP-ENV:Body><Result>"
        f'<Item type="{item_type}" id="ID-1"><_no>{number}</_no></Item>'
        "</Result></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


class _TransportDriver:
    def __init__(self) -> None:
        self.async_calls: list[tuple[object, ...]] = []
        self.script_timeout = 0.0
        self.soap_pending = False
        self.soap_result: dict[str, object] | None = None
        self.cancel_calls = 0

    def set_script_timeout(self, value: float) -> None:
        self.script_timeout = value

    def execute_script(self, script: str, *args: object):
        if script == browser_transport._CAPABILITY_SCRIPT:
            return {"mask": 31, "candidates": 1}
        if script == browser_transport._BROWSER_SOAP_START_SCRIPT:
            self.async_calls.append(args)
            expected_type = str(args[6])
            self.soap_result = {
                "ok": True,
                "status_code": 200,
                "content_type": "text/xml; charset=utf-8",
                "text": _soap(expected_type),
                "mask": CAP_ALL,
            }
            return None
        if script == browser_transport._BROWSER_SOAP_POLL_SCRIPT:
            if self.soap_pending:
                return {"state": "pending"}
            result = self.soap_result
            self.soap_result = None
            return {"state": "done", "value": result}
        if script == browser_transport._BROWSER_SOAP_CANCEL_SCRIPT:
            self.cancel_calls += 1
            self.soap_result = None
            return True
        return True


class _Owner:
    def __init__(self) -> None:
        self.driver = _TransportDriver()
        self.closed = False
        self.cancelled = False
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        self.closed = True

    def request_cancel(self) -> None:
        self.cancelled = True


def _session() -> tuple[BrowserArasSession, _Owner]:
    owner = _Owner()
    return (
        BrowserArasSession(
            owner,
            base_url=BASE,
            deadline=10_000.0,
            clock=lambda: 1.0,
        ),
        owner,
    )


def test_browser_transport_gate_and_sequential_ewo_paa_scopes() -> None:
    session, owner = _session()
    assert session.perform_gate("EWO_O", 5.0) == CAP_ALL
    client = ArasCrawlerClient(BASE, session=session, prewarm=False)

    with client.begin_full_export_scope(
        "ewo",
        EWOReportFilters(project_code="P1"),
        max_pages=2,
        max_records=10,
        deadline=50.0,
    ):
        first = client.query_ewo_report(
            EWOReportFilters(project_code="P1"),
            page=1,
            page_size=50,
            max_records=10,
        )
        second = client.query_ewo_report(
            EWOReportFilters(project_code="P1"),
            page=2,
            page_size=50,
            max_records=10,
        )
    with client.begin_full_export_scope(
        "paa",
        PAAReportFilters(vehicle_keyword="M1"),
        max_pages=1,
        max_records=10,
        deadline=50.0,
    ):
        paa = client.query_paa_report(
            PAAReportFilters(vehicle_keyword="M1"),
            page=1,
            page_size=50,
            max_records=10,
        )

    assert first.rows[0]["_no"] == "R-1"
    assert second.rows[0]["_no"] == "R-1"
    assert paa.rows[0]["_no"] == "R-1"
    assert len(owner.driver.async_calls) == 4
    # Authorization is produced by the JavaScript itself, never an argument.
    assert all(
        "Bearer " not in repr(arguments) and "Authorization" not in repr(arguments)
        for arguments in owner.driver.async_calls
    )


def test_browser_transport_rejects_page_jump_filter_drift_and_ncr() -> None:
    session, _owner = _session()
    client = ArasCrawlerClient(BASE, session=session, prewarm=False)
    with client.begin_full_export_scope(
        "ewo",
        EWOReportFilters(project_code="P1"),
        max_pages=3,
        max_records=10,
        deadline=50.0,
    ):
        with pytest.raises(BrowserTransportError):
            client.query_ewo_report(
                EWOReportFilters(project_code="P1"),
                page=2,
                page_size=50,
                max_records=10,
            )
    with pytest.raises(BrowserTransportError):
        session.post(
            BASE + "/Server/InnovatorServer.aspx",
            data="<not-allowed/>",
            headers={"SOAPAction": "ApplyMethod", "Content-Type": "text/xml; charset=UTF-8"},
            timeout=1.0,
            allow_redirects=False,
        )


def test_browser_transport_is_thread_affine_cancelable_and_close_once() -> None:
    session, owner = _session()
    errors: list[BaseException] = []

    def other_thread() -> None:
        try:
            session.capability()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join()
    assert len(errors) == 1
    assert isinstance(errors[0], BrowserTransportError)
    session.request_cancel()
    assert owner.cancelled is True
    session.close()
    session.close()
    assert owner.close_count == 1


@pytest.mark.parametrize(
    ("stage", "category", "expected_code"),
    (
        ("auth_capability_wait", "capability_missing", "AUTH_SESSION_CAPABILITY_TIMEOUT"),
        (
            "auth_capability_wait",
            "capability_ambiguous",
            "AUTH_SESSION_CAPABILITY_AMBIGUOUS",
        ),
        ("auth_header_call", "authorization_unavailable", "AUTH_AUTHORIZATION_UNAVAILABLE"),
        ("soap_response", "http_auth", "AUTH_SOAP_GATE_FAILED"),
        ("soap_response", "http_forbidden", "AUTH_SOAP_GATE_FAILED"),
        ("soap_response", "redirect", "AUTH_SOAP_GATE_FAILED"),
        ("soap_parse", "soap_fault", "AUTH_SOAP_GATE_FAILED"),
        ("soap_parse", "item_type", "AUTH_SOAP_GATE_FAILED"),
        ("soap_dispatch", "timeout", "AUTH_DEADLINE_EXCEEDED"),
    ),
)
def test_browser_transport_failure_mapping_is_fixed_and_body_free(
    stage: str, category: str, expected_code: str
) -> None:
    session, owner = _session()

    owner.driver.soap_result = {
        "ok": False,
        "stage": stage,
        "category": category,
        "mask": 31,
        "private": "must-not-escape",
    }
    original_start = owner.driver.execute_script

    def fail(script: str, *args: object):
        if script == browser_transport._BROWSER_SOAP_START_SCRIPT:
            owner.driver.async_calls.append(args)
            return None
        return original_start(script, *args)

    owner.driver.execute_script = fail  # type: ignore[method-assign]
    with pytest.raises(BrowserTransportError) as excinfo:
        session.perform_gate("EWO_O", 5.0)

    error = excinfo.value
    assert error.code == expected_code
    assert error.stage == stage
    assert error.category == category
    assert error.capability_mask == 31
    assert "private" not in str(error)


def test_full_export_preserves_only_fixed_browser_failure_diagnostics() -> None:
    session, owner = _session()

    owner.driver.soap_result = {
        "ok": False,
        "stage": "soap_response",
        "category": "http_auth",
        "mask": 511,
        "body": "must-not-escape",
    }
    original_start = owner.driver.execute_script

    def fail(script: str, *args: object):
        if script == browser_transport._BROWSER_SOAP_START_SCRIPT:
            owner.driver.async_calls.append(args)
            return None
        return original_start(script, *args)

    owner.driver.execute_script = fail  # type: ignore[method-assign]
    client = ArasCrawlerClient(BASE, session=session, prewarm=False)

    with pytest.raises(ArasReportExportError) as excinfo:
        client.export_ewo_report(
            EWOReportFilters(),
            max_pages=1,
            max_records=10,
            timeout_seconds=5.0,
        )

    error = excinfo.value
    assert error.code == "AUTH_SOAP_GATE_FAILED"
    assert error.stage == "soap_response"
    assert error.category == "http_auth"
    assert error.capability_mask == 511
    assert error.retryable is False
    assert "must-not-escape" not in str(error)


class _FakeFetch:
    class RequestPaused:
        event_class = "paused"

    class RequestPattern:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class RequestStage:
        REQUEST = "request"

    @staticmethod
    def enable(*, patterns):
        return ("enable", patterns)

    @staticmethod
    def disable():
        return ("disable",)

    @staticmethod
    def continue_request(request_id):
        return ("continue", request_id)

    @staticmethod
    def fail_request(request_id, reason):
        return ("fail", request_id, reason)


class _FakeNetwork:
    class ResourceType:
        DOCUMENT = "document"

    class ErrorReason:
        BLOCKED_BY_CLIENT = "blocked"


class _FakeConnection:
    def __init__(self) -> None:
        self.callback = None
        self.callbacks = {"paused": []}
        self.commands: list[object] = []

    def add_callback(self, _event, callback):
        self.callback = callback
        self.callbacks["paused"].append(callback)
        return 7

    def remove_callback(self, _event, _identifier):
        self.callbacks["paused"].clear()

    def execute(self, command):
        self.commands.append(command)

    def emit(self, url: str, method: str) -> None:
        assert self.callback is not None
        self.callback(
            SimpleNamespace(
                request_id=len(self.commands) + 1,
                request=SimpleNamespace(url=url, method=method),
            )
        )


class _Control:
    def __init__(self, click=None) -> None:
        self.values: list[str] = []
        self._click = click

    def clear(self) -> None:
        self.values.clear()

    def send_keys(self, value: str) -> None:
        self.values.append(value)

    def click(self) -> None:
        if self._click is not None:
            self._click()


class _AuthDriver(_TransportDriver):
    def __init__(self) -> None:
        super().__init__()
        self.current_url = ""
        self.connection = _FakeConnection()
        self.devtools = SimpleNamespace(fetch=_FakeFetch, network=_FakeNetwork)
        self.quit_count = 0
        self.deleted_cookies = 0
        self.base_gets = 0
        self.capability_candidates = 1

    def get(self, value: str) -> None:
        parsed = urlsplit(value)
        if parsed.netloc == "ecm.example.test":
            self.base_gets += 1
            callback = quote(BASE + "/client/redirect.html", safe="")
            self.current_url = (
                browser_auth.ACCOUNT_ORIGIN
                + browser_auth.AUTHORIZE_PATH
                + "?client_id=ecm-front&response_type=code&scope=openid"
                + "&redirect_uri="
                + callback
            )
        else:
            self.current_url = value

    def set_page_load_timeout(self, _value: float) -> None:
        pass

    def start_devtools(self):
        return self.devtools, self.connection

    def execute_script(self, script: str, *args: object):
        if script == browser_transport._CAPABILITY_SCRIPT:
            mask = 31 if self.capability_candidates else 3
            return {
                "mask": mask,
                "candidates": self.capability_candidates,
            }
        return super().execute_script(script, *args)

    def execute_cdp_cmd(self, _name, _payload):
        return {}

    def delete_all_cookies(self) -> None:
        self.deleted_cookies += 1

    def quit(self) -> None:
        self.quit_count += 1


def test_owner_base_first_generated_state_single_submit_and_business_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _AuthDriver()
    service = SimpleNamespace(stop=lambda: None)

    def on_click() -> None:
        action = (
            browser_auth.ACCOUNT_ORIGIN
            + browser_auth.LOGIN_PATH
            + "?session_code=s&execution=e&client_id=ecm-front&tab_id=t"
        )
        driver.connection.emit(action, "POST")
        authorize_query = parse_qs(urlsplit(driver.current_url).query)
        state = authorize_query["state"][0]
        callback = (
            BASE
            + "/client/redirect.html?code=fake-code&state="
            + state
        )
        driver.connection.emit(callback, "GET")

    controls = (_Control(), _Control(), _Control(on_click))
    monkeypatch.setattr(browser_auth, "_locate_form", lambda _driver: controls)
    owner = browser_auth.ArasBrowserSessionOwner(
        BASE,
        allow_insecure_http=True,
        timeout=1.0,
        driver_factory=lambda _profile: (driver, service),
        sleeper=lambda _value: None,
    )
    session = owner.authenticate("fake-user", "fake-password", "EWO_O")

    assert session.owner is owner
    assert owner.state == "ACTIVE"
    assert owner.credential_submit_count == 1
    assert driver.base_gets == 1
    assert owner.capability_mask == CAP_ALL
    assert controls[0].values == ["fake-user"]
    assert controls[1].values == ["fake-password"]
    owner.close()
    owner.close()
    assert driver.quit_count == 1
    assert owner.state == "CLOSED"


def _login_action() -> str:
    return (
        browser_auth.ACCOUNT_ORIGIN
        + browser_auth.LOGIN_PATH
        + "?session_code=s&execution=e&client_id=ecm-front&tab_id=t"
    )


def _callback_for_driver(driver: _AuthDriver) -> str:
    state = parse_qs(urlsplit(driver.current_url).query)["state"][0]
    return BASE + "/client/redirect.html?code=fake-code&state=" + state


def test_shared_cancel_event_before_driver_start_closes_and_zeroizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_event = threading.Event()
    cancel_event.set()
    factory_calls = 0
    cleared: list[bytes] = []
    original_zeroize = browser_auth._zeroize

    def observe(value: bytearray) -> None:
        original_zeroize(value)
        cleared.append(bytes(value))

    def factory(_profile):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("driver must not start after cancellation")

    monkeypatch.setattr(browser_auth, "_zeroize", observe)
    owner = browser_auth.ArasBrowserSessionOwner(
        BASE,
        allow_insecure_http=True,
        timeout=1.0,
        cancel_event=cancel_event,
        driver_factory=factory,
    )

    with pytest.raises(browser_auth.BrowserAuthError) as excinfo:
        owner.authenticate("fake-user", "fake-password", "EWO_O")

    assert excinfo.value.code == "AUTH_EXPORT_CANCELLED"
    assert excinfo.value.category == "cancelled"
    assert excinfo.value.credential_touched is False
    assert factory_calls == 0
    assert owner.closed is True
    assert owner.credential_submit_count == 0
    assert len(cleared) >= 2
    assert all(value == b"" for value in cleared)


def test_shared_cancel_event_during_base_wait_closes_profile_and_driver() -> None:
    cancel_event = threading.Event()
    driver = _AuthDriver()
    profiles: list[Path] = []

    def never_authorize(value: str) -> None:
        driver.base_gets += 1
        driver.current_url = "about:blank"

    driver.get = never_authorize  # type: ignore[method-assign]

    def factory(profile: Path):
        profiles.append(profile)
        return driver, SimpleNamespace(stop=lambda: None)

    owner = browser_auth.ArasBrowserSessionOwner(
        BASE,
        allow_insecure_http=True,
        timeout=1.0,
        cancel_event=cancel_event,
        driver_factory=factory,
        sleeper=lambda _value: cancel_event.set(),
    )

    with pytest.raises(browser_auth.BrowserAuthError) as excinfo:
        owner.authenticate("fake-user", "fake-password", "EWO_O")

    assert excinfo.value.code == "AUTH_EXPORT_CANCELLED"
    assert excinfo.value.stage == "base_load"
    assert excinfo.value.credential_touched is False
    assert driver.quit_count == 1
    assert owner.closed is True
    assert profiles and not profiles[0].exists()


def test_shared_cancel_event_after_submit_stops_callback_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_event = threading.Event()
    driver = _AuthDriver()

    def on_click() -> None:
        driver.connection.emit(_login_action(), "POST")
        cancel_event.set()

    controls = (_Control(), _Control(), _Control(on_click))
    monkeypatch.setattr(browser_auth, "_locate_form", lambda _driver: controls)
    owner = browser_auth.ArasBrowserSessionOwner(
        BASE,
        allow_insecure_http=True,
        timeout=1.0,
        cancel_event=cancel_event,
        driver_factory=lambda _profile: (
            driver,
            SimpleNamespace(stop=lambda: None),
        ),
        sleeper=lambda _value: None,
    )

    with pytest.raises(browser_auth.BrowserAuthError) as excinfo:
        owner.authenticate("fake-user", "fake-password", "EWO_O")

    assert excinfo.value.code == "AUTH_EXPORT_CANCELLED"
    assert excinfo.value.stage == "callback_wait"
    assert excinfo.value.category == "cancelled"
    assert excinfo.value.credential_touched is True
    assert owner.credential_submit_count == 1
    assert driver.quit_count == 1
    assert owner.closed is True


def test_shared_cancel_event_during_capability_wait_closes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_event = threading.Event()
    driver = _AuthDriver()
    driver.capability_candidates = 0

    def on_click() -> None:
        driver.connection.emit(_login_action(), "POST")
        driver.connection.emit(_callback_for_driver(driver), "GET")

    controls = (_Control(), _Control(), _Control(on_click))
    monkeypatch.setattr(browser_auth, "_locate_form", lambda _driver: controls)
    owner = browser_auth.ArasBrowserSessionOwner(
        BASE,
        allow_insecure_http=True,
        timeout=1.0,
        cancel_event=cancel_event,
        driver_factory=lambda _profile: (
            driver,
            SimpleNamespace(stop=lambda: None),
        ),
        sleeper=lambda _value: cancel_event.set(),
    )

    with pytest.raises(browser_auth.BrowserAuthError) as excinfo:
        owner.authenticate("fake-user", "fake-password", "EWO_O")

    assert excinfo.value.code == "AUTH_EXPORT_CANCELLED"
    assert excinfo.value.stage == "auth_capability_wait"
    assert excinfo.value.credential_touched is True
    assert owner.credential_submit_count == 1
    assert driver.quit_count == 1
    assert owner.closed is True


def test_shared_cancel_event_aborts_runtime_gate_on_owner_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_event = threading.Event()
    driver = _AuthDriver()
    driver.soap_pending = True

    def on_click() -> None:
        driver.connection.emit(_login_action(), "POST")
        driver.connection.emit(_callback_for_driver(driver), "GET")

    controls = (_Control(), _Control(), _Control(on_click))
    monkeypatch.setattr(browser_auth, "_locate_form", lambda _driver: controls)
    owner = browser_auth.ArasBrowserSessionOwner(
        BASE,
        allow_insecure_http=True,
        timeout=1.0,
        cancel_event=cancel_event,
        driver_factory=lambda _profile: (
            driver,
            SimpleNamespace(stop=lambda: None),
        ),
        sleeper=lambda _value: cancel_event.set(),
    )

    with pytest.raises(browser_auth.BrowserAuthError) as excinfo:
        owner.authenticate("fake-user", "fake-password", "EWO_O")

    assert excinfo.value.code == "AUTH_EXPORT_CANCELLED"
    assert excinfo.value.stage == "soap_dispatch"
    assert excinfo.value.category == "cancelled"
    assert excinfo.value.credential_touched is True
    assert owner.credential_submit_count == 1
    assert driver.cancel_calls >= 1
    assert driver.quit_count == 1
    assert owner.closed is True


@pytest.mark.parametrize(
    "query",
    (
        "code=fake-code&state=wrong",
        "code=fake-code&state=good&state=second",
        "state=good",
        "code=fake-code",
    ),
)
def test_callback_gate_fails_closed_for_invalid_single_value_contract(
    query: str,
) -> None:
    connection = _FakeConnection()
    devtools = SimpleNamespace(fetch=_FakeFetch, network=_FakeNetwork)
    gate = browser_auth._CallbackGate(
        devtools=devtools,
        connection=connection,
        callback=BASE + "/client/redirect.html",
        expected_state=bytearray(b"good"),
    )
    gate.install()
    connection.emit(BASE + "/client/redirect.html?" + query, "GET")

    assert gate.event.is_set()
    assert gate.failed is True
    assert gate.state_verified is False
    assert gate.continued_original is False
    assert gate.close() is True
    assert gate.expected_state == bytearray()


def test_authorize_preserves_unique_existing_state_and_rejects_duplicates() -> None:
    callback = BASE + "/client/redirect.html"
    base_query = (
        "client_id=ecm-front&response_type=code&scope=openid&redirect_uri="
        + quote(callback, safe="")
    )
    value = browser_auth.ACCOUNT_ORIGIN + browser_auth.AUTHORIZE_PATH + "?" + base_query
    ok, state = browser_auth._validate_authorize(
        value + "&state=existing-state",
        callback=callback,
        allow_missing_state=False,
    )
    duplicate_ok, _duplicate_state = browser_auth._validate_authorize(
        value + "&state=one&state=two",
        callback=callback,
        allow_missing_state=False,
    )
    rebuilt, generated = browser_auth._with_state(value)

    assert ok is True
    assert state == "existing-state"
    assert duplicate_ok is False
    generated_state = parse_qs(urlsplit(rebuilt).query)["state"]
    assert len(generated_state) == 1
    assert len(generated) >= 32
    assert generated_state[0].encode("ascii") == bytes(generated)


def test_public_password_auth_uses_scheme_a_and_has_no_b2_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    calls: list[tuple[str, str, str]] = []

    class Owner:
        def __init__(self, *_args, **_kwargs) -> None:
            self.closed = False

        def authenticate(self, username: str, password: str, item_type: str):
            calls.append((username, password, item_type))
            return sentinel

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(browser_auth, "ArasBrowserSessionOwner", Owner)
    result = auth_service.ArasPasswordAuthClient(
        BASE, allow_insecure_http=True
    ).login("fake-user", "fake-password", validation_item_type="PAA_O")

    assert result.session is sentinel
    assert calls == [("fake-user", "fake-password", "PAA_O")]
    source = inspect.getsource(auth_service.ArasPasswordAuthClient.login)
    assert "aras_account_code_auth" not in source
    assert "ArasAccountCodeAuthClient" not in source


def test_public_password_auth_passes_shared_cancel_and_preserves_fixed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = threading.Event()
    shared.set()
    received: list[object] = []

    class CancelOwner:
        def __init__(self, *_args, **kwargs) -> None:
            received.append(kwargs.get("cancel_event"))

        def authenticate(self, *_args):
            raise browser_auth.BrowserAuthError(
                "AUTH_EXPORT_CANCELLED",
                stage="base_load",
                category="cancelled",
                http_status=409,
                credential_touched=False,
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(browser_auth, "ArasBrowserSessionOwner", CancelOwner)
    client = auth_service.ArasPasswordAuthClient(
        BASE,
        allow_insecure_http=True,
        cancel_event=shared,
    )

    with pytest.raises(auth_service.ArasAuthError) as excinfo:
        client.login("fake-user", "fake-password")

    assert received == [shared]
    assert excinfo.value.code == "AUTH_EXPORT_CANCELLED"
    assert excinfo.value.stage == "base_load"
    assert excinfo.value.category == "cancelled"
    assert excinfo.value.http_status == 409
    assert excinfo.value.credential_touched is False


def test_fixed_diagnostic_shape_discards_unknown_values() -> None:
    error = BrowserTransportError(
        "not-safe",
        stage="private-stage",
        category="private-category",
        capability_mask=999999,
    )
    assert error.code == "AUTH_SOAP_GATE_FAILED"
    assert error.stage == "soap_dispatch"
    assert error.category == "unexpected"
    assert 0 <= error.capability_mask <= CAP_ALL
    assert "private" not in str(error)


def test_scheme_a_source_has_no_runtime_false_gate_or_b2_import() -> None:
    auth_source = Path("services/aras_browser_auth.py").read_text(encoding="utf-8")
    transport_source = Path("services/aras_browser_transport.py").read_text(
        encoding="utf-8"
    )
    public_source = inspect.getsource(auth_service.ArasPasswordAuthClient.login)
    assert ".isLogged(" not in auth_source + transport_source
    assert "IomInnovator" not in auth_source + transport_source
    assert "aras_account_code_auth" not in public_source
    assert "window.stop" not in auth_source + transport_source
