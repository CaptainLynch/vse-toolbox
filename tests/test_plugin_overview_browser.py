# -*- coding: utf-8 -*-
"""Real-browser behaviour of the project-overview plugin (restored parity items).

These replace the retired `web/static/app.js` source-text assertions with
behaviour checks against the plugin pages: the live Flask app serves the
pages, a temporary database holds synthetic form snapshots, and Playwright
drives Chromium. Upstream calls are never made: the wizard's discovery /
policy endpoints are intercepted with synthetic responses.

Skipped when Playwright or a Chromium binary is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

import web.app as web_app  # noqa: E402
from core.db_manager import DatabaseManager  # noqa: E402
from services.deliverable_form_analysis import build_form_snapshot, form_definition  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ARRIVE = "#p/project-overview/deliverable?id="
PAGE_TIMEOUT = 8000


# ---------------------------------------------------------------------------
# synthetic snapshots


def _labelled_values(form_key: str, header_row: int, labelled: dict[str, object]) -> list[object | None]:
    definition = form_definition(form_key)
    headers = definition["headerRows"][header_row]
    index_of = {str(column["label"]): int(column["index"]) for column in definition["columns"]}
    values: list[object | None] = [None] * len(headers)
    for label, value in labelled.items():
        values[index_of[label] if label in index_of else headers.index(label)] = value
    return values


def _seed_snapshots(db: DatabaseManager) -> None:
    # PAA: one row whose stage is outside the official vocabulary (OPEN).
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "aras_paa",
            [
                {"_no": "PAA-1", "_department": "车身开发部", "_pe_tdc_smt": "车身科", "_vehicles": "F610S",
                 "state": "PROC", "_submit_date": "2026-09-20"},
                {"_no": "PAA-2", "_department": "车身开发部", "_pe_tdc_smt": "车身科", "_vehicles": "F610S",
                 "state": "OPEN", "_submit_date": "2026-09-21"},
            ],
            snapshot_at="2026-09-30T08:00:00Z",
            source_run_id=1,
            source="browser test",
            artifacts=({"display_name": "paa.json", "relative_path": "aras/paa/paa.json", "artifact_type": "normalized_json"},),
        )
    )
    # NCR detail: four cost metrics, one negative, one empty-vs-zero pair.
    def ncr_row(no: str, section: str, **costs: object) -> dict[str, object]:
        labelled: dict[str, object] = {"NCR编号": no, "状态": "审批中", "区域": section, "项目": "F610S",
                                       "零件名称": "组件A", "零件号": f"27{no[-3:]}"}
        labelled.update(costs)
        return {"values": _labelled_values("aras_ncr_detail", 1, labelled), "sheetName": "整车"}

    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "aras_ncr_detail",
            [
                ncr_row("NCR-001", "车身科", **{"测算工程工装费用(万元)": 10.5, "批准工程工装费用（万元）": 0,
                                                "测算单件成本变化（元）": -50}),
                ncr_row("NCR-002", "车身科", **{"测算工程工装费用(万元)": 1.5}),
                ncr_row("NCR-003", "内饰科"),
            ],
            snapshot_at="2026-09-30T08:00:00Z",
            source_run_id=2,
            source="browser test",
            artifacts=({"display_name": "ncr.json", "relative_path": "aras/ncr/ncr.json", "artifact_type": "normalized_json"},),
        )
    )
    # Data model: official header rows, long flow name, numeric status codes.
    headers = form_definition("tdc_data_model")["headerRows"][0]

    def dm_row(no: str, status: str, section: str, flow: str) -> dict[str, object]:
        values = _labelled_values("tdc_data_model", 0, {
            "实例号": no, "流程名": flow, "部门": section, "申请日期": "2026-09-25 10:00:00",
            "项目/车型": "F999X", "零件名称": "组件A", "状态": status,
            "最新审批记录": "审批人甲：同意；审批人乙：同意；审批人丙：同意；" * 4,
        })
        return {str(h): v for h, v in zip(headers, values)}

    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_data_model",
            [
                dm_row("90000301", "4", "车身科", "T2发布-" + "很长的流程名称" * 12),
                dm_row("90000302", "2", "内饰科", "T2发布-组件B"),
            ],
            snapshot_at="2026-09-30T08:00:00Z",
            source_run_id=3,
            source="browser test",
            artifacts=({"display_name": "dm.json", "relative_path": "tdc/dm/dm.json", "artifact_type": "normalized_json"},),
        )
    )


_SOR_KEYS = (
    "carTypeProject", "currentAssigneeNameList", "id", "isCurrentUserInvolved", "processInstanceId",
    "sorProcessStatus", "source", "startTime", "title", "startUser", "version", "processInstanceStatus",
    "processNo", "pushResult", "sorNo", "sorPartList", "sorPartNo",
)


def _seed_sor(db: DatabaseManager) -> None:
    """SOR rows with the production key set: several positional columns have no source key at all."""
    rows = []
    for number, status in (("S-1", "审批中"), ("S-2", "已完成")):
        row: dict[str, object] = {key: "" for key in _SOR_KEYS}
        row.update({"processNo": number, "processInstanceStatus": status, "startUser": "张三",
                    "carTypeProject": "F610S", "startTime": "2026-09-20 10:00:00"})
        rows.append(row)
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_sor", rows, snapshot_at="2026-09-30T08:00:00Z", source_run_id=4, source="browser test",
            artifacts=({"display_name": "sor.json", "relative_path": "tdc/sor/sor.json", "artifact_type": "normalized_json"},),
        )
    )


# ---------------------------------------------------------------------------
# fixtures


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    tmp = tmp_path_factory.mktemp("overview-browser")
    db_path = tmp / "browser.db"
    original = web_app.DatabaseManager
    web_app.DatabaseManager = lambda: original(db_path)  # type: ignore[assignment]
    os.environ.pop("VSE_TOOLBOX_PLUGIN_ONLY", None)
    try:
        app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"])
        app.config.update(TESTING=False)
        db = DatabaseManager(db_path)
        _seed_snapshots(db)
        _seed_sor(db)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield {"base": f"http://127.0.0.1:{server.server_port}", "db": db}
        finally:
            server.shutdown()
            thread.join(timeout=5)
    finally:
        web_app.DatabaseManager = original  # type: ignore[assignment]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with playwright_sync.sync_playwright() as pw:
        chromium = None
        candidates = [None, os.environ.get("VSE_TEST_CHROMIUM"), "/opt/pw-browsers/chromium", shutil.which("chromium")]
        for candidate in candidates:
            try:
                chromium = pw.chromium.launch(executable_path=candidate) if candidate else pw.chromium.launch()
                break
            except Exception:  # noqa: BLE001
                continue
        if chromium is None:
            pytest.skip("no Chromium binary available for Playwright")
        try:
            yield chromium
        finally:
            chromium.close()


class Session:
    """One browser page with pageerror / console-error collection."""

    def __init__(self, browser: Any, base: str, width: int = 1400, height: int = 900) -> None:
        self.context = browser.new_context(viewport={"width": width, "height": height})
        self.page = self.context.new_page()
        self.base = base
        self.errors: list[str] = []
        self.page.on("pageerror", lambda exc: self.errors.append(f"pageerror: {exc}"))
        self.page.on(
            "console",
            lambda msg: self.errors.append(f"console.error: {msg.text}") if msg.type == "error" else None,
        )
        self.page.set_default_timeout(PAGE_TIMEOUT)

    def open_deliverable(self, deliverable_id: str) -> None:
        self.page.goto(f"{self.base}/{ARRIVE}{deliverable_id}")
        self.page.wait_for_selector(".overview-deliverable-detail-view")

    def close(self) -> None:
        self.context.close()


@pytest.fixture()
def session(browser: Any, live: dict[str, Any]) -> Iterator[Session]:
    sess = Session(browser, live["base"])
    try:
        yield sess
        relevant = [e for e in sess.errors if "Failed to load resource" not in e]
        assert not relevant, relevant
    finally:
        sess.close()


@pytest.fixture()
def narrow(browser: Any, live: dict[str, Any]) -> Iterator[Session]:
    sess = Session(browser, live["base"], width=420, height=900)
    try:
        yield sess
        relevant = [e for e in sess.errors if "Failed to load resource" not in e]
        assert not relevant, relevant
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# A8/A9/A13/A14: forms render the restored boards and honest table cells


def test_ncr_detail_cost_table_shows_four_metrics_with_valued_counts(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D8")
    page.wait_for_selector(".form-section-cost-table")
    rows = page.eval_on_selector_all(
        ".form-section-cost-table tbody tr",
        "rows => rows.map(r => [...r.children].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))",
    )
    by_name = {row[0]: row for row in rows}
    body = by_name["车身科"]
    assert body[1] == "2"
    assert "12" in body[2] and "2 项有值" in body[2]           # 测算工装费用 10.5 + 1.5
    assert "0" in body[3] and "1 项有值" in body[3]            # 批准 = 真实 0（有值件数 1）
    assert "-50" in body[4] and "1 项有值" in body[4]          # 负值表示
    assert page.locator(".form-section-cost-value.is-negative").count() >= 1
    interior = by_name["内饰科"]
    assert interior[2] == "—" and interior[3] == "—"          # 空值不是 0
    assert page.locator(".form-section-cost-none").count() >= 2


def test_ncr_cost_table_row_click_appends_section_filter(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D8")
    page.wait_for_selector(".form-section-cost-table")
    page.locator(".form-section-cost-table tbody tr", has_text="车身科").first.click()
    page.wait_for_selector(".form-filter-chip:has-text('车身科')")
    page.wait_for_function("document.querySelector('.form-row-count').innerText.includes('2 条')")
    # keyboard activation of a row works the same way
    page.locator(".form-filter-chip-remove").first.click()
    page.wait_for_function("document.querySelector('.form-row-count').innerText.includes('3 条')")
    page.locator(".form-section-cost-table tbody tr", has_text="内饰科").first.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('.form-row-count').innerText.includes('1 条')")


def test_data_model_has_section_counts_tab_and_completion_caliber(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D5")
    page.wait_for_selector(".form-chart-tab")
    tabs = [t.strip() for t in page.eval_on_selector_all(".form-chart-tabs > .form-chart-tab-list > .form-chart-tab", "e => e.map(x => x.innerText)")]
    assert tabs == ["项目状态", "部门状态", "按科室", "数量趋势"]
    # code 4 -> completed, code 2 -> in flight: summary and rows agree
    cards = dict(zip(
        page.eval_on_selector_all(".form-summary-label", "e => e.map(x => x.innerText)"),
        page.eval_on_selector_all(".form-summary-value", "e => e.map(x => x.innerText)"),
    ))
    assert cards["总数"] == "2" and cards["已完成"] == "1" and cards["未完成"] == "1"
    page.locator(".form-chart-tabs > .form-chart-tab-list > .form-chart-tab", has_text="按科室").click()
    page.wait_for_selector(".form-chart-title:has-text('按科室统计')")
    assert "数模流程无阶段维度" in page.inner_text(".form-chart-panel-content")
    assert "NCR明细" not in page.inner_text(".form-chart-panel-content")
    labels = page.eval_on_selector_all(".form-status-bar-label", "e => e.map(x => x.innerText)")
    assert "车身科" in labels and "内饰科" in labels


def test_data_model_rows_show_status_column_and_truncate_long_text(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D5")
    page.wait_for_selector(".form-row-table")
    headers = page.eval_on_selector_all(".form-row-table thead th", "e => e.map(x => x.innerText)")
    assert "状态" in headers and "最新审批记录" in headers
    status_col = headers.index("状态")
    statuses = page.eval_on_selector_all(
        ".form-row-table tbody tr:not(.form-row-detail-row)",
        f"rows => rows.map(r => r.children[{status_col}].innerText)",
    )
    assert set(statuses) == {"已完成", "审批中"} and len(statuses) == 2
    # long flow name and approval log are truncated to one line; the full value is in title
    for needle in ("很长的流程名称", "审批人甲：同意"):
        cell = page.locator(f".form-row-table td.form-cell-truncate[title*='{needle}']").first
        title = cell.get_attribute("title")
        assert title and len(title) > 40
        assert cell.inner_text() == title            # DOM text is complete; CSS ellipsis does the clipping
        assert page.evaluate("el => el.getBoundingClientRect().height", cell.element_handle()) < 48
        assert page.evaluate("el => el.scrollWidth > el.clientWidth", cell.element_handle()) is True
    # the full-field detail still carries the unclipped value (details are collapsed: read textContent)
    full_values = page.eval_on_selector_all(".form-row-field-grid dd", "e => e.map(x => x.textContent)")
    assert any("很长的流程名称" * 12 in value for value in full_values)


def test_paa_board_drops_other_bucket_and_discloses_unrecognized(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D6")
    page.wait_for_selector(".form-chart-unrecognized")
    assert page.inner_text(".form-chart-unrecognized") == "未识别 1 条"
    page.locator(".dept-board-tab", has_text="按状态").click()
    page.wait_for_selector(".form-status-bar-label")
    labels = page.eval_on_selector_all(".form-status-bar-label", "e => e.map(x => x.innerText)")
    assert "其他状态" not in labels
    assert "PROC" in labels
    assert page.inner_text(".form-chart-unrecognized") == "未识别 1 条"


def test_paa_display_name_is_paa_liucheng(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D6")
    page.wait_for_selector(".form-analysis-title")
    assert "PAA流程" in page.inner_text(".form-analysis-title")
    assert "PAA 报告" not in page.inner_text("body")


def test_narrow_viewport_has_no_horizontal_page_scroll(narrow: Session) -> None:
    page = narrow.page
    for deliverable in ("VPI-T2-D8", "VPI-T2-D5", "VPI-T2-D6"):
        narrow.open_deliverable(deliverable)
        page.wait_for_selector(".form-row-table")
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") is True, deliverable


def test_sor_columns_with_no_source_key_are_marked_absent_not_blank(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D2")
    page.wait_for_selector(".form-row-table")
    absent_headers = page.eval_on_selector_all(".form-row-table thead th.form-cell-absent", "e => e.map(x => x.innerText)")
    assert absent_headers, "expected at least one source-absent column header"
    absent_cells = page.eval_on_selector_all(".form-row-table tbody td.form-cell-absent", "e => e.map(x => x.innerText)")
    assert absent_cells and set(absent_cells) == {"源端不提供"}
    # a column whose key exists but whose value is empty stays a plain empty cell ('-'), not "源端不提供"
    headers = page.eval_on_selector_all(".form-row-table thead th", "e => e.map(x => x.innerText)")
    plain_empty = page.eval_on_selector_all(
        ".form-row-table tbody tr:not(.form-row-detail-row) td:not(.form-cell-absent)",
        "e => e.map(x => x.innerText)",
    )
    assert "-" in plain_empty
    assert len(absent_headers) < len(headers) - 2


# ---------------------------------------------------------------------------
# A16: view/rows request recovery in the Preact panel


def _set_limit(page: Any, millis: int) -> None:
    page.evaluate(
        """async (ms) => {
          const mod = await import('/plugins/project-overview/static/deliverable/form-state.js');
          mod.FORM_VIEW_LIMITS.timeoutMs = ms;
        }""",
        millis,
    )


def test_view_timeout_unlocks_interaction_and_offers_retry(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D5")
    page.wait_for_selector(".form-chart-tabs")
    _set_limit(page, 600)
    hold = {"on": True}

    def handler(route: Any) -> None:
        if hold["on"]:
            return  # never answered: the request hangs until the client deadline aborts it
        route.continue_()

    page.route("**/api/deliverable-forms/tdc_data_model/view*", handler)
    page.route("**/api/deliverable-forms/tdc_data_model/rows*", handler)
    page.locator(".form-chart-tabs > .form-chart-tab-list > .form-chart-tab", has_text="数量趋势").click()
    # while the new tab's request is in flight the stale controls are locked
    page.wait_for_selector(".form-chart-tabs[data-form-interaction-locked='true']")
    # a blocked interaction is observable
    page.locator(".form-filter-keyword").first.click(force=True)
    assert int(page.get_attribute(".form-chart-tabs", "data-form-interaction-blocked-count") or "0") >= 1
    # ... and the lock is bounded: after the deadline the panel unlocks and shows a retryable error
    page.wait_for_selector(".form-view-load-error")
    assert "未完成，已取消；可稍后重试" in page.inner_text(".form-view-load-error")
    assert page.get_attribute(".form-chart-tabs", "data-form-interaction-locked") == "false"
    keyword = page.locator(".form-filter-keyword").first
    keyword.fill("abc")
    assert keyword.input_value() == "abc"
    # retry once the upstream answers again
    hold["on"] = False
    page.unroute("**/api/deliverable-forms/tdc_data_model/view*")
    page.unroute("**/api/deliverable-forms/tdc_data_model/rows*")
    page.get_by_role("button", name="刷新表单数据").first.click()
    page.wait_for_selector(".form-trend-chart")
    assert page.locator(".form-view-load-error").count() == 0


def test_stale_response_never_overwrites_the_latest_view(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D5")
    page.wait_for_selector(".form-row-table")
    pending: list[Any] = []

    def slow(route: Any) -> None:
        pending.append(route)

    # first request (keyword "zzz": would show 0 rows) is held; the second (no keyword) is answered at once
    page.route("**/api/deliverable-forms/tdc_data_model/rows?*keyword=zzz*", slow)
    page.route("**/api/deliverable-forms/tdc_data_model/view?*keyword=zzz*", slow)
    keyword = page.locator(".form-filter-keyword").first
    keyword.fill("zzz")
    page.get_by_role("button", name="应用筛选").first.click()
    page.wait_for_function("document.querySelector('.form-filter-draft-state').innerText.includes('正在')")
    assert len(pending) == 2  # view + rows of the first (soon stale) request are in flight
    # newer request: clear the filter (answered normally)
    page.get_by_role("button", name="清除筛选").first.click()
    page.wait_for_function("document.querySelector('.form-row-count') && document.querySelector('.form-row-count').innerText.includes('2 条')")
    # now release the stale responses: they must not repaint the table
    for route in pending:
        route.continue_()
    page.wait_for_timeout(500)
    assert "2 条" in page.inner_text(".form-row-count")
    assert page.locator(".form-row-table tbody tr:not(.form-row-detail-row)").count() == 2


# ---------------------------------------------------------------------------
# A16: multi-select pick / keyboard behaviour under live option updates, draft chips


def _multi(page: Any, label: str) -> Any:
    return page.locator(f".analysis-multi-select[aria-label='{label}']")


def test_pick_survives_option_refresh_between_mousedown_and_click(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D5")
    page.wait_for_selector(".form-row-table")
    box = _multi(page, "部门")
    box.locator("input").click()
    option = box.locator(".analysis-multi-select-option[data-value='车身科']")
    option.wait_for()
    target = option.bounding_box()
    assert target is not None
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + target["height"] / 2)
    page.mouse.down()
    # the data refresh settles while the pointer is still down (focus is not moved)
    page.evaluate("document.querySelector('.form-snapshot-actions button').click()")
    page.wait_for_function("document.querySelector('.form-filter-draft-state').innerText.includes('正在')")
    page.wait_for_function("!document.querySelector('.form-filter-draft-state').innerText.includes('正在')")
    page.mouse.up()
    page.wait_for_selector(".analysis-multi-select[aria-label='部门'] .analysis-filter-token")
    tokens = box.locator(".analysis-filter-token-label").all_inner_texts()
    assert tokens == ["车身科"]


def test_multi_select_keyboard_behaviour_and_draft_feedback(session: Session) -> None:
    page = session.page
    session.open_deliverable("VPI-T2-D5")
    page.wait_for_selector(".form-row-table")
    box = _multi(page, "部门")
    field = box.locator("input")
    field.click()
    field.type("内饰")
    assert box.locator(".analysis-multi-select-option").all_inner_texts() == ["内饰科"]
    field.press("Enter")                       # Enter commits the typed text
    assert box.locator(".analysis-filter-token-label").all_inner_texts() == ["内饰"]
    field.press("Backspace")                   # Backspace on empty input removes the last token
    assert box.locator(".analysis-filter-token").count() == 0
    field.press("Escape")
    assert box.locator(".analysis-multi-select-options").is_hidden()
    field.blur()                               # Escape closed the list; focusing again reopens it
    # pick by mouse -> draft feedback is visible before applying
    field.click()
    box.locator(".analysis-multi-select-option[data-value='内饰科']").click()
    page.wait_for_selector(".form-filter-chips-note")
    assert "待应用" in page.inner_text(".form-filter-chips-note")
    assert page.locator(".form-filter-chip.is-draft").count() == 1
    assert page.locator(".form-filter-actions .btn.is-draft-dirty").count() == 1
    # removing the draft chip only edits the draft (no request, control follows)
    page.locator(".form-filter-chip.is-draft .form-filter-chip-remove").click()
    assert box.locator(".analysis-filter-token").count() == 0
    assert page.locator(".form-filter-chips-note").count() == 0
    # apply the real filter
    field.click()
    box.locator(".analysis-multi-select-option[data-value='内饰科']").click()
    page.get_by_role("button", name="应用筛选").first.click()
    page.wait_for_function("document.querySelector('.form-row-count').innerText.includes('1 条')")
    assert page.locator(".form-filter-chip:not(.is-draft)").count() == 1
    assert page.locator(".form-filter-actions .btn.is-draft-dirty").count() == 0


# ---------------------------------------------------------------------------
# A11/A12: wizard discovery channel (deadline, cancel, 202 task, stability, scope fields)


def _json_response(route: Any, body: dict[str, Any], status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


def _matched(confirmed: int, fields: tuple[str, ...] = ("latestApproveLog", "status"), **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "state": "matched", "externalKey": None, "candidateCount": 3,
        "stability": {"confirmed": confirmed}, "fieldReport": {"fields": list(fields)},
    }
    data.update(extra)
    return data


class Wizard:
    """Intercepts the wizard's endpoints; records every request body."""

    def __init__(self, session: Session, deliverable: str) -> None:
        self.session = session
        self.page = session.page
        self.deliverable = deliverable
        self.discovery: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.cancels: list[dict[str, Any]] = []
        self.task_cancels: list[str] = []
        self.on_discovery: Any = None
        page = self.page
        page.route("**/api/settings", lambda r: _json_response(r, {"ok": True, "data": {"credentialVaultConfigured": True}})
                   if r.request.method == "GET" else r.fallback())
        page.route("**/mapping-discovery", self._discovery)
        page.route("**/mapping-discovery/cancel", self._cancel)
        page.route("**/update-policy", self._policy)
        page.route("**/sync-now", lambda r: _json_response(r, {"ok": True, "data": {"result": {"finalState": "success", "outcome": "completed"}}}))
        page.route("**/api/tasks/*/cancel", self._task_cancel)

    def _discovery(self, route: Any) -> None:
        if route.request.method != "POST":
            route.fallback()
            return
        body = json.loads(route.request.post_data or "{}")
        self.discovery.append(body)
        self.on_discovery(route, body, len(self.discovery))

    def _cancel(self, route: Any) -> None:
        self.cancels.append(json.loads(route.request.post_data or "{}"))
        _json_response(route, {"ok": True, "data": {}})

    def _task_cancel(self, route: Any) -> None:
        self.task_cancels.append(route.request.url)
        _json_response(route, {"ok": True, "data": {}})

    def _policy(self, route: Any) -> None:
        if route.request.method == "PATCH":
            self.patches.append(json.loads(route.request.post_data or "{}"))
            _json_response(route, {"ok": True, "data": {}})
        else:
            route.fallback()

    def limits(self, **values: int) -> None:
        self.page.evaluate(
            """async (v) => {
              const mod = await import('/plugins/project-overview/static/deliverable/discovery.js');
              Object.assign(mod.discoveryLimits, v);
            }""",
            values,
        )

    def open(self, model: str = "F999X") -> None:
        self.session.open_deliverable(self.deliverable)
        self.page.wait_for_selector(".policy-sync-summary")
        self.page.locator(".policy-sync-enable-btn, .policy-sync-reconfig-btn").first.click()
        self.page.locator(".policy-wizard-field", has_text="车型项目").locator("input").fill(model)

    def start(self) -> None:
        self.page.locator(".policy-wizard-start-btn").click()

    def status(self) -> str:
        return self.page.inner_text(".policy-sync-wizard-status")

    def wait_status(self, needle: str) -> str:
        try:
            self.page.wait_for_function(
                "(n) => (document.querySelector('.policy-sync-wizard-status')||{}).innerText?.includes(n)", arg=needle
            )
        except playwright_sync.TimeoutError as exc:
            raise AssertionError(f"status never contained {needle!r}; last status: {self.status()!r}") from exc
        return self.status()


def _task_routes(page: Any, *, active: bool = False, status: str = "succeeded", result: dict[str, Any] | None = None,
                 params_hash: str = "h1") -> None:
    page.route("**/api/tasks/task-1", lambda r: _json_response(r, {"ok": True, "data": {"is_active": active, "status": status}})
               if r.request.method == "GET" else r.fallback())
    page.route("**/api/tasks/task-1/result", lambda r: _json_response(
        r, {"ok": True, "data": {"result": result if result is not None else _matched(1), "paramsHash": params_hash}}))


def _accepted(route: Any) -> None:
    _json_response(route, {"ok": True, "data": {
        "taskId": "task-1", "status": "queued", "category": "crawl", "statusUrl": "/api/tasks/task-1",
        "resultUrl": "/api/tasks/task-1/result", "paramsHash": "h1"}}, status=202)


def test_wizard_runs_first_discovery_as_background_task_then_stability_check(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")

    def on_discovery(route: Any, body: dict[str, Any], count: int) -> None:
        if count == 1:
            _accepted(route)
        else:
            _json_response(route, {"ok": True, "data": _matched(2)})

    wiz.on_discovery = on_discovery
    _task_routes(session.page)
    wiz.open()
    session.page.evaluate("window.__kicks = 0; document.addEventListener('vse:task-center-kick', () => { window.__kicks += 1; })")
    wiz.start()
    assert "配置并启用成功" in wiz.wait_status("配置并启用成功")
    first, second = wiz.discovery
    assert first["wizardSessionId"].startswith("wiz-") and first["cancelToken"].startswith("disc-")
    assert "stabilityCheck" not in first and second["stabilityCheck"] is True
    assert second["wizardSessionId"] == first["wizardSessionId"]          # same wizard session -> server reuses the crawl
    assert first["filters"]["project_model"] == "F999X"
    assert session.page.evaluate("window.__kicks") >= 1                    # task centre was told about the background task
    assert len(wiz.patches) == 1
    patch = wiz.patches[0]
    assert patch["enabled"] is True and patch["mapping"] == {"note": ["latestApproveLog", "status"]}
    assert patch["matchRule"]["projectModel"] == "F999X"
    # the terminal text survives the card rebuild that follows the overview reload
    session.page.wait_for_timeout(600)
    assert "配置并启用成功" in wiz.status()
    assert session.page.evaluate("window.__vseWizardBusy") is False


def test_wizard_discards_background_result_with_foreign_params_hash(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    wiz.on_discovery = lambda route, body, count: _accepted(route)
    _task_routes(session.page, params_hash="OTHER")
    wiz.open()
    wiz.start()
    text = wiz.wait_status("结果与请求参数不一致")
    assert text.startswith("配置启用失败：") and "已丢弃" in text
    assert not wiz.patches


def test_wizard_client_deadline_cancels_server_side_and_is_retryable(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    wiz.on_discovery = lambda route, body, count: None            # never answered
    wiz.open()
    wiz.limits(tdcMs=500)
    wiz.start()
    text = wiz.wait_status("已取消")
    assert "映射取证超过" in text and "可稍后重试" in text
    assert not text.startswith("配置启用失败")                      # transient, not a configuration failure
    session.page.wait_for_function("document.querySelector('.policy-wizard-start-btn').disabled === false")
    assert wiz.cancels and wiz.cancels[0]["cancelToken"] == wiz.discovery[0]["cancelToken"]
    assert session.page.evaluate("window.__vseWizardBusy") is False
    assert not wiz.patches


def test_wizard_aras_deadline_is_independent_of_tdc_deadline(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D6")
    wiz.on_discovery = lambda route, body, count: None
    wiz.open()
    wiz.limits(tdcMs=60000, arasMs=500)                            # only the Aras channel is shortened
    wiz.start()
    assert "映射取证超过" in wiz.wait_status("已取消")


def test_wizard_background_task_poll_limit_is_bounded(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    wiz.on_discovery = lambda route, body, count: _accepted(route)
    _task_routes(session.page, active=True)
    wiz.open()
    wiz.limits(taskPollTimeoutMs=500, taskPollIntervalMs=100)
    wiz.start()
    text = wiz.wait_status("任务中心")
    assert "未完成" in text and not wiz.patches


def test_wizard_reports_specific_stability_mismatch(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")

    def on_discovery(route: Any, body: dict[str, Any], count: int) -> None:
        if count == 1:
            _json_response(route, {"ok": True, "data": _matched(1)})
        else:
            _json_response(route, {"ok": True, "data": _matched(
                1, mismatch={"reason": "total_mismatch", "expected": 100, "actual": 101})})

    wiz.on_discovery = on_discovery
    wiz.open()
    wiz.start()
    text = wiz.wait_status("稳定性核验未通过")
    assert "（100→101）" in text and "单号" not in text
    assert [c.get("stabilityCheck") for c in wiz.discovery] == [None, True]
    assert not wiz.patches


def test_wizard_gateway_failure_shows_server_wording_without_config_prefix(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    message = "TDC 网关暂时不可用（503），已重试 2 次，请稍后重试。"
    wiz.on_discovery = lambda route, body, count: _json_response(
        route, {"ok": False, "error": {"type": "UpstreamUnavailable", "message": message, "diagnostic": {"retryable": True}}}, status=503)
    wiz.open()
    wiz.start()
    text = wiz.wait_status("网关暂时不可用")
    assert message in text and "配置启用失败" not in text


def test_wizard_ncr_has_section_scope_instead_of_department(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D7")

    def on_discovery(route: Any, body: dict[str, Any], count: int) -> None:
        _json_response(route, {"ok": True, "data": _matched(2, fields=("状态", "更改主题"))})

    wiz.on_discovery = on_discovery
    wiz.open("F610S")
    assert session.page.locator(".policy-wizard-field", has_text="责任部门").count() == 0
    field = session.page.locator(".policy-wizard-field", has_text="科室（选填，可多选）")
    box = field.locator(".analysis-multi-select")
    box.locator("input").click()
    box.locator(".analysis-multi-select-option[data-value='车身科']").click()      # inside a <label>: must stay picked
    box.locator("input").click()
    box.locator(".analysis-multi-select-option[data-value='内饰科']").click()
    assert box.locator(".analysis-filter-token-label").all_inner_texts() == ["车身科", "内饰科"]
    wiz.start()
    wiz.wait_status("配置并启用成功")
    first = wiz.discovery[0]
    assert "department" not in first["filters"] and "section_code" not in first["filters"]
    assert wiz.patches[0]["matchRule"]["sectionScope"] == ["车身科", "内饰科"]
    assert "department" not in wiz.patches[0]["matchRule"] and "sectionCode" not in wiz.patches[0]["matchRule"]


def test_wizard_sor_status_filter_reaches_request_and_binding(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D2")

    def on_discovery(route: Any, body: dict[str, Any], count: int) -> None:
        _json_response(route, {"ok": True, "data": _matched(2, fields=("latestCompletedNode", "processInstanceStatus"))})

    wiz.on_discovery = on_discovery
    wiz.open("F610S")
    status_field = session.page.locator(".policy-wizard-field", has_text="状态（选填）")
    assert "剔除优先于本筛选" in (status_field.locator("input").get_attribute("title") or "")
    status_field.locator("input").fill("审批中")
    wiz.start()
    wiz.wait_status("配置并启用成功")
    assert wiz.discovery[0]["filters"]["approval_status"] == "审批中"
    assert wiz.patches[0]["matchRule"]["approvalStatus"] == "审批中"


def test_wizard_terminal_status_is_scoped_to_its_deliverable(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    held: list[Any] = []
    wiz.on_discovery = lambda route, body, count: held.append(route)
    wiz.open()
    wiz.start()
    session.page.wait_for_function("document.querySelector('.policy-wizard-start-btn').disabled === true")
    # the user leaves for another deliverable while the discovery is still running
    session.open_deliverable("VPI-T2-D6")
    session.page.wait_for_selector(".policy-sync-summary")
    for route in held:
        _json_response(route, {"ok": False, "error": {"type": "ServerError", "message": "上游拒绝"}}, status=400)
    session.page.wait_for_timeout(500)
    assert "上游拒绝" not in session.page.inner_text(".policy-sync-wizard-status")      # not leaked into D6's card
    session.open_deliverable("VPI-T2-D5")
    session.page.wait_for_selector(".policy-sync-wizard-status")
    assert "配置启用失败" in session.page.inner_text(".policy-sync-wizard-status")


def test_wizard_double_click_starts_one_discovery(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    held: list[Any] = []
    wiz.on_discovery = lambda route, body, count: held.append(route)
    wiz.open()
    button = session.page.locator(".policy-wizard-start-btn")
    button.click()
    session.page.wait_for_function("document.querySelector('.policy-wizard-start-btn').disabled === true")
    button.click(force=True)                                   # disabled: must not start a second run
    session.page.wait_for_timeout(300)
    assert len(wiz.discovery) == 1
    for route in held:
        _json_response(route, {"ok": False, "error": {"type": "ServerError", "message": "停止"}}, status=400)
    wiz.wait_status("配置启用失败")
    session.page.wait_for_function("document.querySelector('.policy-wizard-start-btn').disabled === false")


def test_wizard_reattaches_to_the_same_inflight_task_after_reload(session: Session) -> None:
    """The server answers an identical in-flight discovery with the same 202 task; the page just polls it again."""
    wiz = Wizard(session, "VPI-T2-D5")
    state = {"active": True}

    def on_discovery(route: Any, body: dict[str, Any], count: int) -> None:
        if count <= 2:
            _accepted(route)                                    # both starts get the same task (re-attached)
        else:
            _json_response(route, {"ok": True, "data": _matched(2)})

    wiz.on_discovery = on_discovery
    session.page.route("**/api/tasks/task-1", lambda r: _json_response(
        r, {"ok": True, "data": {"is_active": state["active"], "status": "running" if state["active"] else "succeeded"}}))
    session.page.route("**/api/tasks/task-1/result", lambda r: _json_response(
        r, {"ok": True, "data": {"result": _matched(1), "paramsHash": "h1"}}))
    wiz.open()
    wiz.limits(taskPollIntervalMs=100)
    wiz.start()
    session.page.wait_for_function("document.querySelector('.policy-wizard-start-btn').disabled === true")
    session.page.reload()                                       # first poll loop is abandoned with the page
    session.page.wait_for_selector(".policy-sync-summary")
    session.page.locator(".policy-sync-enable-btn").click()
    session.page.locator(".policy-wizard-field", has_text="车型项目").locator("input").fill("F999X")
    wiz.limits(taskPollIntervalMs=100)
    state["active"] = False                                     # the task finished while nobody was watching
    wiz.start()
    wiz.wait_status("配置并启用成功")
    # abandoned start + re-attached start + stability check; the saved binding is written once
    assert len(wiz.discovery) == 3 and wiz.discovery[2]["stabilityCheck"] is True
    assert len(wiz.patches) == 1


def test_wizard_cancelled_background_task_offers_restart(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    wiz.on_discovery = lambda route, body, count: _accepted(route)
    _task_routes(session.page, status="cancelled")
    wiz.open()
    wiz.start()
    text = wiz.wait_status("映射取证已取消")
    assert "重新点击" in text and not wiz.patches
    session.page.wait_for_function("document.querySelector('.policy-wizard-start-btn').disabled === false")


def test_wizard_failed_background_task_reports_its_reason(session: Session) -> None:
    wiz = Wizard(session, "VPI-T2-D5")
    wiz.on_discovery = lambda route, body, count: _accepted(route)
    session.page.route("**/api/tasks/task-1", lambda r: _json_response(
        r, {"ok": True, "data": {"is_active": False, "status": "failed", "error_message": "TDC 会话已过期"}}))
    wiz.open()
    wiz.start()
    text = wiz.wait_status("后台任务失败")
    assert "TDC 会话已过期" in text


def test_wizard_layout_on_narrow_viewport(narrow: Session) -> None:
    wiz = Wizard(narrow, "VPI-T2-D7")
    wiz.on_discovery = lambda route, body, count: None
    wiz.open("F610S")
    page = narrow.page
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") is True
    box = page.locator(".policy-wizard-field", has_text="科室（选填，可多选）").locator(".analysis-multi-select")
    box.locator("input").click()
    assert box.locator(".analysis-multi-select-option").first.is_visible()
