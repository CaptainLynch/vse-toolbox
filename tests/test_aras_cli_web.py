from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

import main
import web.app as web_app
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from services.aras_auth import ArasAuthError
from services.aras_crawler import ArasCrawlerError, EWOReportPage, PAAReportPage
from services.aras_report_export import ArasReportExportError, ArasReportExportResult


@dataclass
class FakeProgress:
    file_id: str = "FILE-secret2"
    file_name: str = "progress.xlsx"
    record_id: str = "REC-1"


@dataclass
class FakeDetail:
    file_name: str = "detail.xlsx"


class FakeArasClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None

    def __init__(
        self,
        base_url,
        session=None,
        headers=None,
        cookies=None,
        timeout=30.0,
        prewarm=None,
        diagnostic_hook=None,
    ):  # type: ignore[no-untyped-def]
        self.base_url = base_url
        self.session = session
        self.headers = headers or {}
        self.cookies = cookies
        self.timeout = timeout
        self.diagnostic_hook = diagnostic_hook
        self.__class__.calls.append(
            {
                "base_url": base_url,
                "headers": self.headers,
                "cookies": cookies,
                "has_session": session is not None,
                "timeout": timeout,
                "prewarm": prewarm,
                "diagnostic_hook": diagnostic_hook,
            }
        )

    def query_ewo_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "ewo", "filters": filters, "page": page, "page_size": page_size, "max_records": max_records}
        )
        return EWOReportPage(
            rows=[
                {
                    "_no": "EWO-1",
                    "state": "Open",
                    "note": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=page,
            item_ids=["ID-1"],
            raw_xml="<xml/>",
        )

    def query_paa_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "paa", "filters": filters, "page": page, "page_size": page_size, "max_records": max_records}
        )
        return PAAReportPage(
            rows=[
                {
                    "_no": "PAA-1",
                    "state": "Open",
                    "note": "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=page,
            item_ids=["PAA-ID-1"],
            raw_xml="<xml/>",
        )

    def crawl_paa_report_all(self, filters, page_size=50, max_pages=20, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {
                "method": "paa_all",
                "filters": filters,
                "page_size": page_size,
                "max_pages": max_pages,
                "max_records": max_records,
            }
        )
        return PAAReportPage(
            rows=[
                {
                    "_no": "PAA-2",
                    "state": "Closed",
                    "note": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 token=tok123",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=2,
            item_ids=["PAA-ID-2"],
            raw_xml="<xml/>",
        )

    def export_ewo_report(
        self,
        filters,
        max_pages=500,
        max_records=12000,
        timeout_seconds=300.0,
    ):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {
                "method": "ewo_export",
                "filters": filters,
                "max_pages": max_pages,
                "max_records": max_records,
                "timeout_seconds": timeout_seconds,
            }
        )
        return ArasReportExportResult(
            module="ewo",
            status="completed",
            count=51,
            file_name="EWO_20260722_130000.xlsx",
            saved_path=Path("data/output/EWO_20260722_130000.xlsx"),
            stop_reason="short_page",
            limit_reached=False,
            pages_fetched=2,
            duplicates_removed=1,
        )

    def export_paa_report(
        self,
        filters,
        max_pages=500,
        max_records=12000,
        timeout_seconds=300.0,
    ):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {
                "method": "paa_export",
                "filters": filters,
                "max_pages": max_pages,
                "max_records": max_records,
                "timeout_seconds": timeout_seconds,
            }
        )
        return ArasReportExportResult(
            module="paa",
            status="partial",
            count=120,
            file_name="PAA_20260722_130000_PARTIAL.xlsx",
            saved_path=Path("data/output/PAA_20260722_130000_PARTIAL.xlsx"),
            stop_reason="max_records",
            limit_reached=True,
            pages_fetched=3,
            duplicates_removed=2,
        )

    def query_ncr_approval_progress(self, filters):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append({"method": "progress", "filters": filters})
        return FakeProgress()

    def extract_ncr_approval_detail(self, filters):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append({"method": "detail", "filters": filters})
        return FakeDetail()


@pytest.fixture(autouse=True)
def disable_cli_aras_diagnostics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        main,
        "_ask_aras_diagnostic_options",
        lambda **_kwargs: DiagnosticOptions(),
    )


@pytest.fixture()
def client(monkeypatch, tmp_path):
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    monkeypatch.setattr(web_app, "ArasCrawlerClient", FakeArasClient)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "web-test.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_web_ewo_export_contract_preserves_all_filters_and_no_auth_echo(client) -> None:
    response = client.post(
        "/api/aras/ewo/export",
        json={
            "base_url": "  http://aras.example  ",
            "headers": {" X-Test ": " yes ", "Authorization": "secret-auth"},
            "cookie": " sid=secret-cookie ",
            "filters": {
                "ewo_no": " EWO-1 ",
                "project_code": " P100 ",
                "subject_keyword": " seat ",
                "change_type": " major ",
                "change_sub_type": " drawing ",
                "area": " PT ",
                "state": " Open ",
                "rsp_department": " VSE ",
                "rsp_department_keyword": " Body Engineering ",
                "model_keyword": " F610S ",
                "submit_start": " 2026-01-01 ",
                "submit_end": " 2026-01-31 ",
            },
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "module": "ewo",
        "status": "completed",
        "count": 51,
        "file_name": "EWO_20260722_130000.xlsx",
        "saved_path": "data\\output\\EWO_20260722_130000.xlsx",
        "stop_reason": "short_page",
        "limit_reached": False,
        "pages_fetched": 2,
        "duplicates_removed": 1,
    }
    init_call = FakeArasClient.calls[0]
    assert init_call["base_url"] == "http://aras.example"
    assert init_call["headers"]["X-Test"] == "yes"  # type: ignore[index]
    assert init_call["headers"]["Cookie"] == "sid=secret-cookie"  # type: ignore[index]
    export_call = next(call for call in FakeArasClient.calls if call.get("method") == "ewo_export")
    filters = export_call["filters"]
    assert filters == main.EWOReportFilters(
        ewo_no="EWO-1",
        project_code="P100",
        subject_keyword="seat",
        change_type="major",
        change_sub_type="drawing",
        area="PT",
        state="Open",
        rsp_department="VSE",
        rsp_department_keyword="Body Engineering",
        model_keyword="F610S",
        submit_start="2026-01-01",
        submit_end="2026-01-31",
    )
    response_text = response.get_data(as_text=True)
    assert "secret-cookie" not in response_text
    assert "secret-auth" not in response_text
    assert "raw_xml" not in response_text


def test_web_paa_export_contract_preserves_all_filters_limits_and_partial_summary(client) -> None:
    response = client.post(
        "/api/aras/paa/export",
        json={
            "base_url": "http://aras.example",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {
                "paa_no": " PAA-1 ",
                "ewo_no": " EWO-1 ",
                "state": " Open ",
                "area": " PT ",
                "base": " Base-A ",
                "department_keyword": " Body Engineering ",
                "vehicle_keyword": " Vehicle ",
                "submit_start": " 2026-01-01 ",
                "submit_end": " 2026-01-31 ",
                "mtl_rq_start": " 2026-02-01 ",
                "mtl_rq_end": " 2026-02-28 ",
            },
            "limits": {"max_pages": 6, "max_records": 120, "timeout_seconds": 20.5},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {
        "ok": True,
        "module": "paa",
        "status": "partial",
        "count": 120,
        "file_name": "PAA_20260722_130000_PARTIAL.xlsx",
        "saved_path": "data\\output\\PAA_20260722_130000_PARTIAL.xlsx",
        "stop_reason": "max_records",
        "limit_reached": True,
        "pages_fetched": 3,
        "duplicates_removed": 2,
    }
    export_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_export")
    assert export_call["filters"] == main.PAAReportFilters(
        paa_no="PAA-1",
        ewo_no="EWO-1",
        state="Open",
        area="PT",
        base="Base-A",
        department_keyword="Body Engineering",
        vehicle_keyword="Vehicle",
        submit_start="2026-01-01",
        submit_end="2026-01-31",
        mtl_rq_start="2026-02-01",
        mtl_rq_end="2026-02-28",
    )
    assert export_call["max_pages"] == 6
    assert export_call["max_records"] == 120
    assert export_call["timeout_seconds"] == 20.5
    assert "secret-cookie" not in response.get_data(as_text=True)
    assert "secret-auth" not in response.get_data(as_text=True)
    assert "raw_xml" not in response.get_data(as_text=True)


def test_web_password_auth_is_primary_ephemeral_path_and_finally_closes_session(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    class EphemeralSession:
        def __init__(self) -> None:
            self.headers = {"Authorization": "Bearer fictional-access"}
            self.cookies = {"sid": "fictional-session"}
            self.closed = False

        def close(self) -> None:
            self.closed = True

    session = EphemeralSession()
    logins: list[dict[str, object]] = []

    class FakePasswordAuth:
        def __init__(self, base_url: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            logins.append({"base_url": base_url, **kwargs})

        def login(self, username: str, password: str, **kwargs):  # type: ignore[no-untyped-def]
            logins.append({"username": username, "password": password, **kwargs})
            return SimpleNamespace(session=session)

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", FakePasswordAuth)
    response = client.post(
        "/api/aras/ewo/export",
        json={
            "base_url": "http://aras.example",
            "username": "fake-user",
            "password": "fake-password",
            "allow_insecure_http": True,
            "filters": {
                "rsp_department_keyword": " Body Engineering ",
                "model_keyword": " F610S ",
            },
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "fake-password" not in body
    assert "fictional-access" not in body
    assert "fictional-session" not in body
    assert len([entry for entry in logins if "username" in entry]) == 1
    assert logins[0]["allow_insecure_http"] is True
    assert session.headers == {}
    assert session.cookies == {}
    assert session.closed is True
    construction = next(call for call in FakeArasClient.calls if "has_session" in call)
    assert construction["has_session"] is True
    assert construction["prewarm"] is False


@pytest.mark.parametrize(
    ("internal_stage", "public_stage"),
    [("browser", "browser"), ("future-private-stage", "authentication")],
)
def test_web_auth_diagnostics_are_allowlisted_and_logs_only_stable_codes(
    client,
    monkeypatch,
    caplog,
    internal_stage: str,
    public_stage: str,
) -> None:  # type: ignore[no-untyped-def]
    class FailingAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ArasAuthError(
                "AUTH_BROWSER_FAILED",
                (
                    "diagnostic-message-must-not-be-logged "
                    "url-marker body-marker selector-marker credential-marker"
                ),
                stage=internal_stage,
                http_status=502,
                substage="callback_wait",
                category="timeout",
            )

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", FailingAuth)
    caplog.set_level(logging.WARNING, logger="vse_toolbox.web")

    response = client.post(
        "/api/aras/ewo/export",
        json={
            "base_url": "http://aras.example",
            "username": "fake-user",
            "password": "fake-password",
            "allow_insecure_http": True,
            "filters": {},
        },
    )

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "AUTH_BROWSER_FAILED",
        "stage": public_stage,
        "substage": "callback_wait",
        "category": "timeout",
    }
    messages = [record.getMessage() for record in caplog.records if record.name == "vse_toolbox.web"]
    assert messages[-1] == (
        "Aras authentication failed: code=AUTH_BROWSER_FAILED "
        f"stage={public_stage} substage=callback_wait category=timeout"
    )
    combined = "\n".join(messages)
    assert "diagnostic-message-must-not-be-logged" not in combined
    assert "url-marker" not in combined
    assert "body-marker" not in combined
    assert "selector-marker" not in combined
    assert "credential-marker" not in combined
    assert "http://" not in combined
    assert "<html" not in combined.casefold()
    assert "fake-password" not in combined


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("AUTH_BROWSER_POLICY_BLOCKED", "security"),
        ("AUTH_BROWSER_NETWORK_FAILED", "webdriver"),
    ],
)
def test_web_navigation_auth_failures_never_reflect_raw_error_text(
    client, monkeypatch, caplog, code: str, category: str
) -> None:  # type: ignore[no-untyped-def]
    raw_detail = "opaque-raw-errorText-url-body-selector-credential"

    class FailingAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ArasAuthError(
                code,
                raw_detail,
                stage="browser",
                http_status=502,
                substage="navigate",
                category=category,
            )

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", FailingAuth)
    caplog.set_level(logging.WARNING, logger="vse_toolbox.web")

    response = client.post(
        "/api/aras/ewo/export",
        json={
            "base_url": "http://aras.example",
            "username": "fake-user",
            "password": "fake-password",
            "allow_insecure_http": True,
            "filters": {},
        },
    )

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": code,
        "stage": "browser",
        "substage": "navigate",
        "category": category,
    }
    response_text = response.get_data(as_text=True)
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "vse_toolbox.web"
    ]
    assert messages[-1] == (
        f"Aras authentication failed: code={code} "
        f"stage=browser substage=navigate category={category}"
    )
    assert raw_detail not in response_text
    assert raw_detail not in "\n".join(messages)
    assert "fake-password" not in response_text
    assert "fake-password" not in "\n".join(messages)


def test_frontend_auth_stage_labels_ignore_unknown_values() -> None:
    javascript = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    labels = re.search(
        r"const AUTH_STAGE_LABELS = Object\.freeze\(\{(?P<body>.*?)\}\);",
        javascript,
        re.DOTALL,
    )
    assert labels is not None
    label_body = labels.group("body")
    for stage in web_app._PUBLIC_AUTH_STAGES:
        assert re.search(rf"^\s*{re.escape(stage)}\s*:", label_body, re.MULTILINE)
    assert not re.search(r"^\s*authentication\s*:", label_body, re.MULTILINE)
    assert "function fixedDiagnosticLabel(labels, value)" in javascript
    assert "Object.prototype.hasOwnProperty.call(labels, key)" in javascript
    assert re.search(r"\?\s*labels\[key\]\s*:\s*\"\"", javascript, re.DOTALL)


def test_web_drops_unknown_browser_diagnostics_from_json_and_logs(
    client, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    class FailingAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            error = ArasAuthError(
                "AUTH_BROWSER_FAILED",
                "private-message",
                stage="browser",
                http_status=502,
            )
            # Simulate an untrusted future producer bypassing constructor normalization.
            error.substage = "private-substage"
            error.category = "private-category"
            raise error

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", FailingAuth)
    caplog.set_level(logging.WARNING, logger="vse_toolbox.web")

    response = client.post(
        "/api/aras/paa/export",
        json={
            "base_url": "http://aras.example",
            "username": "fake-user",
            "password": "fake-password",
            "allow_insecure_http": True,
            "filters": {},
        },
    )

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "AUTH_BROWSER_FAILED",
        "stage": "browser",
    }
    message = next(
        record.getMessage()
        for record in reversed(caplog.records)
        if record.name == "vse_toolbox.web"
    )
    assert message == (
        "Aras authentication failed: code=AUTH_BROWSER_FAILED "
        "stage=browser substage= category="
    )
    assert "private" not in message


def test_frontend_browser_diagnostic_maps_are_exact_fixed_allowlists() -> None:
    javascript = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    def object_keys(name: str) -> set[str]:
        match = re.search(
            rf"const {name} = Object\.freeze\(\{{(?P<body>.*?)\}}\);",
            javascript,
            re.DOTALL,
        )
        assert match is not None
        return set(re.findall(r"^\s*([a-z_]+)\s*:", match.group("body"), re.MULTILINE))

    assert object_keys("AUTH_BROWSER_SUBSTAGE_LABELS") == set(
        web_app.BROWSER_AUTH_SUBSTAGES
    )
    assert object_keys("AUTH_BROWSER_CATEGORY_LABELS") == set(
        web_app.BROWSER_EXCEPTION_CATEGORIES
    )
    assert "fixedDiagnosticLabel(AUTH_BROWSER_SUBSTAGE_LABELS, safeError.substage)" in javascript
    assert "fixedDiagnosticLabel(AUTH_BROWSER_CATEGORY_LABELS, safeError.category)" in javascript
    assert "errorText" not in javascript


def test_web_http_password_auth_requires_explicit_one_time_flag_and_rejects_mixed_mode(
    client,
) -> None:  # type: ignore[no-untyped-def]
    common = {
        "base_url": "http://aras.example",
        "username": "fake-user",
        "password": "fake-password",
        "filters": {},
    }
    refused = client.post("/api/aras/ewo/export", json=common)
    assert refused.status_code == 400
    assert refused.get_json()["error"]["code"] == "INSECURE_HTTP_NOT_ALLOWED"
    assert "fake-password" not in refused.get_data(as_text=True)

    conflict = client.post(
        "/api/aras/ewo/export",
        json={**common, "allow_insecure_http": True, "headers": {"X-Test": "yes"}},
    )
    assert conflict.status_code == 400
    assert conflict.get_json()["error"]["code"] == "AUTH_MODE_CONFLICT"
    assert "fake-password" not in conflict.get_data(as_text=True)


def test_legacy_ewo_query_route_remains_compatible_but_is_not_user_facing(client) -> None:
    resp = client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "headers": {"X-Test": "yes", "Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {"ewo_no": "EWO-1", "project_code": "F610S"},
            "page": 2,
            "page_size": 25,
            "max_records": 100,
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload == {
        "ok": True,
        "data": {
            "rows": [{"_no": "EWO-1", "state": "Open", "note": "Cookie: [redacted] Authorization: [redacted]"}],
            "page": 2,
            "item_ids": ["ID-1"],
            "count": 1,
        },
    }
    init_call = FakeArasClient.calls[0]
    assert init_call["base_url"] == "http://aras.example"
    assert init_call["headers"]["Cookie"] == "sid=secret-cookie"  # type: ignore[index]
    assert "secret-cookie" not in resp.get_data(as_text=True)
    assert "secret-auth" not in resp.get_data(as_text=True)
    assert "abc123" not in resp.get_data(as_text=True)
    assert "secret2" not in resp.get_data(as_text=True)
    assert "secret3" not in resp.get_data(as_text=True)
    assert "xyz789" not in resp.get_data(as_text=True)
    assert "raw_xml" not in resp.get_data(as_text=True)
    assert "<secret-xml/>" not in resp.get_data(as_text=True)
    method_call = FakeArasClient.calls[1]
    assert method_call["page"] == 2
    assert method_call["page_size"] == 25
    assert method_call["max_records"] == 100
    assert method_call["filters"].ewo_no == "EWO-1"


def test_ncr_progress_and_detail_routes(client) -> None:
    common = {
        "base_url": "http://aras.example",
        "filters": {
            "buy_start": "2026-01-01",
            "project_names": ["F610S", "F610S DG"],
            "othercondition": "1",
        },
    }

    progress = client.post("/api/aras/ncr/progress", json=common)
    detail = client.post("/api/aras/ncr/detail", json=common)

    assert progress.status_code == 200
    assert progress.get_json()["data"] == {"file_name": "progress.xlsx", "record_id": "REC-1"}
    assert "file_id" not in progress.get_data(as_text=True)
    assert "FILE-secret2" not in progress.get_data(as_text=True)
    assert "secret2" not in progress.get_data(as_text=True)
    assert detail.status_code == 200
    assert detail.get_json()["data"] == {"file_name": "detail.xlsx"}
    progress_call = next(call for call in FakeArasClient.calls if call.get("method") == "progress")
    assert progress_call["filters"].project_names == ("F610S", "F610S DG")
    assert progress_call["filters"].othercondition == "1"


def test_legacy_paa_query_and_crawl_routes_remain_compatible_but_are_not_user_facing(client) -> None:
    query = client.post(
        "/api/aras/paa/query",
        json={
            "base_url": "http://aras.example",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {
                "paa_no": "PAA-1",
                "ewo_no": "EWO-1",
                "state": "Open",
                "area": "PT",
                "base": "Base-A",
                "vehicle_keyword": "Vehicle",
                "submit_start": "2026-01-01",
                "submit_end": "2026-01-31",
                "mtl_rq_start": "2026-02-01",
                "mtl_rq_end": "2026-02-28",
            },
            "page": 3,
            "page_size": 25,
            "max_records": 100,
        },
    )
    crawl = client.post(
        "/api/aras/paa/crawl-all",
        json={
            "base_url": "http://aras.example",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {"paa_no": "PAA-2"},
            "page_size": 40,
            "max_pages": 6,
            "max_records": 120,
        },
    )

    assert query.status_code == 200
    assert query.get_json()["data"]["rows"] == [
        {"_no": "PAA-1", "state": "Open", "note": "Set-Cookie: [redacted] Authorization: [redacted]"}
    ]
    assert query.get_json()["data"]["page"] == 3
    assert crawl.status_code == 200
    assert crawl.get_json()["data"]["rows"] == [
        {"_no": "PAA-2", "state": "Closed", "note": "Cookie: [redacted] Authorization: [redacted] token=[redacted]"}
    ]
    query_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa")
    assert query_call["filters"].paa_no == "PAA-1"
    assert query_call["filters"].mtl_rq_end == "2026-02-28"
    assert query_call["page"] == 3
    crawl_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert crawl_call["page_size"] == 40
    assert crawl_call["max_pages"] == 6
    assert crawl_call["max_records"] == 120
    assert "secret-cookie" not in query.get_data(as_text=True)
    assert "secret-auth" not in query.get_data(as_text=True)
    assert "abc123" not in query.get_data(as_text=True)
    assert "secret2" not in query.get_data(as_text=True)
    assert "secret3" not in query.get_data(as_text=True)
    assert "xyz789" not in query.get_data(as_text=True)
    assert "raw_xml" not in query.get_data(as_text=True)
    assert "secret-cookie" not in crawl.get_data(as_text=True)
    assert "secret-auth" not in crawl.get_data(as_text=True)
    assert "abc123" not in crawl.get_data(as_text=True)
    assert "tok123" not in crawl.get_data(as_text=True)
    assert "secret2" not in crawl.get_data(as_text=True)
    assert "secret3" not in crawl.get_data(as_text=True)
    assert "xyz789" not in crawl.get_data(as_text=True)
    assert "raw_xml" not in crawl.get_data(as_text=True)


def test_legacy_query_and_crawl_password_sessions_validate_expected_type_and_close(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    sessions = []
    validation_types: list[str] = []

    class EphemeralSession:
        def __init__(self) -> None:
            self.headers = {"Authorization": "Bearer fictional-access"}
            self.cookies = {"sid": "fictional-cookie"}
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakePasswordAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, _username: str, _password: str, **kwargs):  # type: ignore[no-untyped-def]
            validation_types.append(str(kwargs["validation_item_type"]))
            session = EphemeralSession()
            sessions.append(session)
            return SimpleNamespace(session=session)

    monkeypatch.setattr(web_app, "ArasPasswordAuthClient", FakePasswordAuth)
    common = {
        "base_url": "https://aras.example",
        "username": "fake-user",
        "password": "fake-password",
        "filters": {},
    }
    responses = [
        client.post("/api/aras/ewo/query", json={**common, "page": 1}),
        client.post("/api/aras/paa/query", json={**common, "page": 1}),
        client.post("/api/aras/paa/crawl-all", json={**common, "max_pages": 2}),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert validation_types == ["EWO_O", "PAA_O", "PAA_O"]
    assert len(sessions) == 3
    assert all(session.closed for session in sessions)
    assert all(session.headers == {} and session.cookies == {} for session in sessions)
    assert all("fake-password" not in response.get_data(as_text=True) for response in responses)


def test_ncr_rejects_password_mode_but_preserves_header_cookie_compatibility_and_cleanup(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    sessions = []

    class NcrSession:
        def __init__(self, cookies=None) -> None:  # type: ignore[no-untyped-def]
            self.headers = {"X-Session": "temporary"}
            self.cookies = dict(cookies or {})
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class NcrClient:
        def __init__(self, _base_url, headers=None, cookies=None, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            self.headers = dict(headers or {})
            self.session = NcrSession(cookies)
            sessions.append((self, self.session))

        def query_ncr_approval_progress(self, _filters):  # type: ignore[no-untyped-def]
            return FakeProgress()

        def extract_ncr_approval_detail(self, _filters):  # type: ignore[no-untyped-def]
            return FakeDetail()

    monkeypatch.setattr(web_app, "ArasCrawlerClient", NcrClient)
    password_payload = {
        "base_url": "https://aras.example",
        "username": "fake-user",
        "password": "fake-password",
        "filters": {},
    }
    rejected = client.post("/api/aras/ncr/progress", json=password_payload)
    assert rejected.status_code == 400
    assert rejected.get_json()["error"]["code"] == "AUTH_MODE_NOT_SUPPORTED"
    assert "fake-password" not in rejected.get_data(as_text=True)
    assert sessions == []

    fallback = {
        "base_url": "https://aras.example",
        "headers": {"Authorization": "Bearer fictional-header"},
        "cookie": "sid=fictional-cookie",
        "cookies": {"secondary": "fictional-secondary"},
        "filters": {},
    }
    progress = client.post("/api/aras/ncr/progress", json=fallback)
    detail = client.post("/api/aras/ncr/detail", json=fallback)

    assert progress.status_code == detail.status_code == 200
    assert len(sessions) == 2
    assert all(ncr_client.headers == {} for ncr_client, _session in sessions)
    assert all(session.headers == {} and session.cookies == {} for _client, session in sessions)
    assert all(session.closed for _client, session in sessions)
    combined = progress.get_data(as_text=True) + detail.get_data(as_text=True)
    for secret in ("fictional-header", "fictional-cookie", "fictional-secondary"):
        assert secret not in combined


def test_route_validation_and_aras_error_are_sanitized(client) -> None:
    missing = client.post("/api/aras/ewo/export", json={"filters": {}})
    assert missing.status_code == 400
    assert missing.get_json() == {
        "ok": False,
        "module": "ewo",
        "status": "failed",
        "error": {"code": "INVALID_REQUEST", "message": "base_url is required."},
    }

    FakeArasClient.fail = ArasReportExportError(
        "UPSTREAM_REQUEST_FAILED",
        'upstream failed Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 token=tok123 '
        'Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 '
        '"token":"tok123" {\'Authorization\': \'Bearer xyz789\'}',
        http_status=502,
    )
    failed = client.post("/api/aras/ewo/export", json={"base_url": "http://aras.example", "cookie": "sid=abc123"})
    text = failed.get_data(as_text=True)
    assert failed.status_code == 502
    assert failed.get_json()["error"]["code"] == "UPSTREAM_REQUEST_FAILED"
    assert failed.get_json()["module"] == "ewo"
    assert failed.get_json()["status"] == "failed"
    assert "abc123" not in text
    assert "secret2" not in text
    assert "secret3" not in text
    assert "xyz789" not in text
    assert "tok123" not in text

    cli_text = main._safe_error_message(
        ArasCrawlerError(
            "upstream failed Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 "
            "Bearer xyz789 token=tok123 api_key=key456\n" + ("x" * 500) + "TAIL"
        )
    )
    assert "abc123" not in cli_text
    assert "secret2" not in cli_text
    assert "secret3" not in cli_text
    assert "xyz789" not in cli_text
    assert "tok123" not in cli_text
    assert "key456" not in cli_text
    assert "\n" in cli_text
    assert "TAIL" in cli_text


def test_cli_helpers_parse_headers_and_render_export_summary_without_auth() -> None:
    headers = main._parse_header_lines(
        "X-Test: yes, Authorization: secret, Accept-Language: zh-CN,zh;q=0.9\nTIMEZONE_NAME: China Standard Time"
    )
    assert headers == {
        "X-Test": "yes",
        "Authorization": "secret",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "TIMEZONE_NAME": "China Standard Time",
    }

    table = main._render_aras_export_result(
        ArasReportExportResult(
            module="ewo",
            status="completed",
            count=51,
            file_name="EWO_20260722_130000.xlsx",
            saved_path=Path("data/output/EWO_20260722_130000.xlsx"),
            stop_reason="short_page",
            limit_reached=False,
            pages_fetched=2,
            duplicates_removed=1,
        )
    )
    console = Console(record=True, width=140)
    console.print(table)
    rendered = console.export_text()
    assert table.title == "Aras 全量导出结果"
    assert "EWO_20260722_130000.xlsx" in rendered
    assert "51" in rendered
    assert "short_page" in rendered
    assert "secret" not in repr(table)


def test_cli_aras_connection_defaults_browser_headers(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        prompt = str(args[0])
        if prompt.startswith("Aras base_url"):
            return ""
        if prompt.startswith("Extra headers"):
            return kwargs["default"]
        return ""

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)

    base_url, headers, cookies = main._ask_aras_connection()

    assert base_url == ""
    assert cookies is None
    assert headers == {}
    base_call = next((args, kwargs) for args, kwargs in calls if str(args[0]).startswith("Aras base_url"))
    assert base_call[1]["default"] == ""
    assert not any(str(args[0]).startswith("Cookie header") for args, _kwargs in calls)


def test_cli_aras_connection_cookie_header_is_plain_and_normalized(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(
        [
            "http://aras.example/innovatorserver",
            "",
        ]
    )
    input_lines = iter(["", "Cookie: sid=abc; token=x", ""])

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    base_url, headers, cookies = main._ask_aras_connection()

    assert base_url == "http://aras.example/innovatorserver"
    assert headers["Cookie"] == "sid=abc; token=x"
    assert cookies is None
    assert not any(str(args[0]).startswith("Cookie header") for args, _kwargs in calls)


def test_cli_aras_connection_multiline_cookie_paste_stays_in_cookie_prompt(monkeypatch) -> None:
    answers = iter(["http://aras.example/innovatorserver", ""])
    input_lines = iter(
        [
            "",
            "Cookie: sid=abc; token=x",
            "ASP.NET_SessionId=should-not-be-filter",
            "",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    _base_url, headers, _cookies = main._ask_aras_connection()

    assert headers["Cookie"] == "sid=abc; token=x"


def test_cli_aras_connection_ignores_cookie_control_characters(monkeypatch) -> None:
    answers = iter(["http://aras.example", ""])
    input_lines = iter(["", "\x16", ""])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    _base_url, headers, _cookies = main._ask_aras_connection()

    assert "Cookie" not in headers
    assert "control characters" in console.export_text()


def test_cli_aras_connection_accepts_multiline_authorization_headers(monkeypatch) -> None:
    answers = iter(["http://aras.example/innovatorserver"])
    input_lines = iter(
        [
            "Authorization: Bearer fake-token",
            "Cookie: sid=abc; token=x",
            "Accept-Language: zh-CN,zh;q=0.9",
            "",
            "",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    _base_url, headers, _cookies = main._ask_aras_connection()

    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["Cookie"] == "sid=abc; token=x"
    assert headers["Accept-Language"] == "zh-CN,zh;q=0.9"
    assert "可能需要 Authorization" not in console.export_text()


def test_cli_paa_helper_collects_every_filter_without_paging_prompts(monkeypatch) -> None:
    answers = iter(
        [
            "PAA-1",
            "EWO-1",
            "Open",
            "PT",
            "Base-A",
            "Body Engineering",
            "Vehicle",
            "2026-01-01",
            "2026-01-31",
            "2026-02-01",
            "2026-02-28",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))

    filters = main._ask_paa_filters()

    assert filters.paa_no == "PAA-1"
    assert filters.ewo_no == "EWO-1"
    assert filters.state == "Open"
    assert filters.area == "PT"
    assert filters.base == "Base-A"
    assert filters.department_keyword == "Body Engineering"
    assert filters.vehicle_keyword == "Vehicle"
    assert filters.submit_start == "2026-01-01"
    assert filters.submit_end == "2026-01-31"
    assert filters.mtl_rq_start == "2026-02-01"
    assert filters.mtl_rq_end == "2026-02-28"


def test_cli_ewo_helper_collects_both_contains_filters_without_paging_prompts(monkeypatch) -> None:
    answers = iter(
        [
            "EWO-1",
            "P100",
            "Subject",
            "Major",
            "Drawing",
            "PT",
            "Open",
            "Body Engineering",
            "F610S",
            "2026-01-01",
            "2026-01-31",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))

    filters = main._ask_ewo_filters()

    assert filters == main.EWOReportFilters(
        ewo_no="EWO-1",
        project_code="P100",
        subject_keyword="Subject",
        change_type="Major",
        change_sub_type="Drawing",
        area="PT",
        state="Open",
        rsp_department_keyword="Body Engineering",
        model_keyword="F610S",
        submit_start="2026-01-01",
        submit_end="2026-01-31",
    )


def test_cli_paa_export_render_has_only_safe_summary_fields() -> None:
    table = main._render_aras_export_result(
        ArasReportExportResult(
            module="paa",
            status="partial",
            count=120,
            file_name="PAA_20260722_130000_PARTIAL.xlsx",
            saved_path=Path("data/output/PAA_20260722_130000_PARTIAL.xlsx"),
            stop_reason="max_records",
            limit_reached=True,
            pages_fetched=3,
            duplicates_removed=2,
        )
    )
    console = Console(record=True, width=140)
    console.print(table)
    rendered = console.export_text()

    assert table.title == "Aras 全量导出结果"
    assert "PAA_20260722_130000_PARTIAL.xlsx" in rendered
    assert "120" in rendered
    assert "max_records" in rendered
    assert "raw_xml" not in rendered
    assert "Cookie" not in rendered
    assert "Authorization" not in rendered


def test_cli_diagnostic_report_disabled_does_not_create_file(tmp_path) -> None:
    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(),
        base_url="http://aras.example",
        mode="1",
        output_dir=tmp_path,
    )

    assert report.save("success") is None
    assert list(tmp_path.iterdir()) == []


def test_cli_diagnostic_report_safe_redacts_and_raw_preserves(tmp_path) -> None:
    safe = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=False),
        base_url="http://aras.example",
        mode="1",
        inputs={"headers": {"Cookie": "sid=secret-cookie", "Authorization": "Bearer secret-token"}},
        output_dir=tmp_path,
    )
    safe.record_exception(RuntimeError("failed Cookie: sid=secret-cookie token=secret-token"))
    safe_path = safe.save("failed")
    assert safe_path is not None
    safe_text = safe_path.read_text(encoding="utf-8")
    assert "secret-cookie" not in safe_text
    assert "secret-token" not in safe_text
    assert "[redacted]" in safe_text

    raw = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=True),
        base_url="http://aras.example",
        mode="1",
        inputs={"headers": {"Cookie": "sid=secret-cookie", "Authorization": "Bearer secret-token"}},
        output_dir=tmp_path,
    )
    raw.record_exception(RuntimeError("failed Cookie: sid=secret-cookie token=secret-token"))
    raw_path = raw.save("failed")
    assert raw_path is not None
    raw_text = raw_path.read_text(encoding="utf-8")
    assert "secret-cookie" in raw_text
    assert "secret-token" in raw_text


def test_cli_diagnostic_report_escapes_control_characters(tmp_path) -> None:
    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=True),
        base_url="http://aras.example",
        mode="1",
        output_dir=tmp_path,
    )
    report.record_http_event(
        {
            "stage": "prewarm",
            "method": "GET",
            "url": "http://aras.example/innovatorserver/Client/default.aspx",
            "request_headers": {"X-Test": "\x16"},
        }
    )

    path = report.save("failed")
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "\\x16" in text
    assert "\x16" not in text


def test_cli_ncr_renderers_do_not_leak_sensitive_values() -> None:
    console = Console(record=True, width=140)

    console.print(main._render_ncr_progress_result(FakeProgress()))
    console.print(main._render_ncr_detail_result(FakeDetail(file_name="detail.xlsx")))
    rendered = console.export_text()

    assert "NCR approval progress result" in rendered
    assert "NCR approval detail result" in rendered
    assert "progress.xlsx" in rendered
    assert "FILE-secret2" not in rendered
    assert "secret2" not in rendered


def test_cli_ncr_handlers_progress_and_detail(monkeypatch) -> None:
    for choice, method, title in [
        ("2", "progress", "NCR approval progress result"),
        ("3", "detail", "NCR approval detail result"),
    ]:
        FakeArasClient.calls = []
        FakeArasClient.fail = None
        filters = main.NCRApprovalFilters(ncr_no="NCR-1")
        monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
        answers = iter([choice, "http://aras.example"])
        monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
        monkeypatch.setattr(main, "_ask_aras_login_mode", lambda: "2")
        monkeypatch.setattr(main, "_ask_aras_connection", lambda _base: ("http://aras.example", {}, None))
        monkeypatch.setattr(main, "_ask_ncr_filters", lambda: filters)
        console = Console(record=True, width=140)
        monkeypatch.setattr(main, "console", console)

        main.handle_intranet_scrape(None)  # type: ignore[arg-type]

        method_call = next(call for call in FakeArasClient.calls if call.get("method") == method)
        assert method_call["filters"] == filters
        rendered = console.export_text()
        assert title in rendered
        assert "FILE-secret2" not in rendered
        assert "secret2" not in rendered


def test_cli_ewo_handler_has_one_full_export_path(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    filters = main.EWOReportFilters(ewo_no="EWO-1", project_code="P100")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    answers = iter(["1", "http://aras.example"])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(main, "_ask_aras_login_mode", lambda: "2")
    monkeypatch.setattr(main, "_ask_aras_connection", lambda _base: ("http://aras.example", {"Authorization": "secret"}, None))
    monkeypatch.setattr(main, "_ask_ewo_filters", lambda: filters)
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    method_call = next(call for call in FakeArasClient.calls if call.get("method") == "ewo_export")
    assert method_call["filters"] == filters
    rendered = console.export_text()
    assert "EWO 筛选后全量导出" in rendered
    assert "Aras 全量导出结果" in rendered
    assert "EWO_20260722_130000.xlsx" in rendered
    assert "secret" not in rendered
    assert not any(call.get("method") == "ewo" for call in FakeArasClient.calls)


def test_cli_paa_handler_has_one_full_export_path(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    filters = main.PAAReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    answers = iter(["4", "http://aras.example"])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(main, "_ask_aras_login_mode", lambda: "2")
    monkeypatch.setattr(main, "_ask_aras_connection", lambda _base: ("http://aras.example", {}, None))
    monkeypatch.setattr(main, "_ask_paa_filters", lambda: filters)
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    method_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_export")
    assert method_call["filters"] == filters
    rendered = console.export_text()
    assert "PAA 筛选后全量导出" in rendered
    assert "Aras 全量导出结果" in rendered
    assert "PAA_20260722_130000_PARTIAL.xlsx" in rendered
    assert not any(call.get("method") in {"paa", "paa_all"} for call in FakeArasClient.calls)


def test_web_ewo_and_paa_expose_only_one_export_action_without_paging_inputs(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    javascript = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    aras_modes = javascript.split("const ARAS_MODES =", 1)[1].split("let arasMode", 1)[0]

    assert html.count('data-aras-mode="ewo"') == 1
    assert html.count('data-aras-mode="paa"') == 1
    assert html.count('id="aras-submit"') == 1
    assert "筛选后全量导出" in html
    assert not re.search(r'name=["\'](?:page|page_size)["\']', html)
    assert "分页查询" not in html
    assert "Crawl All" not in html
    assert aras_modes.count("endpoint: EXPORT_JOB_ENDPOINTS.start") == 2
    assert 'start: "/api/aras/export-jobs"' in javascript
    assert 'status: "/api/aras/export-jobs/status"' in javascript
    assert 'cancel: "/api/aras/export-jobs/cancel"' in javascript
    assert '"/api/aras/ewo/query"' not in aras_modes
    assert '"/api/aras/paa/query"' not in aras_modes
    assert '"/api/aras/paa/crawl-all"' not in aras_modes
    assert "page_size" not in aras_modes
    assert re.search(r'ewo:\s*\{[^}]*actionLabel: "筛选后全量导出"', aras_modes, re.DOTALL)
    assert re.search(r'paa:\s*\{[^}]*actionLabel: "筛选后全量导出"', aras_modes, re.DOTALL)


def test_web_export_running_state_blocks_duplicate_submit_and_clears_credentials() -> None:
    javascript = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")

    assert re.search(r"if\s*\(arasRunning\)\s*\{\s*return;\s*\}", javascript)
    assert "button.disabled = Boolean(isRunning)" in javascript
    assert "modeButton.disabled = Boolean(isRunning)" in javascript
    assert "payload.cookie = \"\"" in javascript
    assert "payload.password = \"\"" in javascript
    assert "payload.username = \"\"" in javascript
    assert "payload.headers = {}" in javascript
    assert "payload.filters = {}" in javascript
    assert re.search(r'name="password"\s+type="password"', html)
    assert re.search(r'name="allow_insecure_http"\s+type="checkbox"', html)
    assert not re.search(r'name="allow_insecure_http"[^>]*\bchecked\b', html)
    assert "console.log" not in javascript
    assert not re.search(
        r"(?:localStorage|sessionStorage)\.setItem\([^)]*(?:password|authorization|cookie|token)",
        javascript,
        re.IGNORECASE,
    )
    assert "正在全量导出" in javascript
    assert "导出记录数" in javascript
    assert "文件保存位置" in javascript
    assert "cancelArasExportJob" in javascript
    assert "EXPORT_JOB_ID_HEADER" in javascript
    assert "localStorage.setItem(THEME_KEY" in javascript
    assert "localStorage.setItem(EXPORT_JOB" not in javascript


def _start_export_job(client, module: str = "ewo"):  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/aras/export-jobs",
        json={
            "module": module,
            "base_url": "https://aras.example",
            "username": "fake-user",
            "password": "fake-password",
            "headers": {},
            "cookie": "",
            "filters": {"ewo_no": "EWO-1"} if module == "ewo" else {"paa_no": "PAA-1"},
        },
    )
    return response


def _poll_export_job(client, start_body):  # type: ignore[no-untyped-def]
    headers = {
        web_app._EXPORT_JOB_ID_HEADER: start_body["operation_id"],
        web_app._EXPORT_JOB_CSRF_HEADER: start_body["csrf"],
    }
    response = None
    for _ in range(100):
        response = client.get("/api/aras/export-jobs/status", headers=headers)
        if response.get_json()["status"] not in {"running", "cancelling"}:
            return response
        time.sleep(0.01)
    pytest.fail("export job did not reach a terminal state")


def test_web_export_job_is_ram_only_single_flight_and_returns_fixed_summary(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    fake = FakeArasClient("https://aras.example")
    monkeypatch.setattr(
        web_app, "_build_aras_client_from_payload", lambda _payload, **_kwargs: fake
    )

    started = _start_export_job(client)
    assert started.status_code == 202
    start_body = started.get_json()
    assert set(start_body) == {"ok", "module", "status", "operation_id", "csrf"}
    assert start_body["status"] == "running"
    terminal = _poll_export_job(client, start_body)
    assert terminal.status_code == 200
    body = terminal.get_json()
    assert body["ok"] is True
    assert body["status"] == "completed"
    assert body["module"] == "ewo"
    assert body["count"] == 51
    assert "operation_id" not in body
    assert "csrf" not in body
    assert "message" not in repr(body).lower()
    assert "vse_aras_export_job=;" in terminal.headers["Set-Cookie"]


def test_web_export_job_cancel_is_cooperative_and_worker_closes_session(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    entered = threading.Event()
    cancelled = threading.Event()
    closed = threading.Event()

    class Session:
        headers: dict[str, str] = {}
        cookies: dict[str, str] = {}

        def request_cancel(self) -> None:
            cancelled.set()

        def close(self) -> None:
            closed.set()

    class BlockingClient:
        def __init__(self) -> None:
            self.session = Session()
            self.headers: dict[str, str] = {}

        def export_ewo_report(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            entered.set()
            assert cancelled.wait(2.0)
            raise ArasReportExportError("EXPORT_TIMEOUT", "private", http_status=504)

    monkeypatch.setattr(
        web_app,
        "_build_aras_client_from_payload",
        lambda _payload, **_kwargs: BlockingClient(),
    )
    started = _start_export_job(client)
    start_body = started.get_json()
    assert entered.wait(2.0)
    headers = {
        web_app._EXPORT_JOB_ID_HEADER: start_body["operation_id"],
        web_app._EXPORT_JOB_CSRF_HEADER: start_body["csrf"],
    }
    cancelling = client.post("/api/aras/export-jobs/cancel", headers=headers)
    assert cancelling.status_code == 200
    assert cancelling.get_json() == {"ok": True, "status": "cancelling"}
    terminal = _poll_export_job(client, start_body)
    assert terminal.get_json()["status"] == "cancelled"
    assert terminal.get_json()["error"]["code"] == "AUTH_EXPORT_CANCELLED"
    assert closed.wait(2.0)


def test_web_export_job_cancel_interrupts_authentication_via_shared_event(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    entered = threading.Event()
    observed_cancel = threading.Event()

    def blocking_builder(_payload, *, cancel_event=None):  # type: ignore[no-untyped-def]
        assert isinstance(cancel_event, threading.Event)
        entered.set()
        assert cancel_event.wait(2.0)
        observed_cancel.set()
        raise ArasAuthError(
            "AUTH_EXPORT_CANCELLED",
            "private text must not escape",
            stage="base_load",
            category="cancelled",
            capability_mask=0,
        )

    monkeypatch.setattr(web_app, "_build_aras_client_from_payload", blocking_builder)
    started = _start_export_job(client)
    start_body = started.get_json()
    assert entered.wait(2.0)
    headers = {
        web_app._EXPORT_JOB_ID_HEADER: start_body["operation_id"],
        web_app._EXPORT_JOB_CSRF_HEADER: start_body["csrf"],
    }
    cancelling = client.post("/api/aras/export-jobs/cancel", headers=headers)
    assert cancelling.get_json() == {"ok": True, "status": "cancelling"}
    terminal = _poll_export_job(client, start_body)
    body = terminal.get_json()
    assert body["status"] == "cancelled"
    assert body["error"] == {
        "code": "AUTH_EXPORT_CANCELLED",
        "retryable": False,
        "stage": "base_load",
        "category": "cancelled",
        "capability_mask": 0,
    }
    assert observed_cancel.is_set()
    assert "private" not in repr(body)


def test_web_export_job_terminal_cancel_race_preserves_summary_until_status_poll(
    client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    fake = FakeArasClient("https://aras.example")
    monkeypatch.setattr(
        web_app, "_build_aras_client_from_payload", lambda _payload, **_kwargs: fake
    )
    started = _start_export_job(client)
    start_body = started.get_json()
    coordinator = client.application.extensions["aras_export_jobs"]
    for _ in range(100):
        with coordinator._lock:
            job = coordinator._jobs[start_body["operation_id"]]
            if job.status == "completed":
                break
        time.sleep(0.01)
    else:
        pytest.fail("export job did not complete before terminal race check")

    headers = {
        web_app._EXPORT_JOB_ID_HEADER: start_body["operation_id"],
        web_app._EXPORT_JOB_CSRF_HEADER: start_body["csrf"],
    }
    cancel_response = client.post("/api/aras/export-jobs/cancel", headers=headers)
    assert cancel_response.get_json() == {"ok": True, "status": "completed"}
    assert "vse_aras_export_job=;" not in cancel_response.headers.get("Set-Cookie", "")

    terminal = client.get("/api/aras/export-jobs/status", headers=headers)
    assert terminal.get_json()["status"] == "completed"
    assert terminal.get_json()["file_name"] == "EWO_20260722_130000.xlsx"
    assert "vse_aras_export_job=;" in terminal.headers["Set-Cookie"]


def test_overview_and_ncr_web_paths_remain_available(client) -> None:
    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert set(overview.get_json()) == {"projects", "deliverables", "feishu"}

    root = client.get("/").get_data(as_text=True)
    assert 'data-aras-mode="ncr-progress"' in root
    assert 'data-aras-mode="ncr-detail"' in root
    assert 'id="overview"' in root


def test_static_guards_for_boundaries_and_credentials() -> None:
    service_text = Path("services/aras_crawler.py").read_text(encoding="utf-8-sig")
    assert not re.search(r"\b(rich|flask|render_template|jsonify|document\.|window\.)\b", service_text)

    cli_web_text = "\n".join(
        Path(path).read_text(encoding="utf-8-sig")
        for path in [
            "main.py",
            "web/app.py",
            "web/templates/dashboard.html",
            "web/static/app.js",
            "web/static/style.css",
        ]
    )
    assert not re.search(r"(?:cookie|token|authorization|sessionid|csrf).{0,80}localStorage", cli_web_text, re.IGNORECASE)
    assert ("session" + "Storage") not in cli_web_text
    assert ("console" + ".log(") not in cli_web_text
    assert not re.search(
        r"requests\.(?:get|post|head|request)\(",
        Path("tests/test_aras_cli_web.py").read_text(encoding="utf-8-sig"),
    )


def test_cli_and_web_share_internal_chrome_first_auth_without_user_or_env_browser_choice() -> None:
    auth_source = Path("services/aras_auth.py").read_text(encoding="utf-8-sig")
    login_source = auth_source.split("def _login_with_selenium", 1)[1].split(
        "def _validate_session", 1
    )[0]
    main_source = Path("main.py").read_text(encoding="utf-8-sig")
    web_source = Path("web/app.py").read_text(encoding="utf-8-sig")
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    javascript = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    assert login_source.index("webdriver.ChromeOptions()") < login_source.index(
        "webdriver.EdgeOptions()"
    )
    assert login_source.index("webdriver.Chrome(options=chrome_options)") < login_source.index(
        "webdriver.Edge(options=edge_options)"
    )
    assert 'prefix="vse-aras-auth-chrome-"' in login_source
    assert 'prefix="vse-aras-auth-edge-"' in login_source
    assert "ArasPasswordAuthClient" in main_source
    assert "ArasPasswordAuthClient" in web_source

    public_surface = "\n".join((main_source, web_source, html, javascript))
    assert "VSE_ARAS_BROWSER" not in public_surface
    assert not re.search(
        r"(?:os\.(?:getenv|environ)|payload\.get|request\.json\.get)\([^\n)]*browser",
        public_surface,
        re.IGNORECASE,
    )
    assert not re.search(
        r"(?:name|id|data-[\w-]+)=[\"'][^\"']*(?:browser|chrome|edge)[^\"']*[\"']",
        html,
        re.IGNORECASE,
    )
    assert not re.search(
        r"(?:value|label|actionLabel)\s*:\s*[\"'](?:chrome|edge)[\"']",
        javascript,
        re.IGNORECASE,
    )
    assert not re.search(r"os\.(?:getenv|environ)", login_source)
