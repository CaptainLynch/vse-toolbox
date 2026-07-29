from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.aras_auth import ArasAuthError


HOST = f"127.0.0.1:{web_app.FLASK_PORT}"
ORIGIN = f"http://{HOST}"
GATE_HEADERS = {
    "Host": HOST,
    "Origin": ORIGIN,
    "Sec-Fetch-Site": "same-origin",
}
PASSWORD = "web-unit-test-password"
TOKEN = "web-unit-test-token"


class OwnedSession:
    def __init__(self) -> None:
        self.headers = {"Authorization": "Bearer " + TOKEN}
        self.cookies = {"sid": "web-unit-test-cookie"}
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def enabled_client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_class = web_app.DatabaseManager
    monkeypatch.setattr(
        web_app,
        "DatabaseManager",
        lambda: db_class(tmp_path / "ephemeral-web.db"),
    )
    app = web_app.create_app(enable_ephemeral_test_session=True)
    app.config.update(TESTING=True)
    client = app.test_client()
    try:
        yield client, app
    finally:
        app.extensions["ephemeral_test_session_vault"].close()


def _bootstrap(client):  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/test-session/bootstrap",
        headers=GATE_HEADERS,
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 200
    return response.get_json()["csrf"], response


def _seed(client, csrf: str, *, module: str = "ewo"):  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/test-session/seed",
        headers={**GATE_HEADERS, "X-Test-Session-CSRF": csrf},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        json={
            "base_url": "http://aras.example/innovatorserver/",
            "username": "web-unit-test-user",
            "password": PASSWORD,
            "allow_insecure_http": True,
            "module": module,
            "filters": {"ewo_no": " EWO-1 "} if module == "ewo" else {"paa_no": " PAA-1 "},
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert PASSWORD not in response.get_data(as_text=True)
    assert "password" not in body["status"]
    assert body["status"]["password_cached"] is True
    return body["csrf"], response


def _post(client, path: str, csrf: str, **kwargs):  # type: ignore[no-untyped-def]
    return client.post(
        path,
        headers={**GATE_HEADERS, "X-Test-Session-CSRF": csrf},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        **kwargs,
    )


def test_test_session_is_default_off_and_all_responses_are_no_store(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_class = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_class(tmp_path / "off.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post(
        "/api/test-session/bootstrap",
        headers=GATE_HEADERS,
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 404
    assert response.get_json() == {
        "ok": False,
        "error": {"code": "TEST_SESSION_DISABLED"},
    }
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "vse_test_session=;" in response.headers["Set-Cookie"]
    page = client.get("/")
    assert 'data-test-session-enabled="false"' in page.get_data(as_text=True)


@pytest.mark.parametrize(
    ("headers", "remote_addr"),
    [
        ({"Host": HOST, "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}, "127.0.0.2"),
        ({"Host": "localhost:5000", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}, "127.0.0.1"),
        ({"Host": HOST, "Origin": "http://evil.invalid", "Sec-Fetch-Site": "same-origin"}, "127.0.0.1"),
        ({"Host": HOST, "Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}, "127.0.0.1"),
        ({**GATE_HEADERS, "Forwarded": "for=127.0.0.1"}, "127.0.0.1"),
        ({**GATE_HEADERS, "X-Forwarded-For": "127.0.0.1"}, "127.0.0.1"),
        ({**GATE_HEADERS, "X-Forwarded-Host": HOST}, "127.0.0.1"),
        ({**GATE_HEADERS, "X-Forwarded-Proto": "http"}, "127.0.0.1"),
    ],
)
def test_loopback_host_origin_fetch_and_forwarded_gate(
    enabled_client, headers: dict[str, str], remote_addr: str
) -> None:  # type: ignore[no-untyped-def]
    client, _app = enabled_client

    response = client.post(
        "/api/test-session/bootstrap",
        headers=headers,
        environ_base={"REMOTE_ADDR": remote_addr},
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "TEST_SESSION_LOOPBACK_REQUIRED"
    assert response.headers["Cache-Control"] == "no-store, private"


def test_bootstrap_cookie_csrf_rotation_seed_status_noecho_and_clear(enabled_client) -> None:  # type: ignore[no-untyped-def]
    client, _app = enabled_client
    page = client.get("/")
    assert 'data-test-session-enabled="true"' in page.get_data(as_text=True)
    csrf, bootstrap = _bootstrap(client)
    cookie = bootstrap.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/api/test-session" in cookie
    assert "Secure" not in cookie

    new_csrf, seed = _seed(client, csrf)
    assert new_csrf != csrf
    assert seed.get_json()["status"]["filters"] == {"ewo_no": "EWO-1"}
    rejected = _post(client, "/api/test-session/status", csrf, json={})
    assert rejected.status_code == 403
    assert rejected.get_json()["error"]["code"] == "TEST_SESSION_FORBIDDEN"

    status = _post(client, "/api/test-session/status", new_csrf, json={})
    assert status.status_code == 200
    text = status.get_data(as_text=True)
    assert PASSWORD not in text
    assert TOKEN not in text
    assert "password" not in status.get_json()["status"]

    cleared = _post(client, "/api/test-session/clear", new_csrf, json={})
    assert cleared.status_code == 200
    assert cleared.get_json() == {"ok": True, "status": "cleared"}
    assert "vse_test_session=;" in cleared.headers["Set-Cookie"]


def test_scheme_a_pretouch_auth_failure_destroys_session_without_retry(
    enabled_client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client, _app = enabled_client
    csrf, _bootstrap_response = _bootstrap(client)
    csrf, _seed_response = _seed(client, csrf)

    class PretouchFailure:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ArasAuthError(
                "AUTH_METADATA_INVALID",
                "safe contract failure",
                stage="metadata",
                substage="navigate",
                category="security",
                credential_touched=False,
            )

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", PretouchFailure)

    failed = _post(
        client,
        "/api/test-session/export",
        csrf,
        json={"module": "ewo", "filters": {"ewo_no": "EWO-1"}},
    )
    assert failed.status_code == 502
    assert failed.get_json()["error"]["code"] == "AUTH_METADATA_INVALID"
    assert "vse_test_session=;" in failed.headers["Set-Cookie"]
    gone = _post(client, "/api/test-session/status", csrf, json={})
    assert gone.status_code == 404


def test_posttouch_auth_failure_destroys_session_and_redacts_logs(
    enabled_client, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    client, _app = enabled_client
    csrf, _bootstrap_response = _bootstrap(client)
    csrf, _seed_response = _seed(client, csrf)

    class PosttouchFailure:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ArasAuthError(
                "AUTH_STATE_MISMATCH",
                "must-not-log " + PASSWORD + " " + TOKEN,
                stage="callback",
                substage="session_extract",
                category="security",
                credential_touched=True,
            )

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", PosttouchFailure)
    caplog.set_level(logging.WARNING, logger="vse_toolbox.web")

    response = _post(
        client,
        "/api/test-session/export",
        csrf,
        json={"module": "ewo", "filters": {}},
    )

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "AUTH_STATE_MISMATCH",
        "stage": "callback",
        "substage": "session_extract",
        "category": "security",
    }
    assert "vse_test_session=;" in response.headers["Set-Cookie"]
    combined = response.get_data(as_text=True) + "\n" + "\n".join(
        record.getMessage() for record in caplog.records
    )
    assert PASSWORD not in combined
    assert TOKEN not in combined
    assert "must-not-log" not in combined
    gone = _post(client, "/api/test-session/status", csrf, json={})
    assert gone.status_code == 404


def test_ewo_then_paa_uses_one_login_reuses_session_and_terminally_clears(
    enabled_client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client, _app = enabled_client
    csrf, _bootstrap_response = _bootstrap(client)
    csrf, _seed_response = _seed(client, csrf)
    session = OwnedSession()
    login_calls: list[tuple[str, str, str]] = []
    validation_calls: list[tuple[object, str]] = []
    exports: list[tuple[str, object]] = []

    class FakeAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, username: str, password: str, **kwargs):  # type: ignore[no-untyped-def]
            login_calls.append((username, password, kwargs["validation_item_type"]))
            return SimpleNamespace(session=session)

        def validate_authenticated_session(self, target, item_type):  # type: ignore[no-untyped-def]
            validation_calls.append((target, item_type))

    class FakeCrawler:
        def __init__(self, _base_url: str, *, session, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            assert session is not None
            self.headers: dict[str, str] = {}

        @staticmethod
        def _result(module: str):
            return SimpleNamespace(
                module=module,
                status="completed",
                count=2,
                file_name=module.upper() + "_unit.xlsx",
                saved_path="data\\output\\" + module.upper() + "_unit.xlsx",
                stop_reason="short_page",
                limit_reached=False,
                pages_fetched=2,
                duplicates_removed=1,
            )

        def export_ewo_report(self, filters, **_kwargs):  # type: ignore[no-untyped-def]
            exports.append(("ewo", filters))
            return self._result("ewo")

        def export_paa_report(self, filters, **_kwargs):  # type: ignore[no-untyped-def]
            exports.append(("paa", filters))
            return self._result("paa")

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", FakeAuth)
    monkeypatch.setattr(web_app, "ArasCrawlerClient", FakeCrawler)

    ewo = _post(
        client,
        "/api/test-session/export",
        csrf,
        json={"module": "ewo", "filters": {"ewo_no": " EWO-2 "}},
    )
    assert ewo.status_code == 200
    assert ewo.get_json()["test_session_destroyed"] is False
    assert len(login_calls) == 1
    assert login_calls[0][1] == PASSWORD
    assert PASSWORD not in ewo.get_data(as_text=True)
    assert TOKEN not in ewo.get_data(as_text=True)

    paa = _post(
        client,
        "/api/test-session/export",
        csrf,
        json={"module": "paa", "filters": {"paa_no": " PAA-2 "}},
    )
    assert paa.status_code == 200
    assert paa.get_json()["test_session_destroyed"] is True
    assert len(login_calls) == 1
    assert validation_calls == [(session, "PAA_O")]
    assert [module for module, _filters in exports] == ["ewo", "paa"]
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True
    assert "vse_test_session=;" in paa.headers["Set-Cookie"]


def test_frontend_test_session_has_single_direct_flow_and_no_secret_persistence() -> None:
    source = Path(web_app.__file__).with_name("static").joinpath("app.js").read_text(
        encoding="utf-8"
    )
    section = source[
        source.index("class TestSessionUiError") : source.index("async function runArasQuery")
    ]

    assert "TEST_SESSION_ENDPOINTS.query" not in section
    assert "crawl-all" not in section.casefold()
    assert "page_size" not in section
    assert "localStorage" not in section
    assert "sessionStorage" not in section
    assert "indexedDB" not in section
    assert "document.cookie" not in section
    assert "password_cached" in section
    assert "replacePasswordInput" in section
    assert "testSessionRunning" in section
    assert "TEST_SESSION_ENDPOINTS.export" in section
    assert "TEST_SESSION_ENDPOINTS.clear" in section


def test_frontend_bootstrap_is_only_issued_when_feature_is_explicitly_enabled() -> None:
    source = Path(web_app.__file__).with_name("static").joinpath("app.js").read_text(
        encoding="utf-8"
    )
    setup = source[
        source.index("function setupTestSession") : source.index("async function runArasQuery")
    ]

    assert "bootstrapTestSession({ silent: true })" not in setup
    assert 'document.body.dataset.testSessionEnabled !== "true"' in setup
    assert setup.index("return;") < setup.index("startEnabledTestSession();")


def test_frontend_disabled_runtime_executes_zero_bootstrap_clear_or_dom_hooks() -> None:
    source = Path(web_app.__file__).with_name("static").joinpath("app.js").read_text(
        encoding="utf-8"
    )
    start_function = source[
        source.index("function startEnabledTestSession") : source.index(
            "function setupTestSession"
        )
    ]
    setup_function = source[
        source.index("function setupTestSession") : source.index("async function runArasQuery")
    ]
    node_program = "\n".join(
        [
            'const document = { body: { dataset: { testSessionEnabled: "false" } },',
            '  getElementById() { throw new Error("disabled DOM hook"); } };',
            'const window = { addEventListener() { throw new Error("disabled lifecycle hook"); } };',
            'function bootstrapTestSession() { throw new Error("disabled bootstrap"); }',
            'function bestEffortClearTestSession() { throw new Error("disabled clear"); }',
            start_function,
            setup_function,
            "setupTestSession();",
        ]
    )

    completed = subprocess.run(
        ["node", "-e", node_program],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
