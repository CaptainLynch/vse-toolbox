# -*- coding: utf-8 -*-
"""签署日报页面的真浏览器行为（Playwright + Chromium）：生成预览、Canvas 出图、长周期复核阻塞导出、
下载 .eml、复制正文、设置页。上游不会被调用：数据是合成的表单快照。没有 Playwright 或 Chromium 时跳过。
"""

from __future__ import annotations

import email
import os
import shutil
import threading
from email import policy
from pathlib import Path
from typing import Any, Iterator

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

import web.app as web_app  # noqa: E402
from core.db_manager import DatabaseManager  # noqa: E402
from services.deliverable_form_analysis import build_form_snapshot, form_definition  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADERS = form_definition("tdc_data_model")["headerRows"][0]
PAGE_TIMEOUT = 10000


def _row(serial: str, **values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "流水单号": serial, "项目/车型": "F610M", "部门": "车身科", "申请人": "林锦辉",
        "申请日期": "2026-09-10 10:00:00", "零件号": f"{serial}-P1", "零件名称": "前门铰链",
        "应签人数": 2, "已签人数": 1, "未签人数": 1, "签署率": "50.00%", "状态": "进行中",
    }
    base.update(values)
    return base


ROWS = [
    _row("S1", 零件名称="前门内板", 冲压="冲压丁(未签)", 车身="张帅", 待审批人员="冲压丁"),
    _row("S2", 零件名称="前门内板加强板", 车身="张帅", **{"首席/总监": "总监辛(未签)"}, 待审批人员="总监辛"),
    _row("S3", 内外饰="梁海峰(未签)", 待审批人员="梁海峰", 申请日期="2026-09-28"),
]


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    tmp = tmp_path_factory.mktemp("sign-daily-browser")
    db_path = tmp / "browser.db"
    original = web_app.DatabaseManager
    web_app.DatabaseManager = lambda: original(db_path)  # type: ignore[assignment]
    os.environ.pop("VSE_TOOLBOX_PLUGIN_ONLY", None)
    try:
        app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["sign-daily"])
        app.config.update(TESTING=False)
        db = DatabaseManager(db_path)
        positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in ROWS]
        db.publish_deliverable_form_snapshot(build_form_snapshot(
            "tdc_data_model", positional, snapshot_at="2026-10-03T08:00:00Z", source_run_id=1, source="test"))
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield {"base": f"http://127.0.0.1:{server.server_port}"}
        finally:
            server.shutdown()
            thread.join(timeout=5)
    finally:
        web_app.DatabaseManager = original  # type: ignore[assignment]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with playwright_sync.sync_playwright() as pw:
        chromium = None
        for candidate in (None, os.environ.get("VSE_TEST_CHROMIUM"), "/opt/pw-browsers/chromium", shutil.which("chromium")):
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


def _page(browser: Any, base: str, width: int = 1400):  # type: ignore[no-untyped-def]
    context = browser.new_context(viewport={"width": width, "height": 900}, accept_downloads=True)
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: errors.append(f"console.error: {msg.text}") if msg.type == "error" else None)
    page.set_default_timeout(PAGE_TIMEOUT)
    page.goto(f"{base}/#p/sign-daily/report")
    page.wait_for_selector(".sd-form")
    return context, page, errors


def test_generate_review_export_and_settings(browser: Any, live: dict[str, Any]) -> None:
    context, page, errors = _page(browser, live["base"])
    try:
        page.locator(".sd-chip", has_text="F610M").click()
        page.get_by_role("button", name="用现有数据生成").click()
        page.wait_for_selector(".sd-preview img[src^='data:image/png']")
        # 三张图都有数据：冲压丁（图1 冲压）、梁海峰（在册，图2 内饰科）、总监辛（图3 首席/总监）
        assert page.locator(".sd-preview img").count() == 3
        assert all(src.startswith("data:image/png") for src in page.eval_on_selector_all(
            ".sd-preview img", "els => els.map(e => e.getAttribute('src'))"))
        assert "长周期初筛待确认" in page.inner_text(".sd-notice.is-blocking")
        assert page.get_by_role("button", name="复制正文").is_disabled()
        assert page.get_by_role("button", name="下载 .eml 草稿").is_disabled()
        page.get_by_role("button", name="确认并记住").click()
        page.wait_for_function("!document.querySelector('.sd-review')")
        page.wait_for_selector(".sd-preview img[src^='data:image/png']")
        assert page.get_by_role("button", name="复制正文").is_enabled()

        with page.expect_download() as info:
            page.get_by_role("button", name="下载 .eml 草稿").click()
        message = email.message_from_bytes(Path(info.value.path()).read_bytes(), policy=policy.default)
        assert message.get_content_type() == "multipart/related" and message["X-Unsent"] == "1"
        assert sum(1 for part in message.walk() if part.get_content_type() == "image/png") == 3

        page.get_by_role("button", name="复制正文").click()
        page.wait_for_selector("[role=status]:has-text('正文已复制')")

        page.locator(".sd-panel > summary", has_text="设置").click()
        page.fill(".sd-settings-tab input[placeholder='搜索姓名或科室']", "林锦辉")
        row = page.locator(".sd-table tr", has=page.locator("td", has_text="林锦辉"))
        row.locator("select").select_option("车体科")  # 单条修改只写本地层（M2）
        page.wait_for_selector(".sd-table tr:has-text('林锦辉') .sd-tag:has-text('已修改')")
        page.get_by_role("tab", name="长周期规则").click()
        page.wait_for_selector(".sd-table td:has-text('LC01')")
        page.get_by_role("tab", name="长周期结论").click()
        page.locator(".sd-settings-tab select").select_option("F610M")
        page.wait_for_selector(".sd-table td:has-text('前门内板')")
        assert not errors, errors
    finally:
        context.close()


def test_narrow_layout_has_no_horizontal_scroll(browser: Any, live: dict[str, Any]) -> None:
    context, page, errors = _page(browser, live["base"], width=420)
    try:
        page.locator(".sd-chip", has_text="F610M").click()
        page.get_by_role("button", name="用现有数据生成").click()
        page.wait_for_selector(".sd-preview")
        overflow = page.evaluate("document.scrollingElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, overflow
        assert not errors, errors
    finally:
        context.close()
