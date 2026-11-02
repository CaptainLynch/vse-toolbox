# -*- coding: utf-8 -*-
"""DSH-V2-40：真实 DOM 可见文案与 aria / title 门禁（只读测试，不改产品）。

口径
====
1. **真实渲染**：用 ``tests/browser/v2_fixtures.py``（Edge/Chrome 无头 + CDP）打开
   宿主外壳与各插件 ``plugin.json`` 里 ``pages`` 声明的页面，抓
   ``document.body.innerText``、``document.title`` 与全部 ``aria-label`` / ``title``
   属性值，再套 ``tests/test_glossary_terms.py`` 的同一套禁词/路径规则。
2. **数据**：测试服务器自带临时 SQLite，页面用合成/空数据；空态、未登录态、
   未配置态的文案同样检查（契约允许，不要求构造业务数据）。
3. **源级 vs DOM**：``tests/test_glossary_terms.py`` 仍做 JS 字符串源级扫描，但
   **不计入**本文件的 DOM 验收页面数；本文件唯一的源级断言是「页面清单一致性」，
   它只证明每个声明页面要么被 DOM 验收、要么写明未覆盖原因，不冒充行为验收。
4. **无浏览器/Node**：沿用夹具约定 ``pytest.skip`` 并写明缺什么，绝不用源码
   断言顶替 DOM 验收。
5. **白名单预算**：``DOM_WHITELIST`` 为空（本任务不新增 DOM 白名单）；
   实测到的真实文案违规登记在 ``KNOWN_VIOLATIONS``（带理由 + 后续建议），
   二者合计 ≤ ``BASELINE_WHITELIST_ENTRIES``（任务开始时
   ``tests/golden/glossary_baseline.json`` 的 23 项）。既有源级白名单逐项审计
   在 ``tests/test_glossary_terms.py`` 的 ``BASELINE_AUDIT``。
6. **不改产品**：本文件只登记违规，不修文案；文件/行与建议见最终报告。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import pytest

from tests.browser.v2_fixtures import (  # noqa: F401 - pytest fixture 注入
    BrowserPage,
    LiveServer,
    browser,
    page,
    server,
)
from tests.test_glossary_terms import (
    BASELINE_WHITELIST_ENTRIES,
    REPO_ROOT,
    scan_text_segment,
)

# ── 页面清单：plugin.json pages 声明 → 真实渲染验收 ─────────────────────────

#: 主控契约点名的页面（路由键）。报告中心在插件里就是 workbench/reports（nav 名「报告」）。
CONTRACT_REQUIRED_PAGES = frozenset(
    {
        "workbench/reports",  # 报告中心
        "project-overview/deliverable",  # 交付物详情
        "project-overview/status",  # 项目状态
        "settings/general",  # 设置各页（1/2）
        "settings/updates",  # 设置各页（2/2）
        "diagnostics/self-check",  # 自检
        "sync-control/schedule",  # 调度设置（调度时刻）
        "excel-tasks/workspace",  # Excel
        "system-query/query",  # 系统查询
    }
)

DOM_GROUP_ORDER = ("required", "project", "forms", "reports")


@dataclass(frozen=True)
class DomPage:
    """一个要在真实浏览器里渲染验收的页面。"""

    plugin: str
    page: str
    label: str
    group: str
    #: 页面主内容就绪选择器；空串表示只等「无加载态 + 有可见文本」。
    ready_selector: str = ""
    #: 就绪后再等一小段，让异步数据落 DOM（毫秒）。
    settle_ms: int = 400

    @property
    def key(self) -> str:
        return f"{self.plugin}/{self.page}"

    @property
    def hash_route(self) -> str:
        return f"#p/{self.plugin}/{self.page}"


DOM_PAGES: tuple[DomPage, ...] = (
    # 契约点名页
    DomPage("workbench", "reports", "报告中心（报告）", "required"),
    DomPage("project-overview", "deliverable", "交付物详情", "required"),
    DomPage("project-overview", "status", "项目状态", "required"),
    DomPage("settings", "general", "系统设置", "required"),
    DomPage("settings", "updates", "插件更新", "required"),
    DomPage("diagnostics", "self-check", "自检", "required", ready_selector=".diag-item", settle_ms=200),
    DomPage("sync-control", "schedule", "调度时刻", "required"),
    DomPage("excel-tasks", "workspace", "Excel 文件处理", "required", settle_ms=800),
    DomPage("system-query", "query", "系统查询", "required"),
    # 项目概览其余页面
    DomPage("project-overview", "details", "交付物明细", "project"),
    DomPage("project-overview", "plan", "主计划维护", "project"),
    DomPage("project-overview", "archive-deliverable", "归档交付物详情", "project"),
    DomPage("project-overview", "auto-sync", "一键开启自动同步", "project"),
    DomPage("scheduled-archive", "jobs", "自动下载与留存", "project"),
    # 交付物表单（index 是模块页，其余 6 个是 schema 页）
    DomPage("deliverable-forms", "index", "交付物表单", "forms"),
    DomPage("deliverable-forms", "ewo", "EWO 进度", "forms"),
    DomPage("deliverable-forms", "paa", "PAA 进度", "forms"),
    DomPage("deliverable-forms", "ncr_progress", "NCR 审批进度", "forms"),
    DomPage("deliverable-forms", "ncr_detail", "NCR 审批明细", "forms"),
    DomPage("deliverable-forms", "tdc_data_model", "数模设计审核流程", "forms"),
    DomPage("deliverable-forms", "tdc_sor", "SOR 定点流程", "forms"),
    # 工作台与报告类页面
    DomPage("workbench", "today", "今天", "reports"),
    DomPage("workbench", "project", "项目", "reports"),
    DomPage("workbench", "tools", "工具", "reports"),
    DomPage("sign-daily", "report", "签署日报", "reports"),
    DomPage("tir-report", "report", "TIR 数据简表", "reports"),
)

#: 页面级未覆盖清单：当前为空——26 个声明页面全部在真实浏览器里渲染验收。
#: 将来若有页面无法离线渲染，必须在此登记原因；test_declared_pages_are_covered
#: 会强制「声明页面 = DOM 验收 ∪ 未覆盖（带原因）」。
UNCOVERED_PAGES: dict[str, str] = {}

@dataclass(frozen=True)
class UncoveredState:
    """已做页面级 DOM 验收、但某个状态未覆盖的说明。"""

    #: 页面键；"" 表示不属于任何 plugin.json 声明页面（例如全局模态层）。
    page_key: str
    state: str
    reason: str


#: 状态级未覆盖清单（页面已 DOM 验收，但某些状态需要业务数据/外部系统）。
#: 这些不算页面未覆盖，只在报告里如实列出，避免把空态验收说成完整行为验收。
UNCOVERED_STATES: tuple[UncoveredState, ...] = (
    UncoveredState(
        "project-overview/deliverable",
        "有数据时的交付物详情正文",
        "临时库没有交付物记录，只能验收「未找到编号…」空态；构造种子数据超出本任务（只改测试）范围。",
    ),
    UncoveredState(
        "project-overview/archive-deliverable",
        "归档任务详情",
        "需要归档任务记录（?job=），空库只能验收「未找到该外部同步任务」空态。",
    ),
    UncoveredState(
        "deliverable-forms/*",
        "有数据时的表格单元格与筛选结果",
        "6 个 schema 页在空库下只渲染空表（「没有符合条件的记录」），数据行文案未覆盖。",
    ),
    UncoveredState(
        "sign-daily/report",
        "生成结果预览 / 邮件草稿",
        "生成需要 TDC 数模审批数据；离线夹具禁止外部系统，只验收空态与未登录提示。",
    ),
    UncoveredState(
        "tir-report/report",
        "导出结果与历史文件",
        "导出需要帆软报表平台与域账号凭据；离线夹具只验收未登录/空态文案。",
    ),
    UncoveredState(
        "excel-tasks/workspace",
        "任务创建与处理中状态",
        "测试环境未配置 Excel 工作目录（接口 503），只验收未配置空态。",
    ),
    UncoveredState(
        "settings/general",
        "「高级与维护设置」展开后的表单",
        "折叠态摘要已验收；展开态需要真实点击，本门禁只做页面级可见文案。",
    ),
    UncoveredState(
        "",
        "模态层（登录对话框 / 任务中心 / 首次向导）",
        "不属于 plugin.json 的 pages 声明；首次向导已由 tests/browser/test_v2_user_paths.py 用真实点击覆盖。",
    ),
)

#: DOM 层白名单：本任务不新增（空）。既有源级白名单见 tests/golden/glossary_baseline.json
#: 与 tests/test_glossary_terms.py::BASELINE_AUDIT（23 项逐项有理由）。
DOM_WHITELIST: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class KnownViolation:
    """真实渲染出来的文案违规：不改产品，只登记并给出后续建议。"""

    copy: str
    reason: str
    follow_up: str


#: 实测到的真实文案违规（页面键, 术语）→ 登记。键必须仍然命中，否则门禁失败要求删除，
#: 防止「登记了却早已修好」的条目长期掩盖回归。
KNOWN_VIOLATIONS: dict[tuple[str, str], KnownViolation] = {
    ("deliverable-forms/index", "快照"): KnownViolation(
        copy="各表单数据来自最近一次自动归档快照；同步与归档配置在「自动归档」页。",
        reason="「快照」是内部归档实现术语，直接写进面向用户的页面说明，用户无法据此判断数据时间。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/index.js:22。",
    ),
    ("deliverable-forms/ewo", "快照"): KnownViolation(
        copy="数据来自最近一次自动归档快照；逾期口径与旧表单页一致（按阶段停留天数与计划日期判定）。",
        reason="schema 页面描述把内部归档术语「快照」暴露给用户；源级门禁只扫 .js，扫不到 pages/*.json。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/pages/ewo.json:4。",
    ),
    ("deliverable-forms/paa", "快照"): KnownViolation(
        copy="数据来自最近一次自动归档快照；逾期口径与旧表单页一致（按阶段停留天数与计划日期判定）。",
        reason="同 ewo：schema 页面描述泄露内部归档术语「快照」。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/pages/paa.json:4。",
    ),
    ("deliverable-forms/ncr_progress", "快照"): KnownViolation(
        copy="数据来自最近一次自动归档快照；逾期口径与旧表单页一致（按阶段停留天数与计划日期判定）。",
        reason="同 ewo：schema 页面描述泄露内部归档术语「快照」。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/pages/ncr_progress.json:4。",
    ),
    ("deliverable-forms/ncr_detail", "快照"): KnownViolation(
        copy="数据来自最近一次自动归档快照；该表单不做逾期判定。",
        reason="同 ewo：schema 页面描述泄露内部归档术语「快照」。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/pages/ncr_detail.json:4。",
    ),
    ("deliverable-forms/tdc_data_model", "快照"): KnownViolation(
        copy="数据来自最近一次自动归档快照；逾期口径：审批中且申请日期滞留超过 7 天。",
        reason="同 ewo：schema 页面描述泄露内部归档术语「快照」。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/pages/tdc_data_model.json:4。",
    ),
    ("deliverable-forms/tdc_sor", "快照"): KnownViolation(
        copy="数据来自最近一次自动归档快照；逾期口径：审批中且申请日期滞留超过 7 天。",
        reason="同 ewo：schema 页面描述泄露内部归档术语「快照」。",
        follow_up="建议改为「最近一次自动归档的数据」；需改 plugins/deliverable_forms/static/pages/tdc_sor.json:4。",
    ),
    ("project-overview/details", "快照"): KnownViolation(
        copy="手工字段只读：外部快照驱动，状态由归档快照自动映射",
        reason="交付物明细的只读提示把「外部快照驱动」暴露给用户；文案来自后端常量，源级门禁扫不到。",
        follow_up="建议改为「该交付物的状态由外部系统同步结果自动维护」；需改 core/project_status_contracts.py:236。",
    ),
    ("project-overview/details", "取证"): KnownViolation(
        copy="待配置：缺统一域账号凭据、筛选条件、外部稳定键（在明细页完成映射取证）、自动更新的字段（在明细页完成映射取证）",
        reason="「映射取证」是内部配置流程术语，出现在交付物明细的待配置提示里；由插件后端拼装。",
        follow_up="建议改为「在明细页完成字段映射」；需改 plugins/project_overview/backend.py:126,128。",
    ),
    ("settings/general", "快照"): KnownViolation(
        copy="包含临时目录、诊断日志、单次请求重试与快照策略",
        reason="高级设置摘要出现「快照策略」，普通用户不知道「快照」指什么。",
        follow_up="建议改为「历史数据保留策略」；需改 plugins/settings/static/settings-form.js:197。",
    ),
    ("system-query/query", "Base URL"): KnownViolation(
        copy="请求上下文 · Base URL",
        reason="「Base URL」是技术字段名，直接作为查询页表单标签展示给用户。",
        follow_up="建议改为「服务地址」；需改 plugins/system_query/static/query.js:741。",
    ),
    ("workbench/tools", "Base URL"): KnownViolation(
        copy="开启后顶栏会多出原来的技术入口：概览、交付物工作台、系统查询（Base URL / XML）、表单、诊断录制等。",
        reason="专家模式说明里出现「Base URL / XML」，把内部技术入口直接写给普通用户看。",
        follow_up="建议改为「系统查询（服务地址 / 原始报文）」；需改 plugins/workbench/static/tools.js:38。",
    ),
}


# ── 浏览器取数：真实 DOM 文本 + aria-label / title ──────────────────────────

COLLECT_JS = r"""
(() => {
  const norm = (value) => String(value == null ? "" : value);
  const attributes = [];
  for (const element of document.querySelectorAll("[aria-label], [title]")) {
    const label = norm(element.getAttribute("aria-label")).trim();
    const title = norm(element.getAttribute("title")).trim();
    const tag = element.tagName.toLowerCase();
    if (label) attributes.push({ attr: "aria-label", value: label, tag });
    if (title) attributes.push({ attr: "title", value: title, tag });
  }
  const host = document.querySelector("#plugin-host");
  return {
    route: norm(document.body && document.body.dataset.routePlugin),
    title: norm(document.title),
    text: norm(document.body && document.body.innerText),
    hostText: host ? norm(host.innerText) : "",
    aria: attributes,
    loading: Boolean(document.querySelector(".vk-state.is-loading")),
    errorState: Boolean(document.querySelector(".vk-state.is-error")),
  };
})()
"""

HOST_CHROME_JS = r"""
(() => {
  const norm = (value) => String(value == null ? "" : value);
  const chrome = document.querySelector("#host-chrome");
  const attributes = [];
  for (const element of document.querySelectorAll("#host-chrome [aria-label], #host-chrome [title]")) {
    const label = norm(element.getAttribute("aria-label")).trim();
    const title = norm(element.getAttribute("title")).trim();
    const tag = element.tagName.toLowerCase();
    if (label) attributes.push({ attr: "aria-label", value: label, tag });
    if (title) attributes.push({ attr: "title", value: title, tag });
  }
  const nav = Array.from(document.querySelectorAll("#hc-top-bar nav.hc-nav a[data-plugin-link]"))
    .map((link) => norm(link.textContent).trim())
    .filter(Boolean);
  return { nav, text: chrome ? norm(chrome.innerText) : "", aria: attributes };
})()
"""

#: 页面主内容就绪：有渲染结果、且没有通用加载块。
PAGE_READY_JS = r"""
(() => {
  const host = document.querySelector("#plugin-host");
  if (!host || !host.firstElementChild) return false;
  return !host.querySelector(".vk-state.is-loading");
})()
"""


@dataclass(frozen=True)
class DomHit:
    """一次真实渲染里的禁词命中。"""

    page_key: str
    term: str
    source: str
    match: str
    context: str

    def describe(self) -> str:
        if self.term in ("盘符路径", ".py 后缀"):
            # 路径类命中可能带内网地址：只露前 6 字符，和 test_glossary_terms 口径一致。
            return (
                f"{self.page_key} 发现未登记禁词 [{self.term}] 来源={self.source} "
                f"匹配内容前 6 字符: {self.match[:6]!r}…（完整内容已脱敏）"
            )
        return f"{self.page_key} 发现未登记禁词 [{self.term}] 来源={self.source} 上下文: {self.context!r}"


def _context_around(text: str, match: str, limit: int = 60) -> str:
    index = text.find(match) if match else -1
    if index < 0:
        index = 0
    snippet = text[max(0, index - limit // 2): index + max(len(match), limit // 2)]
    return " ".join(snippet.split())


def scan_rendered_payload(page_key: str, payload: dict) -> list[DomHit]:
    """扫描一份渲染结果：可见文本、document.title 与所有 aria-label / title。"""
    hits: list[DomHit] = []
    seen: set[tuple[str, str, str]] = set()

    def collect(text: str, source: str) -> None:
        for term, match in scan_text_segment(text):
            marker = (term, source)
            if marker in seen:
                continue
            seen.add(marker)
            hits.append(DomHit(page_key, term, source, match, _context_around(text, match)))

    collect(str(payload.get("text") or ""), "innerText")
    collect(str(payload.get("title") or ""), "document.title")
    for item in payload.get("aria") or []:
        value = str(item.get("value") or "")
        collect(value, f"{item.get('attr') or 'attr'}@{item.get('tag') or 'node'}")
    return hits


def _render_and_collect(browser_page: BrowserPage, live: LiveServer, target: DomPage) -> dict:
    """打开页面并等到主内容就绪，返回真实 DOM 取数结果。"""
    browser_page.goto(live.route_url(target.hash_route))
    browser_page.wait_for_function(
        f"document.body.dataset.routePlugin === {json.dumps(target.plugin)}",
        timeout_ms=20_000,
    )
    browser_page.wait_for_function(PAGE_READY_JS, timeout_ms=20_000)
    if target.ready_selector:
        browser_page.wait_for_selector(target.ready_selector, timeout_ms=30_000)
    if target.settle_ms:
        time.sleep(target.settle_ms / 1000.0)
    return browser_page.eval(COLLECT_JS)


def _declared_pages() -> dict[str, str]:
    """源级：读各插件 plugin.json 的 pages 声明（路由键 → 标题）。

    只用于清单一致性，**不是** DOM 行为验收。
    """
    declared: dict[str, str] = {}
    for manifest in sorted(REPO_ROOT.glob("plugins/*/plugin.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        plugin_id = str(data.get("id") or manifest.parent.name)
        for item in data.get("pages") or []:
            declared[f"{plugin_id}/{item['id']}"] = str(item.get("title") or "")
    return declared


# ── 门禁 ────────────────────────────────────────────────────────────────────


def test_declared_pages_are_covered_or_explicitly_uncovered() -> None:
    """源级清单一致性（不冒充 DOM 验收）：声明页面必须被验收或写明未覆盖原因。"""
    declared = _declared_pages()
    covered = {target.key for target in DOM_PAGES}
    assert len(covered) == len(DOM_PAGES), "DOM_PAGES 存在重复页面"
    assert not (covered & set(UNCOVERED_PAGES)), "同一页面不能既被验收又登记未覆盖"

    missing = sorted(set(declared) - covered - set(UNCOVERED_PAGES))
    assert not missing, (
        "以下 plugin.json 声明页面既没有 DOM 验收，也没有未覆盖原因：\n"
        + "\n".join(f"  - {key}" for key in missing)
    )
    unknown = sorted((covered | set(UNCOVERED_PAGES)) - set(declared))
    assert not unknown, (
        "以下页面在本文件里被验收/登记，但 plugin.json 已不再声明（清单过期）：\n"
        + "\n".join(f"  - {key}" for key in unknown)
    )
    assert all(reason.strip() for reason in UNCOVERED_PAGES.values())

    # 契约点名的页面必须真的在 DOM 验收集合里。
    assert CONTRACT_REQUIRED_PAGES <= covered, (
        "主控契约点名的页面未进入 DOM 验收：" f"{sorted(CONTRACT_REQUIRED_PAGES - covered)}"
    )

    # 状态级未覆盖清单：每条都要有原因，且页面必须已被 DOM 验收（通配页按前缀校验）。
    for item in UNCOVERED_STATES:
        assert item.state.strip() and item.reason.strip(), f"未覆盖状态缺少说明：{item.state}"
        if not item.page_key:
            continue
        if item.page_key.endswith("/*"):
            prefix = item.page_key[:-1]
            assert any(key.startswith(prefix) for key in covered), item.page_key
        else:
            assert item.page_key in covered, f"未覆盖状态指向的页面不在 DOM 验收清单：{item.page_key}"


def test_whitelist_budget_does_not_grow() -> None:
    """白名单预算：DOM 白名单 + KNOWN_VIOLATIONS ≤ 任务开始时的既有白名单项数。"""
    assert DOM_WHITELIST == {}, "本任务不新增 DOM 白名单；新命中只能登记到 KNOWN_VIOLATIONS"
    total = len(DOM_WHITELIST) + len(KNOWN_VIOLATIONS)
    assert total <= BASELINE_WHITELIST_ENTRIES, (
        f"白名单与已知项合计 {total} 超过基线 {BASELINE_WHITELIST_ENTRIES}："
        "不得用登记表掩盖新回归"
    )
    covered = {target.key for target in DOM_PAGES}
    for (page_key, term), item in KNOWN_VIOLATIONS.items():
        assert page_key in covered, f"KNOWN_VIOLATIONS 指向未验收页面：{page_key}"
        assert term.strip() and item.copy.strip(), f"KNOWN_VIOLATIONS 缺少文案：{page_key}/{term}"
        assert item.reason.strip(), f"KNOWN_VIOLATIONS 缺少理由：{page_key}/{term}"
        assert item.follow_up.strip(), f"KNOWN_VIOLATIONS 缺少后续建议：{page_key}/{term}"


def test_scan_rendered_payload_reads_text_and_attributes() -> None:
    """扫描器自检（非 DOM 验收）：innerText、document.title、aria-label、title 都要覆盖。"""
    payload = {
        "text": "普通文案，含一个 快照 字样",
        "title": "普通标题",
        "aria": [
            {"attr": "aria-label", "value": "这里含 JSON 字样", "tag": "div"},
            {"attr": "title", "value": "例如：D:\\VSE\\archive 归档目录", "tag": "tr"},
        ],
    }
    hits = scan_rendered_payload("demo/page", payload)
    found = {(hit.term, hit.source) for hit in hits}
    assert ("快照", "innerText") in found
    assert ("JSON", "aria-label@div") in found
    assert ("盘符路径", "title@tr") in found
    # 路径类命中的断言消息必须脱敏（只露前 6 字符）。
    path_hit = next(hit for hit in hits if hit.term == "盘符路径")
    assert path_hit.match.startswith("D:\\VSE")
    assert "D:\\VSE" in path_hit.context
    assert repr(path_hit.match[:6]) in path_hit.describe()
    assert path_hit.match not in path_hit.describe()


def test_host_shell_visible_text_and_aria(server: LiveServer, page: BrowserPage) -> None:  # noqa: F811
    """宿主外壳：顶栏导航、版本与会话 aria 标签真实渲染，且外壳文案无禁词。"""
    page.goto(server.launch_url)
    page.wait_for_selector("#hc-top-bar nav.hc-nav a[data-plugin-link]")

    payload = page.eval(HOST_CHROME_JS)
    nav = [str(item) for item in payload.get("nav") or []]
    assert {"今天", "项目", "报告", "工具"} <= set(nav), page.diagnose(f"顶栏导航异常：{nav}")
    assert len(nav) >= 5, page.diagnose(f"顶栏导航条目过少：{nav}")

    labels = [str(item.get("value") or "") for item in payload.get("aria") or []]
    assert labels, page.diagnose("宿主外壳没有渲染任何 aria-label/title")
    assert any("应用版本" in value for value in labels), page.diagnose(f"缺少版本 aria 标签：{labels}")
    assert any("企业会话" in value for value in labels), page.diagnose(f"缺少会话 aria 标签：{labels}")

    hits = scan_rendered_payload("host/chrome", payload)
    assert not hits, "宿主外壳可见文案/aria 出现未登记禁词：\n" + "\n".join(
        f"  - {hit.describe()}" for hit in hits
    )


@pytest.mark.parametrize("group", DOM_GROUP_ORDER)
def test_dom_visible_text_and_aria_gate(
    group: str,
    server: LiveServer,  # noqa: F811 - fixture
    page: BrowserPage,  # noqa: F811 - fixture
) -> None:
    """真实 DOM 门禁：按分组渲染页面，检查 innerText 与全部 aria-label/title。"""
    targets = [target for target in DOM_PAGES if target.group == group]
    assert targets, f"未知分组：{group}"

    problems: list[str] = []
    observed: set[tuple[str, str]] = set()
    rendered: list[str] = []

    for target in targets:
        payload = _render_and_collect(page, server, target)
        assert payload.get("route") == target.plugin, page.diagnose(
            f"{target.key} 未挂到插件路由（route={payload.get('route')!r}）"
        )
        assert payload.get("hostText", "").strip(), page.diagnose(f"{target.key} 主内容为空")
        assert not payload.get("errorState"), page.diagnose(
            f"{target.key} 渲染成通用错误卡片，页面文案不可验收"
        )
        assert payload.get("aria"), page.diagnose(f"{target.key} 没有可验收的 aria-label/title")

        hits = scan_rendered_payload(target.key, payload)
        for hit in hits:
            observed.add((target.key, hit.term))
            if (target.key, hit.term) in DOM_WHITELIST or (target.key, hit.term) in KNOWN_VIOLATIONS:
                continue
            problems.append(hit.describe())
        rendered.append(
            f"{target.key}（innerText {len(payload.get('text') or '')} 字，"
            f"aria/title {len(payload.get('aria') or [])} 条）"
        )

    assert not problems, (
        f"分组 {group} 的真实 DOM 出现未登记禁词（新增命中只能修文案，不得放宽规则）：\n"
        + "\n".join(f"  - {item}" for item in problems)
        + "\n已验收页面：" + "、".join(rendered)
    )

    # 已登记的白名单/已知项必须仍然命中：修好文案后要删登记，不能长期掩盖回归。
    group_keys = {target.key for target in targets}
    stale = sorted(
        key
        for key in (set(DOM_WHITELIST) | set(KNOWN_VIOLATIONS))
        if key[0] in group_keys and key not in observed
    )
    assert not stale, (
        f"分组 {group} 的已登记条目已不再命中，请删除对应登记：\n"
        + "\n".join(f"  - {page_key} -> [{term}]" for page_key, term in stale)
    )
