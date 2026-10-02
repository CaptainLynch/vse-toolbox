"""JSON/SOAP pagination proofs must survive both project-status gates."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.aras_crawler import ArasCrawlerClient, ArasCrawlerError
from services.project_status_connectors import _require_complete_result
from services.tdc_crawler import TDCCrawlerClient, TDCCrawlerError
from web.app import _TDCRequestError, _require_complete_mapping_result


class Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, payload):
        self.payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self.headers = {"Content-Type": "text/xml" if isinstance(payload, str) else "application/json"}

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, payloads):
        self.responses = [Response(payload) for payload in payloads]
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    post = get


def rejected_by_both(result):
    assert result.complete is False
    with pytest.raises(ValueError, match="incomplete"):
        _require_complete_result(result)
    with pytest.raises(_TDCRequestError):
        _require_complete_mapping_result(result, _TDCRequestError)


def tdc_page(page=1, size=2, rows=None, **metadata):
    return {"code": 200, "data": {
        "current": page, "size": size,
        "records": [{"id": "A"}, {"id": "B"}] if rows is None else rows,
        **metadata,
    }}


@pytest.mark.parametrize("second_page", [False, True])
def test_tdc_rejects_changed_effective_page_size(second_page):
    payloads = [tdc_page(size=2)]
    if second_page:
        payloads.insert(0, tdc_page(size=3, rows=[{"id": x} for x in "XYZ"]))
        payloads[-1]["data"]["current"] = 2
    session = Session(payloads)
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=3, max_pages=5, max_records=20
    )
    rejected_by_both(result)
    assert result.stop_reason == "inconsistent_page_size"
    assert [row["id"] for row in result.rows] == (list("XYZ") if second_page else [])
    assert len(session.calls) == (2 if second_page else 1)


@pytest.mark.parametrize("field", ["current", "size", "total", "pages"])
@pytest.mark.parametrize("invalid", [True, False, 1.5, "1.5", "invalid", -1, "", [], {}])
def test_tdc_rejects_explicit_invalid_pagination(field, invalid):
    payload = tdc_page(total=2, pages=1)
    payload["data"][field] = invalid
    session = Session([payload])
    with pytest.raises(TDCCrawlerError, match="pagination"):
        TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(page_size=2)


@pytest.mark.parametrize("field", ["current", "size"])
@pytest.mark.parametrize("invalid", [0, None])
def test_tdc_rejects_zero_or_null_required_page_metadata(field, invalid):
    payload = tdc_page(total=2, pages=1)
    payload["data"][field] = invalid
    with pytest.raises(TDCCrawlerError, match="pagination"):
        TDCCrawlerClient("https://tdc.example", session=Session([payload])).crawl_sor_all(page_size=2)


def test_tdc_valid_string_metadata_and_missing_metadata_remain_compatible():
    payload = tdc_page(page="1", size="2", rows=[{"id": "A"}], total="1", pages="1")
    for data in [payload, {"code": 200, "data": {"records": [{"id": "A"}]}}]:
        result = TDCCrawlerClient("https://tdc.example", session=Session([data])).crawl_sor_all(page_size=2)
        _require_complete_result(result)
        assert _require_complete_mapping_result(result, _TDCRequestError) == [{"id": "A"}]


def test_tdc_zero_total_and_pages_is_a_valid_empty_result():
    result = TDCCrawlerClient("https://tdc.example", session=Session([
        tdc_page(rows=[], total=0, pages=0)
    ])).crawl_sor_all(page_size=2)
    assert result.complete is True
    assert result.rows == []


def ewo_page(page, ids, *, no_ids=False, business_no=None):
    items = []
    for item_id in ids:
        id_attr = "" if no_ids else f' id="{item_id}"'
        items.append(f'<Item type="EWO_O"{id_attr} page="{page}"><_no>{business_no or item_id}</_no></Item>')
    return f'<Result page="{page}">' + "".join(items) + "</Result>"


@pytest.mark.parametrize("tail", [
    ewo_page(1, ["A"]),
    ewo_page(1, []),
    ewo_page(2, ["A"]),
    ewo_page(2, ["B", "A"]),
])
def test_ewo_rejects_wrong_or_overlapping_page_before_merging(tail):
    session = Session([ewo_page(1, ["A", "B"]), tail, ewo_page(3, [])])
    result = ArasCrawlerClient("https://aras.example", session=session).crawl_ewo_report_all(
        page_size=2, max_pages=5, max_records=20
    )
    rejected_by_both(result)
    assert result.item_ids == ["A", "B"]
    assert len(session.calls) == 2


def test_ewo_rejects_duplicate_id_with_changed_content():
    session = Session([ewo_page(1, ["A", "B"]), ewo_page(2, ["A"], business_no="CHANGED")])
    result = ArasCrawlerClient("https://aras.example", session=session).crawl_ewo_report_all(page_size=2)
    rejected_by_both(result)
    assert result.stop_reason == "duplicate_records"


def test_ewo_rejects_duplicate_ids_within_one_page():
    result = ArasCrawlerClient("https://aras.example", session=Session([
        ewo_page(1, ["A", "A"])
    ])).crawl_ewo_report_all(page_size=3)
    rejected_by_both(result)
    assert result.rows == []


def test_ewo_rejects_repeated_page_without_item_ids():
    session = Session([ewo_page(1, ["A", "B"], no_ids=True),
                       ewo_page(2, ["B", "A"], no_ids=True), ewo_page(3, [])])
    result = ArasCrawlerClient("https://aras.example", session=session).crawl_ewo_report_all(page_size=2)
    rejected_by_both(result)
    assert len(session.calls) == 2


@pytest.mark.parametrize("first_missing,second_missing", [(True, True), (True, False), (False, True)])
def test_ewo_rejects_partial_overlap_when_item_identity_is_unavailable(first_missing, second_missing):
    session = Session([ewo_page(1, ["A", "B"], no_ids=first_missing),
                       ewo_page(2, ["A"], no_ids=second_missing)])
    result = ArasCrawlerClient("https://aras.example", session=session).crawl_ewo_report_all(page_size=2)
    rejected_by_both(result)
    assert len(result.rows) == 2


def test_ewo_allows_nonoverlapping_legacy_rows_without_item_ids_or_pages():
    session = Session([
        '<Result><Item type="EWO_O"><_no>A</_no></Item><Item type="EWO_O"><_no>B</_no></Item></Result>',
        '<Result><Item type="EWO_O"><_no>C</_no></Item></Result>',
    ])
    result = ArasCrawlerClient("https://aras.example", session=session).crawl_ewo_report_all(page_size=2)
    _require_complete_result(result)
    assert len(result.rows) == 3


@pytest.mark.parametrize("page", ["0", "-1", "invalid", "1.5", ""])
def test_ewo_rejects_invalid_explicit_response_page(page):
    with pytest.raises(ArasCrawlerError, match="page"):
        ArasCrawlerClient("https://aras.example", session=Session([
            ewo_page(page, ["A"])
        ])).crawl_ewo_report_all(page_size=2)


def test_ewo_rejects_conflicting_page_attributes():
    payload = ewo_page(1, ["A", "B"]).replace('id="B" page="1"', 'id="B" page="2"')
    with pytest.raises(ArasCrawlerError, match="page"):
        ArasCrawlerClient("https://aras.example", session=Session([payload])).crawl_ewo_report_all(page_size=2)


def test_ewo_allows_same_business_number_with_distinct_item_ids():
    session = Session([ewo_page(1, ["A", "B"], business_no="SAME"),
                       ewo_page(2, ["C"], business_no="SAME")])
    result = ArasCrawlerClient("https://aras.example", session=session).crawl_ewo_report_all(page_size=2)
    _require_complete_result(result)
    assert len(_require_complete_mapping_result(result, _TDCRequestError)) == 3
    assert result.item_ids == ["A", "B", "C"]


# ── 不完整失败必须自带完整性事实（否则线上无法定位）──────────────────────────


def test_incomplete_discovery_error_carries_pagination_diagnostic():
    result = SimpleNamespace(
        rows=[{"id": "A"}],
        complete=False,
        stop_reason="duplicate_records",
        unique_count=48,
        duplicate_count=2,
        total=50,
        pages=2,
        fetched_pages=2,
    )
    with pytest.raises(_TDCRequestError) as excinfo:
        _require_complete_mapping_result(result, _TDCRequestError)
    diagnostic = excinfo.value.diagnostic
    assert diagnostic == {
        "stopReason": "duplicate_records",
        "rowCount": 1,
        "uniqueCount": 48,
        "duplicateCount": 2,
        "declaredTotal": 50,
        "declaredPages": 2,
        "fetchedPages": 2,
    }


def test_incomplete_diagnostic_tolerates_results_without_pagination_metadata():
    """Aras 的 EWOReportPage 没有 unique/duplicate/total/pages，不得因此抛错。"""
    result = SimpleNamespace(
        rows=[{"_no": "EWO-1"}],
        complete=False,
        stop_reason="max_pages",
        fetched_pages=7,
    )
    with pytest.raises(_TDCRequestError) as excinfo:
        _require_complete_mapping_result(result, _TDCRequestError)
    diagnostic = excinfo.value.diagnostic
    assert diagnostic["stopReason"] == "max_pages"
    assert diagnostic["uniqueCount"] is None
    assert diagnostic["declaredTotal"] is None
    assert diagnostic["fetchedPages"] == 7


def test_json_error_exposes_diagnostic_payload():
    """错误出口必须真正把 diagnostic 写进响应体（前端据此展示事实）。"""
    from flask import Flask

    from web.app import _json_error

    app = Flask(__name__)
    with app.app_context():
        response, status = _json_error(
            422,
            "IncompleteDiscovery",
            "mapping discovery query was incomplete; narrow the filters or retry",
            None,
            diagnostic={"stopReason": "duplicate_records"},
        )
        payload = response.get_json()
    assert status == 422
    assert payload["ok"] is False
    assert payload["error"]["diagnostic"] == {"stopReason": "duplicate_records"}


def test_paa_crawler_pagination_integrity_survives_gates():
    """PAAReportPage 完整爬取结果必须同时通过 _require_complete_result 与 _require_complete_mapping_result。"""
    from services.aras_crawler import PAAReportPage
    from services.project_status_connectors import _require_complete_result
    from web.app import _require_complete_mapping_result, _ArasRequestError

    # 完整结束结果：短页或空页判定为 complete=True
    paa_page = PAAReportPage(
        rows=[{"_no": "PAA-2026-001", "_pe_tdc": "PE-1"}],
        page=1,
        item_ids=["item-paa-1"],
        raw_xml="<xml/>",
        fetched_pages=1,
        stop_reason="short_page",
        complete=True,
    )

    # 1. 业务同步门禁
    _require_complete_result(paa_page)

    # 2. 映射发现门禁
    rows = _require_complete_mapping_result(paa_page, _ArasRequestError)
    assert len(rows) == 1
    assert rows[0]["_no"] == "PAA-2026-001"

    # 3. 不完整结果（如 max_pages）被两个门禁安全拦截
    incomplete_page = PAAReportPage(
        rows=[{"_no": "PAA-2026-001"}],
        page=1,
        item_ids=["item-paa-1"],
        raw_xml="<xml/>",
        fetched_pages=10,
        stop_reason="max_pages",
        complete=False,
    )
    with pytest.raises(ValueError, match="incomplete"):
        _require_complete_result(incomplete_page)
    with pytest.raises(_ArasRequestError):
        _require_complete_mapping_result(incomplete_page, _ArasRequestError)
