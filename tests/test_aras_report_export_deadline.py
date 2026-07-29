from __future__ import annotations

import time

import pytest

from services.aras_crawler import ArasCrawlerClient, EWOReportFilters
from services.aras_report_export import ArasReportExportError, _crawl_all


EMPTY_EWO_XML = (
    "<SOAP-ENV:Envelope xmlns:SOAP-ENV='http://schemas.xmlsoap.org/soap/envelope/'>"
    "<SOAP-ENV:Body><Result /></SOAP-ENV:Body>"
    "</SOAP-ENV:Envelope>"
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None


class _SlowPrewarmSession:
    def __init__(self, clock: _Clock, prewarm_delay: float, post_delay: float = 0.0) -> None:
        self.clock = clock
        self.prewarm_delay = prewarm_delay
        self.post_delay = post_delay
        self.cookies: dict[str, str] = {}
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        del url
        self.calls.append(("GET", kwargs["timeout"]))
        self.clock.value += self.prewarm_delay
        return _Response("<html/>")

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        del url
        timeout = kwargs["timeout"]
        self.calls.append(("POST", timeout))
        if self.post_delay > timeout:
            self.clock.value += timeout
            raise TimeoutError("simulated SOAP timeout")
        self.clock.value += self.post_delay
        return _Response(EMPTY_EWO_XML)


def test_export_deadline_is_recomputed_after_prewarm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    session = _SlowPrewarmSession(clock, prewarm_delay=4.0)
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        timeout=9.0,
        prewarm=True,
    )

    result = _crawl_all(
        client=client,
        filters=EWOReportFilters(),
        query_page=client.query_ewo_report,
        max_pages=5,
        max_records=10,
        deadline=5.0,
    )

    assert result.stop_reason == "empty_page"
    assert session.calls == [("GET", pytest.approx(5.0)), ("POST", pytest.approx(1.0))]
    assert client.timeout == 9.0
    assert client._request_deadline is None


def test_export_deadline_exhausted_by_prewarm_maps_to_timeout_and_restores_client(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    session = _SlowPrewarmSession(clock, prewarm_delay=6.0)
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        timeout=9.0,
        prewarm=True,
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        _crawl_all(
            client=client,
            filters=EWOReportFilters(),
            query_page=client.query_ewo_report,
            max_pages=5,
            max_records=10,
            deadline=5.0,
        )

    assert excinfo.value.code == "EXPORT_TIMEOUT"
    assert excinfo.value.http_status == 504
    assert session.calls == [("GET", pytest.approx(5.0))]
    assert client.timeout == 9.0
    assert client._request_deadline is None


def test_slow_prewarm_and_slow_soap_share_one_deadline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    session = _SlowPrewarmSession(clock, prewarm_delay=4.0, post_delay=2.0)
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        timeout=9.0,
        prewarm=True,
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        _crawl_all(
            client=client,
            filters=EWOReportFilters(),
            query_page=client.query_ewo_report,
            max_pages=5,
            max_records=10,
            deadline=5.0,
        )

    assert excinfo.value.code == "EXPORT_TIMEOUT"
    assert session.calls == [("GET", pytest.approx(5.0)), ("POST", pytest.approx(1.0))]
    assert clock.value == pytest.approx(5.0)
    assert client.timeout == 9.0
    assert client._request_deadline is None
