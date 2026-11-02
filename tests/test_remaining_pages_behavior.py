# -*- coding: utf-8 -*-
"""DSH-V2-32：项目与设置旧页面的体验覆盖（真实浏览器 / 真实 DOM）。

页面入口先经 ``plugin.json`` 的 ``pages`` 与 ``web/static/host/legacy-routes.js``
双向确认，三个模块与契约里的 owned_scope 完全一致：

==================================  ==============================================  ==============================
旧入口（hash）                       页面模块                                         本文件覆盖
==================================  ==============================================  ==============================
``#p/project-overview/status``      ``plugins/project_overview/static/status.js``    正常/空/加载/错误/未配置
``#p/project-overview/details``     ``plugins/project_overview/static/details.js``   正常/空/加载/错误/未配置
``#p/settings/general``             ``plugins/settings/static/general.js``           正常/空/加载/错误/未配置
==================================  ==============================================  ==============================

五种状态的口径（三个页面共用一套口径）：

- 正常：真实种子数据（``DatabaseManager`` 初始化的 VPI-T2 / F610S 快照）；
- 空数据：接口成功但载荷为空（``data: {}``），页面必须给出「暂无数据」而不是空白；
- 加载中：被测接口挂起，页面必须先渲染「加载中」占位，放行后回到正常内容；
- 错误：被测接口返回 500，页面必须给出「加载失败：…」/统一错误卡与可点的重试；
- 未配置：项目有阶段但主计划没有任何节点（概览）／交付物同步未配置（明细）／
  凭据保护库未配置（设置），页面必须给出既有的「主计划待设置」「待配置」「未配置」术语。

数据状态通过替换同一进程内真实 ``create_app`` 的视图函数驱动；页面侧仍是真实 ES
Module、真实 fetch、真实 DOM 与真实鼠标点击（``tests/browser/v2_fixtures.py``），
断言读取渲染后的 DOM、计算样式与浏览器 console，不是源码文本。

顶栏三档会话徽章（``web/static/host/chrome/SessionBadges.js``）与原位登录弹窗
（``web/static/host/chrome/LoginDialog.js``）由宿主外壳统一提供；本文件只读确认三个
旧页面在宿主外壳内渲染即可获得一致徽章与登录入口，不在页面内重造。

运行::

    python -B -m pytest -p no:cacheprovider tests/test_remaining_pages_behavior.py -q
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable, Iterator

import pytest
from flask import jsonify

from tests.browser.v2_fixtures import (  # noqa: F401 - pytest fixture 注入
    BrowserPage,
    LiveServer,
    assert_no_console_errors,
    browser,
    page,
    server,
)

STATUS_ROUTE = "#p/project-overview/status"
DETAILS_ROUTE = "#p/project-overview/details"
SETTINGS_ROUTE = "#p/settings/general"

PROJECT_STATUS_API = "api_project_status"
SETTINGS_API = "api_settings_get"

#: 浏览器把 4xx/5xx 响应记为 network error 日志；错误态用例只放行被测接口本身。
BOOT_CLAIM_PROBE = re.compile(r"status of 409 \(CONFLICT\).*/api/security/boot-claim")


def http_error(status: int, path: str) -> re.Pattern:
    """只放行「被测接口 + 指定状态码」这一条 console error。"""
    return re.compile(rf"status of {status} .*{re.escape(path)}")


# ── 真实 HTTP 层的状态驱动 ──────────────────────────────────────────────────


def _json(payload: Any, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


class Api:
    """替换被测服务进程内的真实视图函数，退出时恢复。

    页面侧看到的仍然是一次真实的 HTTP 往返（同一 ``create_app``、同一会话 Cookie、
    同一 ``/api/...`` 路径），只有响应内容由用例决定。
    """

    def __init__(self, live: LiveServer) -> None:
        self._live = live
        self._saved: dict[str, Callable[..., Any]] = {}

    def original(self, endpoint: str) -> Callable[..., Any]:
        return self._saved.get(endpoint) or self._live.app.view_functions[endpoint]

    def set(self, endpoint: str, handler: Callable[..., Any]) -> None:
        if endpoint not in self._saved:
            self._saved[endpoint] = self._live.app.view_functions[endpoint]
        self._live.app.view_functions[endpoint] = handler

    def payload(self, endpoint: str, data: Any) -> None:
        self.set(endpoint, lambda *args, **kwargs: _json({"ok": True, "data": data}))

    def failure(self, endpoint: str, status: int, message: str, kind: str = "ServerError") -> None:
        self.set(
            endpoint,
            lambda *args, **kwargs: _json({"ok": False, "error": {"type": kind, "message": message}}, status),
        )

    def restore(self) -> None:
        for endpoint, handler in self._saved.items():
            self._live.app.view_functions[endpoint] = handler
        self._saved.clear()


class Gate:
    """让被测接口挂起，直到用例放行；放行后交给原实现，返回真实种子数据。"""

    def __init__(self, fallback: Callable[..., Any]) -> None:
        self._fallback = fallback
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any):
        self.entered.set()
        if not self.release.wait(20):
            raise RuntimeError("加载态用例未在 20 秒内放行被测接口")
        return self._fallback(*args, **kwargs)


@pytest.fixture()
def api(server: LiveServer) -> Iterator[Api]:
    helper = Api(server)
    try:
        yield helper
    finally:
        helper.restore()


# ── DOM 断言小工具 ─────────────────────────────────────────────────────────


def _text_js(selector: str) -> str:
    return (
        "(() => { const el = document.querySelector(%s);"
        " return el ? el.innerText.trim() : ''; })()" % json.dumps(selector)
    )


def text_of(page: BrowserPage, selector: str) -> str:
    return str(page.eval(_text_js(selector)))


def count(page: BrowserPage, selector: str) -> int:
    return int(page.eval("document.querySelectorAll(%s).length" % json.dumps(selector)))


def has(page: BrowserPage, selector: str) -> bool:
    return bool(page.eval("Boolean(document.querySelector(%s))" % json.dumps(selector)))


def texts(page: BrowserPage, selector: str) -> list[str]:
    return list(
        page.eval(
            "Array.from(document.querySelectorAll(%s)).map((el) => el.innerText.trim())" % json.dumps(selector)
        )
        or []
    )


def color_matches(page: BrowserPage, selector: str, variable: str) -> bool:
    """断言元素计算色等于宿主 CSS 变量（例如 ``--success``），不看类名。"""
    script = (
        "(() => { const el = document.querySelector(%s); if (!el) return null;"
        " const probe = document.createElement('span');"
        " probe.style.color = 'var(%s)';"
        " document.body.appendChild(probe);"
        " const want = getComputedStyle(probe).color;"
        " const got = getComputedStyle(el).color;"
        " probe.remove();"
        " return want === got; })()" % (json.dumps(selector), variable)
    )
    return bool(page.eval(script))


def assert_clean_terms(page: BrowserPage) -> None:
    """页面上不应出现开发期残留（未定义/NaN/对象字面量），术语必须是给人看的。"""
    body = text_of(page, "#plugin-host")
    for junk in ("undefined", "NaN", "[object Object]"):
        assert junk not in body, page.diagnose(f"页面出现开发期残留 {junk}：{body[:800]}")


#: 项目概览的状态色词表（宿主 overview.css 的四个状态档）。
OVERVIEW_TONES = {
    "success": "--success",
    "warning": "--warning",
    "error": "--error",
    "primary": "--primary",
}


def assert_tone_palette(page: BrowserPage, selector: str, base_class: str) -> list[str]:
    """断言每个状态元素都落在已登记的状态档，且计算色等于宿主 CSS 变量。

    只看渲染后的类与计算样式，不把「源码里出现过组件名」当验收。
    """
    classes = [
        str(item)
        for item in (
            page.eval(
                "Array.from(document.querySelectorAll(%s)).map((el) => el.className)" % json.dumps(selector)
            )
            or []
        )
    ]
    assert classes, page.diagnose(f"{selector} 没有渲染任何状态元素")
    tones = []
    for value in classes:
        match = re.fullmatch(rf"{re.escape(base_class)} is-([a-z]+)", value)
        assert match and match.group(1) in OVERVIEW_TONES, page.diagnose(f"未登记的状态色：{value!r}")
        tones.append(match.group(1))
    for tone in sorted(set(tones)):
        assert color_matches(page, f"{selector}.is-{tone}", OVERVIEW_TONES[tone]), page.diagnose(
            f"{selector} 的 {tone} 档没有取宿主 {OVERVIEW_TONES[tone]}"
        )
    return tones


# ── 合成载荷 ───────────────────────────────────────────────────────────────


def phase(**overrides: Any) -> dict[str, Any]:
    data = {
        "id": "VPI-T2",
        "displayName": "F610S",
        "status": "进行中",
        "overallProgress": 40,
        "startDate": "2026-01-05",
        "endDate": "2026-12-20",
        "today": "2026-10-31",
    }
    data.update(overrides)
    return data


def milestone(index: int, *, status: str = "进行中") -> dict[str, Any]:
    return {
        "id": f"M-{index}",
        "name": f"示例节点 {index}",
        "date": f"2026-{index:02d}-15",
        "status": status,
        "type": "planned",
        "sortOrder": index,
    }


def deliverable(**overrides: Any) -> dict[str, Any]:
    data = {
        "id": "VPI-T2-D1",
        "name": "示例交付物",
        "status": "进行中",
        "plannedDate": "2026-11-30",
        "progress": 0,
        "note": "",
        "source": "手工维护",
    }
    data.update(overrides)
    return data


def project_status(
    *,
    milestones: list[dict[str, Any]] | None = None,
    deliverables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "phase": phase(),
        "milestones": milestones if milestones is not None else [milestone(1), milestone(2)],
        "deliverables": deliverables if deliverables is not None else [deliverable()],
        "months": ["1月", "2月", "3月"],
    }


def settings_payload(
    *,
    settings: dict[str, Any] | None = None,
    sessions: dict[str, Any] | None = None,
    vault_configured: bool = False,
) -> dict[str, Any]:
    return {
        "settings": settings if settings is not None else {},
        "sessions": sessions if sessions is not None else {},
        "credentialVaultConfigured": vault_configured,
        "excelService": {"configured": False},
    }


# ═══════════════════════════════════════════════════════════════════════════
# 项目状态页 (#p/project-overview/status)
# ═══════════════════════════════════════════════════════════════════════════


def test_status_page_normal_state_renders_plan_node_and_tones(server: LiveServer, page: BrowserPage) -> None:
    """正常：真实种子数据渲染时间轴、当前节点与交付物环图，状态色取宿主变量。"""
    page.goto(server.route_url(STATUS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_function("!document.querySelector('.project-overview .loading')")
    page.wait_for_selector(".project-overview article.progress-ring")

    tabs = texts(page, ".overview-switch [role=tab]")
    assert tabs == ["项目状态", "交付物明细", "主计划维护"], page.diagnose(f"概览 tab 异常：{tabs}")
    assert page.eval(
        "document.querySelector('.overview-switch .overview-tab.active').textContent.trim()"
    ) == "项目状态"

    # 主计划时间轴：默认种子项目 F610S，节点与「今天」标记都在真实 DOM 里。
    assert text_of(page, ".milestone-timeline h4") == "F610S", page.diagnose("时间轴标题不是默认项目")
    assert count(page, ".milestone-node") >= 1, page.diagnose("主计划节点未渲染")
    assert count(page, ".today-marker") == 1, page.diagnose("今天标记未渲染")
    assert "当前节点" in text_of(page, ".milestone-timeline")

    # 当前节点 band：标题来自主计划，附带计划日期与时间口径。
    assert text_of(page, ".node-focus-title"), page.diagnose("当前节点标题为空")
    assert "计划日期：" in text_of(page, ".phase-summary")

    # 交付物环图 + 状态色：每个环的状态都必须落在已登记的状态档，且取宿主变量。
    assert count(page, "article.progress-ring") >= 1, page.diagnose("交付物环图未渲染")
    assert_tone_palette(page, ".ring-status", "ring-status")

    assert not has(page, ".overview-load-error"), page.diagnose("正常态出现加载失败区块")
    assert not has(page, ".milestone-timeline .is-empty"), page.diagnose("正常态出现空数据占位")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_status_page_loading_state_then_resolves(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """加载中：接口挂起时三个 band 都显示「加载中」，放行后替换成真实内容。"""
    gate = Gate(api.original(PROJECT_STATUS_API))
    api.set(PROJECT_STATUS_API, gate)

    page.goto(server.route_url(STATUS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_function("document.querySelectorAll('.project-overview .loading').length >= 3")

    assert gate.entered.wait(20), page.diagnose("页面没有真正请求 /api/project-status")
    assert text_of(page, ".milestone-timeline") == "加载中", page.diagnose("时间轴缺少加载占位")
    assert text_of(page, ".phase-summary") == "加载中", page.diagnose("当前节点缺少加载占位")
    # 加载态下 tab 条已经可用，页面不塌陷。
    assert count(page, ".overview-switch [role=tab]") == 3

    gate.release.set()
    page.wait_for_selector(".milestone-node")
    assert not has(page, ".project-overview .loading"), page.diagnose("放行后仍停留在加载态")
    assert count(page, "article.progress-ring") >= 1
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_status_page_empty_payload_shows_placeholder(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """空数据：接口成功但没有阶段数据，三个 band 都必须给出「暂无数据」。"""
    api.payload(PROJECT_STATUS_API, {})

    page.goto(server.route_url(STATUS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_function("!document.querySelector('.project-overview .loading')")

    assert text_of(page, ".milestone-timeline") == "暂无数据"
    assert text_of(page, ".phase-summary") == "暂无数据"
    assert "暂无数据" in text_of(page, ".deliverable-status-band")
    assert not has(page, ".overview-load-error"), page.diagnose("空数据被当成加载失败")
    assert count(page, "article.progress-ring") == 0
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_status_page_error_state_retries_with_real_click(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """错误：接口 500 时给出「加载失败：…」+ 可点重试；真实点击后恢复。"""
    api.failure(PROJECT_STATUS_API, 500, "项目状态读取失败")

    page.goto(server.route_url(STATUS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_selector(".milestone-timeline .overview-load-error")

    assert "加载失败：" in text_of(page, ".milestone-timeline"), page.diagnose("缺少失败文案")
    assert "项目状态读取失败" in text_of(page, ".milestone-timeline"), page.diagnose("失败原因未展示")
    assert has(page, ".milestone-timeline .overview-load-error [role=alert]"), page.diagnose(
        "失败提示缺少 role=alert"
    )
    assert count(page, ".overview-retry-btn") >= 1, page.diagnose("缺少重试按钮")
    assert_clean_terms(page)

    # 恢复真实实现后，真实鼠标点击「重试」应重新取数并渲染内容。
    api.restore()
    clicked = page.click(selector=".milestone-timeline .overview-retry-btn")
    assert clicked.text.strip() == "重试", page.diagnose(f"点击目标不是重试按钮：{clicked}")
    page.wait_for_selector(".milestone-node")
    assert "加载失败" not in text_of(page, ".milestone-timeline")
    assert_no_console_errors(page, allow=(http_error(500, "/api/project-status"), BOOT_CLAIM_PROBE))


def test_status_page_plan_unconfigured_uses_existing_term(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """未配置：有阶段但主计划没有节点，必须给「主计划待设置」而不是整页「暂无数据」。"""
    api.payload(PROJECT_STATUS_API, project_status(milestones=[], deliverables=[]))

    page.goto(server.route_url(STATUS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_function("!document.querySelector('.project-overview .loading')")

    assert "主计划待设置" in text_of(page, ".milestone-timeline"), page.diagnose("时间轴未提示主计划待设置")
    assert "主计划待设置" in text_of(page, ".phase-summary"), page.diagnose("当前节点未提示主计划待设置")
    assert not has(page, ".milestone-timeline .is-empty"), page.diagnose("未配置被降级成通用空数据")

    # 未配置态必须可操作：编辑主计划入口指向主计划维护页。
    edit_links = page.eval(
        "Array.from(document.querySelectorAll('a.timeline-edit-btn'))"
        ".map((a) => a.getAttribute('href'))"
    ) or []
    assert len(edit_links) >= 2, page.diagnose(f"缺少编辑主计划入口：{edit_links}")
    assert all("project-overview/plan" in str(href) for href in edit_links), page.diagnose(
        f"编辑主计划入口地址异常：{edit_links}"
    )
    assert count(page, ".milestone-node") == 0
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_status_page_deliverable_tones_follow_host_palette(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """状态色：已完成/已逾期/待审批/进行中分别落在宿主 success/error/warning/primary 四档。"""
    api.payload(
        PROJECT_STATUS_API,
        project_status(
            deliverables=[
                deliverable(id="D-1", name="已完成交付物", status="已完成", progress=100, actualDate="2026-10-20"),
                deliverable(id="D-2", name="已逾期交付物", status="已逾期", progress=30),
                deliverable(id="D-3", name="待审批交付物", status="待审批", progress=50),
                deliverable(id="D-4", name="进行中交付物", status="进行中", progress=20),
            ]
        ),
    )

    page.goto(server.route_url(STATUS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_function("document.querySelectorAll('.ring-status').length === 4")

    rings = page.eval(
        "Array.from(document.querySelectorAll('article.progress-ring')).map((el) => ({"
        " name: el.querySelector('.ring-name').textContent.trim(),"
        " status: el.querySelector('.ring-status').className,"
        " center: el.querySelector('.ring-center').textContent.trim() }))"
    ) or []
    by_name = {str(item["name"]): item for item in rings}
    expected = {
        "已完成交付物": ("is-success", "100%"),
        "已逾期交付物": ("is-error", "30%"),
        "待审批交付物": ("is-warning", "50%"),
        "进行中交付物": ("is-primary", "20%"),
    }
    assert set(by_name) == set(expected), page.diagnose(f"交付物环图不完整：{by_name}")
    for name, (tone, center) in expected.items():
        assert by_name[name]["status"] == f"ring-status {tone}", page.diagnose(
            f"{name} 的状态档异常：{by_name[name]['status']!r}"
        )
        assert by_name[name]["center"] == center, page.diagnose(f"{name} 的环心文本异常：{by_name[name]['center']!r}")

    assert_tone_palette(page, ".ring-status", "ring-status")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ═══════════════════════════════════════════════════════════════════════════
# 交付物明细页 (#p/project-overview/details)
# ═══════════════════════════════════════════════════════════════════════════

def test_details_page_normal_state_renders_summary_table_and_reference(
    server: LiveServer, page: BrowserPage
) -> None:
    """正常：阶段摘要、自动同步调度条、交付物明细表与外部来源参考都渲染。"""
    page.goto(server.route_url(DETAILS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='交付物明细']")
    page.wait_for_function("!document.querySelector('.project-overview .loading')")
    page.wait_for_selector(".deliverable-detail-row")

    assert page.eval(
        "document.querySelector('.overview-switch .overview-tab.active').textContent.trim()"
    ) == "交付物明细"

    cells = texts(page, ".details-phase-cell")
    assert len(cells) == 4, page.diagnose(f"阶段摘要格子数量异常：{cells}")
    assert "当前阶段" in cells[0] and "VPI-T2" in cells[0], page.diagnose(f"阶段摘要异常：{cells}")
    assert any("总体进度" in cell and "%" in cell for cell in cells), page.diagnose(f"缺少总体进度：{cells}")

    # 自动同步调度条走真实 /api/project-status/scheduler。
    page.wait_for_function(
        "document.querySelector('.details-sync-indicator')"
        " && !document.querySelector('.details-sync-indicator').textContent.includes('检测中')"
    )
    assert "自动同步" in text_of(page, ".details-sync-indicator"), page.diagnose("调度条未渲染状态")

    headers = texts(page, ".overview-details-table thead th")
    assert headers[:6] == ["交付物", "状态", "计划完成", "实际完成或当前进度", "风险与备注", "数据来源"], page.diagnose(
        f"明细表表头异常：{headers}"
    )
    assert "同步设置" in headers, page.diagnose(f"缺少同步设置列：{headers}")

    rows = count(page, ".deliverable-detail-row")
    assert rows >= 1, page.diagnose("明细表没有数据行")
    assert has(page, ".deliverable-detail-row td[data-label='交付物']"), page.diagnose("行内缺少数据标签")
    assert count(page, ".deliverable-detail-row .detail-expand") == rows, page.diagnose("每行都应有查看明细入口")

    # 状态色取宿主变量，而不是只看类名。
    assert_tone_palette(page, ".overview-details-table .status-text", "status-text")

    assert text_of(page, ".external-deliverables-band h4") == "外部来源交付物（参考）"
    assert "快照仅参考" in text_of(page, ".external-deliverables-band")
    assert not has(page, ".overview-load-error"), page.diagnose("正常态出现加载失败区块")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_details_page_loading_state_then_resolves(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """加载中：摘要 band 与表格行同时显示「加载中」，放行后出现数据行。"""
    gate = Gate(api.original(PROJECT_STATUS_API))
    api.set(PROJECT_STATUS_API, gate)

    page.goto(server.route_url(DETAILS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='交付物明细']")
    page.wait_for_function("document.querySelectorAll('.project-overview .loading').length >= 2")

    assert gate.entered.wait(20), page.diagnose("页面没有真正请求 /api/project-status")
    assert text_of(page, ".details-summary-band") == "加载中"
    assert text_of(page, ".overview-details-table tbody") == "加载中"
    assert count(page, ".deliverable-detail-row") == 0

    gate.release.set()
    page.wait_for_selector(".deliverable-detail-row")
    assert not has(page, ".details-summary-band .loading"), page.diagnose("放行后摘要仍是加载态")
    assert "加载中" not in text_of(page, ".overview-details-table tbody")
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_details_page_empty_payload_shows_placeholder(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """空数据：接口成功但没有数据，摘要与表格都给出「暂无数据」。"""
    api.payload(PROJECT_STATUS_API, {})

    page.goto(server.route_url(DETAILS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='交付物明细']")
    page.wait_for_function("!document.querySelector('.project-overview .loading')")

    assert text_of(page, ".details-summary-band") == "暂无数据"
    assert text_of(page, ".overview-details-table tbody") == "暂无数据"
    assert count(page, ".deliverable-detail-row") == 0
    assert not has(page, ".overview-load-error"), page.diagnose("空数据被当成加载失败")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_details_page_error_state_retries_with_real_click(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """错误：接口 500 时摘要与表格都给失败提示；真实点击重试后恢复。"""
    api.failure(PROJECT_STATUS_API, 500, "项目状态读取失败")

    page.goto(server.route_url(DETAILS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='交付物明细']")
    page.wait_for_selector(".details-summary-band .overview-load-error")

    assert "加载失败：" in text_of(page, ".details-summary-band")
    assert "加载失败：" in text_of(page, ".overview-details-table tbody")
    assert has(page, ".overview-details-table tbody [role=alert]"), page.diagnose("表格失败提示缺少 role=alert")
    assert_clean_terms(page)

    api.restore()
    clicked = page.click(selector=".details-summary-band .overview-retry-btn")
    assert clicked.text.strip() == "重试", page.diagnose(f"点击目标不是重试按钮：{clicked}")
    page.wait_for_selector(".deliverable-detail-row")
    assert "加载失败" not in text_of(page, ".details-summary-band")
    assert_no_console_errors(page, allow=(http_error(500, "/api/project-status"), BOOT_CLAIM_PROBE))


def test_details_page_sync_unconfigured_uses_existing_term(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """未配置：交付物同步未配置时状态列与进度列都显示既有术语「待配置」。"""
    api.payload(
        PROJECT_STATUS_API,
        project_status(
            deliverables=[
                deliverable(
                    id="VPI-T2-D9",
                    name="待配置同步的交付物",
                    syncDisplay={"state": "pending_config"},
                )
            ]
        ),
    )

    page.goto(server.route_url(DETAILS_ROUTE))
    page.wait_for_selector("section.project-overview[aria-label='交付物明细']")
    page.wait_for_selector(".deliverable-detail-row")

    status_cell = text_of(page, ".deliverable-detail-row td[data-label='状态']")
    progress_cell = text_of(page, ".deliverable-detail-row td[data-label='实际完成或当前进度']")
    assert status_cell == "待配置", page.diagnose(f"状态列不是既有术语：{status_cell!r}")
    assert progress_cell == "待配置", page.diagnose(f"进度列不是既有术语：{progress_cell!r}")

    # 未配置的交付物不能冒充正常进度色，也不显示 0%。
    assert color_matches(page, ".deliverable-detail-row .status-text", "--primary"), page.diagnose(
        "未配置状态色不是宿主 --primary"
    )

    # 没有同步设置行时单元格显示占位符而不是空白。
    assert text_of(page, ".deliverable-detail-row .sync-settings-none") == "—"
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ═══════════════════════════════════════════════════════════════════════════
# 系统设置页 (#p/settings/general)
# ═══════════════════════════════════════════════════════════════════════════


def test_settings_page_normal_state_renders_form_and_cards(server: LiveServer, page: BrowserPage) -> None:
    """正常：真实 /api/settings 渲染设置表单、会话卡与版本卡。"""
    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector(".st-layout")
    page.wait_for_selector(".st-form")

    assert text_of(page, ".vk-page-header h2") == "设置", page.diagnose("设置页标题异常")
    assert "大部分情况下不需要改这里" in text_of(page, ".vk-page-header")

    # 日常业务目录 + 保存入口。
    assert has(page, "#st-field-archiveDirectory"), page.diagnose("缺少归档保存目录输入框")
    assert has(page, "#st-field-excelDirectory"), page.diagnose("缺少 Excel 工作目录输入框")
    assert text_of(page, ".st-form button[type=submit]") == "保存设置"
    assert has(page, "details.st-advanced"), page.diagnose("缺少高级与维护设置折叠块")

    # 会话卡：两个企业系统 + 凭据保护库，术语只能取既有三档。
    assert "企业认证会话状态" in text_of(page, ".st-side"), page.diagnose("缺少企业认证会话卡")
    chips = texts(page, ".st-chip")
    assert chips, page.diagnose("会话卡没有状态胶囊")
    allowed = {"已认证", "已过期", "未认证", "已配置", "未配置"}
    assert set(chips) <= allowed, page.diagnose(f"出现未登记的会话术语：{chips}")

    # 版本卡走真实 /api/version。
    page.wait_for_function(
        "Array.from(document.querySelectorAll('.st-kv dt')).some((dt) => dt.textContent.includes('应用版本'))"
    )
    assert "程序与插件更新" in text_of(page, ".st-side")

    assert not has(page, ".uk-error-card"), page.diagnose("正常态出现错误卡")
    assert not has(page, ".uk-skeleton"), page.diagnose("正常态仍显示骨架屏")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_settings_page_loading_state_then_resolves(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """加载中：/api/settings 挂起时显示骨架屏，放行后出现设置表单。"""
    gate = Gate(api.original(SETTINGS_API))
    api.set(SETTINGS_API, gate)

    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector(".uk-skeleton")

    assert gate.entered.wait(20), page.diagnose("页面没有真正请求 /api/settings")
    assert text_of(page, ".vk-page-header h2") == "系统设置", page.diagnose("加载态标题应为「系统设置」")
    assert page.eval("document.querySelector('.uk-skeleton').getAttribute('aria-busy')") == "true"
    assert not has(page, ".st-form"), page.diagnose("加载态不应渲染半成品表单")

    gate.release.set()
    page.wait_for_selector(".st-form")
    assert text_of(page, ".vk-page-header h2") == "设置"
    assert not has(page, ".uk-skeleton")
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_settings_page_empty_payload_renders_defaults(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """空数据：接口成功但没有任何设置项，表单必须回落到默认值而不是空白。"""
    api.payload(SETTINGS_API, {})

    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector(".st-form")

    assert page.eval("document.querySelector('#st-field-archiveDirectory').value") == ""
    assert page.eval("document.querySelector('#st-field-retryCount').value") == "2", page.diagnose(
        "整数项没有回落到默认值"
    )
    assert page.eval("document.querySelector('#st-field-dueSoonDays').value") == "7"
    chips = texts(page, ".st-chip")
    assert "未认证" in chips and "未配置" in chips, page.diagnose(f"空数据下会话术语异常：{chips}")
    assert not has(page, ".uk-error-card")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_settings_page_error_state_retries_with_real_click(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """错误：/api/settings 500 时给出统一错误卡（发生了什么/你需要做什么）并可重新加载。"""
    api.failure(SETTINGS_API, 500, "设置读取失败")

    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector(".uk-error-card")

    assert text_of(page, ".vk-page-header h2") == "系统设置", page.diagnose("错误态标题应为「系统设置」")
    card = text_of(page, ".uk-error-card")
    assert "发生了什么" in card and "你需要做什么" in card, page.diagnose(f"错误卡结构异常：{card}")
    assert "设置读取失败" in card, page.diagnose("错误卡没有展示失败原因")
    assert text_of(page, ".uk-error-card .uk-fixit-btn") == "重新加载", page.diagnose("非认证错误应提供重新加载")
    assert_clean_terms(page)

    api.restore()
    clicked = page.click(selector=".uk-error-card .uk-fixit-btn")
    assert clicked.text.strip() == "重新加载"
    page.wait_for_selector(".st-form")
    assert not has(page, ".uk-error-card"), page.diagnose("重新加载后错误卡未消失")
    assert_no_console_errors(page, allow=(http_error(500, "/api/settings"), BOOT_CLAIM_PROBE))


def test_settings_page_unconfigured_vault_uses_off_tone(server: LiveServer, page: BrowserPage, api: Api) -> None:
    """未配置：凭据保护库未配置显示「未配置」灰档；已认证会话显示「已认证」绿档。"""
    api.payload(
        SETTINGS_API,
        settings_payload(
            sessions={"aras": {"authenticated": True, "updatedAt": "2026-10-31T01:00:00Z"}},
            vault_configured=False,
        ),
    )

    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector(".st-form")
    page.wait_for_selector(".st-chip.is-ok")

    rows = texts(page, ".st-status-row")
    vault_row = next((row for row in rows if "凭据保护库" in row), "")
    assert "未配置" in vault_row, page.diagnose(f"凭据保护库未配置态缺失：{rows}")

    assert color_matches(page, ".st-chip.is-ok", "--success"), page.diagnose("已认证不是宿主 --success")
    idle_chip = page.eval(
        "(() => { const chip = Array.from(document.querySelectorAll('.st-chip'))"
        ".find((el) => el.textContent.trim() === '未配置');"
        " return chip ? chip.className : null; })()"
    )
    assert idle_chip, page.diagnose("找不到「未配置」胶囊")
    assert color_matches(
        page,
        ".st-chip.is-idle",
        "--muted",
    ), page.diagnose("未配置不是宿主灰色档（--muted）")

    # 已认证会话的更新时间必须是可读时间，不是原始 ISO 串。
    aras_row = next((row for row in rows if "ECM 流程会话" in row), "")
    assert re.search(r"更新时间 \d{4}-\d{2}-\d{2} \d{2}:\d{2} · 有效", aras_row), page.diagnose(
        f"会话更新时间格式异常：{aras_row!r}"
    )
    assert "T01:00:00Z" not in aras_row, page.diagnose("页面泄漏了原始时间戳")
    assert_clean_terms(page)
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_settings_page_auth_error_opens_host_in_place_login(
    server: LiveServer, page: BrowserPage, api: Api
) -> None:
    """认证失效：设置页的错误卡必须复用宿主原位登录，而不是让用户离开当前页面。"""
    api.failure(SETTINGS_API, 401, "未登录", kind="Unauthorized")

    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector(".uk-error-card")

    card = text_of(page, ".uk-error-card")
    assert "企业认证会话已失效" in card, page.diagnose(f"认证失效文案异常：{card}")
    assert "重新登录" in text_of(page, ".uk-error-card .uk-fixit-btn"), page.diagnose("缺少重新登录入口")

    clicked = page.click(selector=".uk-error-card .uk-fixit-btn")
    assert "重新登录" in clicked.text
    page.wait_for_function("!document.querySelector('#hc-login-dialog').hidden")
    assert "登录企业系统" in text_of(page, "#hc-login-dialog")
    assert "企业会话已失效" in text_of(page, "#hc-login-notice"), page.diagnose("原位登录弹窗未带上下文提示")
    # 原位：设置页仍在，表单/草稿没有被导航掉。
    assert has(page, ".st-page"), page.diagnose("打开登录弹窗后离开了设置页")
    assert_no_console_errors(page, allow=(http_error(401, "/api/settings"), BOOT_CLAIM_PROBE))


# ═══════════════════════════════════════════════════════════════════════════
# 顶栏三档会话徽章与原位登录（与 W3-01 一致）
# ═══════════════════════════════════════════════════════════════════════════


def test_legacy_pages_share_host_session_badge_and_login_entry(server: LiveServer, page: BrowserPage) -> None:
    """三个旧页面都在宿主外壳内渲染：同一枚三档胶囊 + 同一套原位登录入口。"""
    page.goto(server.route_url(SETTINGS_ROUTE))
    page.wait_for_selector("#hc-login-btn")
    page.wait_for_selector(".st-layout")

    # 宿主发布给插件的兼容全局，设置页的 errorFixAction/refreshGlobalBadges 依赖它们。
    assert page.eval("typeof window.openInPlaceLogin") == "function", page.diagnose("宿主未发布原位登录入口")
    assert page.eval("typeof window.updateGlobalSessionBadges") == "function", page.diagnose(
        "宿主未发布会话徽章刷新入口"
    )

    # 三档之一，且颜色取宿主 TONE（ok/warn/bad）。
    classes = str(page.eval("document.querySelector('#hc-login-btn').className"))
    tiers = [tone for tone in ("ok", "warn", "bad") if f"is-{tone}" in classes]
    assert len(tiers) == 1, page.diagnose(f"会话胶囊不是三档之一：{classes}")
    tone = tiers[0]
    assert color_matches(page, "#hc-login-btn", {"ok": "--success", "warn": "--warning", "bad": "--error"}[tone]), (
        page.diagnose(f"会话胶囊 {tone} 档颜色与宿主状态色不一致")
    )

    # 未登录项目（种子库无企业会话）→ 需要重新登录 → 点击打开宿主登录弹窗。
    assert tone == "bad", page.diagnose(f"空会话应为「需要重新登录」：{classes}")
    assert "需要重新登录" in text_of(page, "#hc-login-btn")
    page.click(selector="#hc-login-btn")
    page.wait_for_function("!document.querySelector('#hc-login-dialog').hidden")
    page.click(selector="#hc-login-cancel-btn")
    page.wait_for_function("document.querySelector('#hc-login-dialog').hidden")

    # 切到两个项目概览旧页面：外壳不重挂，徽章与登录入口保持一致。
    for route, plugin_id in ((STATUS_ROUTE, "project-overview"), (DETAILS_ROUTE, "project-overview")):
        page.eval("location.hash = %s" % json.dumps(route))
        page.wait_for_function(
            "document.body.dataset.routePlugin === %s" % json.dumps(plugin_id)
        )
        page.wait_for_selector("section.project-overview")
        assert count(page, "#hc-login-btn") == 1, page.diagnose(f"{route} 出现了第二枚会话徽章")
        assert page.eval("typeof window.openInPlaceLogin") == "function"
        assert color_matches(page, "#hc-login-btn", "--error"), page.diagnose(f"{route} 的徽章颜色被页面改写")

    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))
