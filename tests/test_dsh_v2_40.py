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
   每条显式标注对应的源级基线条目 ``baseline_entry`` 或 ``None``。预算 =
   基线有效条目数（任务开始时 23 项，删除 2 项过期及 index.js 已修正条目后 20 项）
   + 无基线对应的 DOM 已知违规数 + DOM 白名单，必须 ≤ ``BASELINE_WHITELIST_ENTRIES``
   （任务开始时 ``tests/golden/glossary_baseline.json`` 的 23 项）。同一处违规
   在源级与 DOM 各出现一次只算一项，不重复计数。既有源级白名单逐项审计
   在 ``tests/test_glossary_terms.py`` 的 ``BASELINE_AUDIT``。
6. **不改产品**：本文件只登记违规，不修文案；文件/行与建议见最终报告。
"""

from __future__ import annotations

import json
import re
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
    BASELINE_EFFECTIVE_ENTRIES,
    BASELINE_FILE,
    BASELINE_WHITELIST_ENTRIES,
    REPO_ROOT,
    scan_text_segment,
    scan_text_segment_occurrences,
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
#: 与 tests/test_glossary_terms.py::BASELINE_AUDIT（删除 2 项过期及 index.js 已修正条目后 20 项逐项有理由）。
DOM_WHITELIST: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class KnownViolation:
    """真实渲染出来的文案违规：不改产品，只登记并给出后续建议。

    ``baseline_entry`` 指向 ``tests/golden/glossary_baseline.json`` 中已覆盖同一
    文案/短语的 (文件, 术语) 条目；``None`` 表示源级基线没有对应项，属于纯 DOM
    新违规，计入预算的 DOM-only 部分。同一个源级违规在 DOM 再出现一次时只算一项。
    """

    copy: str
    baseline_entry: tuple[str, str] | None
    reason: str
    follow_up: str
    #: 同一 (页面, 术语) 下其他已登记的真实文案；每条都必须仍出现在 DOM 中。
    #: 同一术语的多个合法位置必须逐条登记，不能因为同词就整页放行。
    extra_copies: tuple[str, ...] = ()

    @property
    def copies(self) -> tuple[str, ...]:
        return (self.copy, *self.extra_copies)


#: 实测到的真实文案违规（页面键, 术语）→ 登记。登记文案必须仍然实际出现在该页
#: DOM 文本中（规范化空白后比对），否则门禁失败要求删除，防止「登记了却早已修好」
#: 的条目长期掩盖回归。
#:
#: baseline_entry 口径：
#: - deliverable_forms 首页与 6 个 schema 页的「自动归档快照」、details 的「映射取证」
#:   已由主控在产品文案中修正（DSH-V2-40 主控补丁），不再登记；
#: - details 的「外部快照驱动…」由后端常量拼装，源级 .js 基线没有同一句，标 None；
#: - 其余页面直接引用同文件同术语的源级基线条目。
KNOWN_VIOLATIONS: dict[tuple[str, str], KnownViolation] = {
    ("project-overview/details", "快照"): KnownViolation(
        copy="手工字段只读：外部快照驱动，状态由归档快照自动映射",
        baseline_entry=None,
        reason="交付物明细的只读提示把「外部快照驱动」暴露给用户；文案来自后端常量，源级门禁扫不到。",
        follow_up="建议改为「该交付物的状态由外部系统同步结果自动维护」；需改 core/project_status_contracts.py:236。",
        # 同页「外部来源交付物（参考）」区块的两处真实文案（external.js），
        # 与上面的后端常量文案不是同一句，必须逐条登记，不能因同词整页放行。
        extra_copies=(
            "快照仅参考，不计入完成统计",
            "查看同步快照",
        ),
    ),
    ("settings/general", "快照"): KnownViolation(
        copy="包含临时目录、诊断日志、单次请求重试与快照策略",
        baseline_entry=("plugins/settings/static/settings-form.js", "快照"),
        reason="高级设置摘要出现「快照策略」，普通用户不知道「快照」指什么。",
        follow_up="建议改为「历史数据保留策略」；需改 plugins/settings/static/settings-form.js:197。",
    ),
    ("system-query/query", "Base URL"): KnownViolation(
        # 实际 innerText 是区块标题「请求上下文」+ 标签「Base URL」，中间是换行，
        # 规范化空白后为单个空格；源码里的「·」不会渲染到 DOM。
        copy="请求上下文 Base URL",
        baseline_entry=("plugins/system_query/static/query.js", "Base URL"),
        reason="「Base URL」是技术字段名，直接作为查询页表单标签展示给用户。",
        follow_up="建议改为「服务地址」；需改 plugins/system_query/static/query.js:741。",
    ),
    ("workbench/tools", "Base URL"): KnownViolation(
        copy="开启后顶栏会多出原来的技术入口：概览、交付物工作台、系统查询（Base URL / XML）、表单、诊断录制等。",
        baseline_entry=("plugins/workbench/static/tools.js", "Base URL"),
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
    hash: norm(window.location.hash),
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
    """一次真实渲染里的禁词命中（每次出现一条，不按术语去重）。"""

    page_key: str
    term: str
    source: str
    match: str
    context: str
    start: int
    segment_index: int

    def describe(self) -> str:
        if self.term in ("盘符路径", ".py 后缀"):
            # 路径类命中可能带内网地址：只露前 6 字符，和 test_glossary_terms 口径一致。
            return (
                f"{self.page_key} 发现未登记禁词 [{self.term}] 来源={self.source} "
                f"匹配内容前 6 字符: {self.match[:6]!r}…（完整内容已脱敏）"
            )
        return f"{self.page_key} 发现未登记禁词 [{self.term}] 来源={self.source} 上下文: {self.context!r}"


def _context_around(text: str, match: str, start: int, limit: int = 60) -> str:
    index = start if 0 <= start < len(text) else (text.find(match) if match else -1)
    if index < 0:
        index = 0
    snippet = text[max(0, index - limit // 2): index + max(len(match), limit // 2)]
    return " ".join(snippet.split())


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_visible_text(text: str) -> str:
    """把可见文本的空白折叠成单个空格并去掉首尾，用于登记文案的比对。"""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _normalize_with_index_map(text: str) -> tuple[str, list[int]]:
    """折叠空白，同时记录每个规范化字符在原文中的下标。

    规范化后的空格映射到原空白串的首字符；登记文案首尾无空白，因此命中区间
    仍能准确落回原文。
    """
    normalized: list[str] = []
    index_map: list[int] = []
    pending_space_at: int | None = None
    started = False
    for index, char in enumerate(text):
        if char.isspace():
            if started and pending_space_at is None:
                pending_space_at = index
            continue
        if pending_space_at is not None:
            normalized.append(" ")
            index_map.append(pending_space_at)
            pending_space_at = None
        normalized.append(char)
        index_map.append(index)
        started = True
    return "".join(normalized), index_map


def _payload_segments(payload: dict) -> list[tuple[str, str]]:
    """按扫描来源拆分 payload；列表下标即 ``DomHit.segment_index``。"""
    segments: list[tuple[str, str]] = [
        ("innerText", str(payload.get("text") or "")),
        ("document.title", str(payload.get("title") or "")),
    ]
    for item in payload.get("aria") or []:
        segments.append(
            (
                f"{item.get('attr') or 'attr'}@{item.get('tag') or 'node'}",
                str(item.get("value") or ""),
            )
        )
    return segments


def _registered_copy_spans(payload: dict, copy: str) -> dict[int, list[tuple[int, int]]]:
    """返回登记文案在各来源中的原文区间（规范化空白后定位，避免换行导致误判）。"""
    copy_norm = normalize_visible_text(copy)
    spans: dict[int, list[tuple[int, int]]] = {}
    if not copy_norm:
        return spans
    for segment_index, (_source, text) in enumerate(_payload_segments(payload)):
        normalized, index_map = _normalize_with_index_map(text)
        start = normalized.find(copy_norm)
        while start >= 0:
            raw_start = index_map[start]
            raw_end = index_map[start + len(copy_norm) - 1] + 1
            spans.setdefault(segment_index, []).append((raw_start, raw_end))
            start = normalized.find(copy_norm, start + 1)
    return spans


def _hit_is_registered_copy(hit: DomHit, spans: dict[int, list[tuple[int, int]]]) -> bool:
    """命中的起始位置必须落在同来源的一条登记文案区间内。"""
    for start, end in spans.get(hit.segment_index, []):
        if start <= hit.start and hit.start + len(hit.match) <= end:
            return True
    return False


def scan_rendered_payload(page_key: str, payload: dict) -> list[DomHit]:
    """扫描一份渲染结果：可见文本、document.title 与所有 aria-label / title。

    不去重：同一术语出现几次就返回几个 ``DomHit``，并带原文起始下标与来源下标，
    以便门禁区分「登记文案内」与「同词其他位置」。
    """
    hits: list[DomHit] = []
    for segment_index, (source, text) in enumerate(_payload_segments(payload)):
        for term, match, start in scan_text_segment_occurrences(text):
            hits.append(
                DomHit(
                    page_key=page_key,
                    term=term,
                    source=source,
                    match=match,
                    context=_context_around(text, match, start),
                    start=start,
                    segment_index=segment_index,
                )
            )
    return hits


def audit_rendered_page(
    page_key: str, payload: dict
) -> tuple[list[str], set[tuple[str, str]], list[tuple[str, str, str]]]:
    """审计一个页面的渲染结果。

    返回 ``(problems, observed, stale)``：

    - ``problems``：未登记命中，或同词但落在登记文案之外的命中；
    - ``observed``：本页实际命中的 (页面, 术语)，用于 DOM_WHITELIST 过期检查；
    - ``stale``：某条登记文案已不在本页 DOM 文本中，元素为
      ``(页面, 术语, 消失的文案)``，需要删除/更新对应 KNOWN_VIOLATIONS。

    只有命中的起始位置落在该页一条已登记 ``copy`` 的原文区间内才放行；同词其他
    位置的命中一律失败。同一 (页面, 术语) 可以登记多条 ``copies``，但每条都必须
    仍实际出现，避免用一条登记掩盖整页同词。
    """
    hits = scan_rendered_payload(page_key, payload)
    observed = {(page_key, hit.term) for hit in hits}

    copy_spans: dict[tuple[str, str], dict[int, list[tuple[int, int]]]] = {}
    stale: list[tuple[str, str, str]] = []
    for key, item in KNOWN_VIOLATIONS.items():
        if key[0] != page_key:
            continue
        merged: dict[int, list[tuple[int, int]]] = {}
        for copy in item.copies:
            spans = _registered_copy_spans(payload, copy)
            if not spans:
                stale.append((key[0], key[1], copy))
                continue
            for segment_index, ranges in spans.items():
                merged.setdefault(segment_index, []).extend(ranges)
        if merged:
            copy_spans[key] = merged

    problems: list[str] = []
    for hit in hits:
        key = (page_key, hit.term)
        if key in DOM_WHITELIST:
            continue
        spans = copy_spans.get(key)
        if spans is not None and _hit_is_registered_copy(hit, spans):
            continue
        problems.append(hit.describe())
    return problems, observed, stale


def _render_and_collect(browser_page: BrowserPage, live: LiveServer, target: DomPage) -> dict:
    """打开页面并等到主内容就绪，返回真实 DOM 取数结果。"""
    browser_page.goto(live.route_url(target.hash_route))
    browser_page.wait_for_function(
        f"document.body.dataset.routePlugin === {json.dumps(target.plugin)}",
        timeout_ms=20_000,
    )
    # 只校验插件会放过「同插件错页」；这里等到具体页面 ID（hash 路由）也落定。
    browser_page.wait_for_function(
        f"window.location.hash === {json.dumps(target.hash_route)}",
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


def _baseline_entries() -> set[tuple[str, str]]:
    baseline_data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    return {(file_rel, term) for file_rel, terms in baseline_data.items() for term in terms}


def test_whitelist_budget_does_not_grow() -> None:
    """白名单预算：基线有效项 + 无基线对应的 DOM 已知违规 + DOM 白名单 ≤ 23。

    口径（主控裁决）：同一处违规在源级基线与 DOM 各出现一次只算一项。
    ``baseline_entry`` 指向已在基线登记的同一文案/短语；``None`` 才是纯 DOM 新违规。
    """
    assert DOM_WHITELIST == {}, "本任务不新增 DOM 白名单；新命中只能登记到 KNOWN_VIOLATIONS"

    baseline_entries = _baseline_entries()
    assert len(baseline_entries) == BASELINE_EFFECTIVE_ENTRIES, (
        f"基线有效条目应为 {BASELINE_EFFECTIVE_ENTRIES} 项（任务开始时 "
        f"{BASELINE_WHITELIST_ENTRIES} 项，删除 2 项过期及 index.js 已修正条目后），实测 {len(baseline_entries)} 项"
    )

    covered = {target.key for target in DOM_PAGES}
    dom_only: list[tuple[str, str]] = []
    for (page_key, term), item in KNOWN_VIOLATIONS.items():
        assert page_key in covered, f"KNOWN_VIOLATIONS 指向未验收页面：{page_key}"
        assert term.strip() and item.copy.strip(), f"KNOWN_VIOLATIONS 缺少文案：{page_key}/{term}"
        assert item.reason.strip(), f"KNOWN_VIOLATIONS 缺少理由：{page_key}/{term}"
        assert item.follow_up.strip(), f"KNOWN_VIOLATIONS 缺少后续建议：{page_key}/{term}"
        assert any(
            hit_term == term for hit_term, _match in scan_text_segment(item.copy)
        ), f"KNOWN_VIOLATIONS 的登记文案不含术语 {term}：{page_key}"

        if item.baseline_entry is None:
            dom_only.append((page_key, term))
            continue
        assert item.baseline_entry in baseline_entries, (
            f"KNOWN_VIOLATIONS 引用了不存在的基线条目："
            f"{page_key}/{term} -> {item.baseline_entry}"
        )
        assert item.baseline_entry[1] == term, (
            f"KNOWN_VIOLATIONS 的基线条目术语不一致："
            f"{page_key}/{term} -> {item.baseline_entry}"
        )

    total = len(baseline_entries) + len(dom_only) + len(DOM_WHITELIST)
    assert total <= BASELINE_WHITELIST_ENTRIES, (
        f"白名单预算 {total} 超过任务开始基线 {BASELINE_WHITELIST_ENTRIES}："
        f"基线有效 {len(baseline_entries)} + 无基线 DOM {len(dom_only)} {dom_only}"
        f" + DOM 白名单 {len(DOM_WHITELIST)}"
    )


def _format_stale_registrations(items: list[tuple[str, str, str]]) -> str:
    """把过期登记格式化成失败信息；元素是 ``(页面, 术语, 消失的文案)``。"""
    return "\n".join(
        f"  - {page_key} -> [{term}] 登记文案: {copy!r}"
        for page_key, term, copy in items
    )


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

    # 每一次出现都要收集：同词两次 = 两个 DomHit（不能按 (term, source) 去重）。
    repeated = scan_rendered_payload("demo/page", {"text": "快照与快照", "aria": []})
    repeated_hits = [hit for hit in repeated if hit.term == "快照"]
    assert len(repeated_hits) == 2
    assert [hit.start for hit in repeated_hits] == [0, 3]


def test_known_violation_requires_registered_copy_not_just_term() -> None:
    """已登记页面：仅登记文案放行；同词不同文案失败；登记文案消失报过期。"""
    page_key = "settings/general"
    term = "快照"
    copy = KNOWN_VIOLATIONS[(page_key, term)].copy

    # 1) 只有登记文案：放行。
    problems, observed, stale = audit_rendered_page(
        page_key, {"text": copy, "title": "", "aria": []}
    )
    assert not problems
    assert not stale
    assert (page_key, term) in observed

    # 2) 登记文案仍在，但页面另一处新增同词不同文案：必须失败。
    problems, _observed, stale = audit_rendered_page(
        page_key,
        {
            "text": copy + "\n另一处说明：这里也提到了快照，但不在登记文案内。",
            "title": "",
            "aria": [],
        },
    )
    assert not stale
    assert len(problems) == 1
    assert "另一处说明" in problems[0]

    # 3) 登记文案消失（同词出现在别的文案里）：必须报过期，且不能放行同词命中。
    problems, _observed, stale = audit_rendered_page(
        page_key,
        {"text": "页面改版后只剩一句提到快照的新文案。", "title": "", "aria": []},
    )
    assert (page_key, term, copy) in stale
    assert problems, "同词其他位置的命中不应被登记放行"


def test_known_violation_copy_scope_is_per_source() -> None:
    """登记文案在 innerText，不代表 aria-label 里的同词可以放行。"""
    page_key = "settings/general"
    term = "快照"
    copy = KNOWN_VIOLATIONS[(page_key, term)].copy

    problems, _observed, stale = audit_rendered_page(
        page_key,
        {
            "text": copy,
            "title": "",
            "aria": [{"attr": "aria-label", "value": "快照按钮", "tag": "button"}],
        },
    )
    assert not stale
    assert len(problems) == 1
    assert "aria-label@button" in problems[0]


def test_known_violation_copy_matches_across_whitespace() -> None:
    """登记文案与 DOM 文本的换行/缩进差异应被规范化空白吸收。

    取一条**本身含空格**的登记文案（``system-query/query`` 的「请求上下文 Base URL」），
    把该空格换成换行 + 缩进：规范化后仍是一个空格，应放行。不能在原本没有空白的
    两个字符之间插入空白——那会改变规范化后的文本，不属于「空白差异」。
    """
    page_key = "system-query/query"
    term = "Base URL"
    copy = KNOWN_VIOLATIONS[(page_key, term)].copy
    assert " " in copy, "本自测需要一条含空格的登记文案"
    reflowed = copy.replace(" ", "\n    ")

    problems, _observed, stale = audit_rendered_page(
        page_key, {"text": reflowed, "title": "", "aria": []}
    )
    assert not problems
    assert not stale


def test_stale_registration_message_keeps_copy() -> None:
    """过期失败信息必须带上消失的文案（3 元组解包的回归保护）。"""
    message = _format_stale_registrations([("demo/page", "快照", "旧文案")])
    assert "demo/page" in message
    assert "快照" in message
    assert "旧文案" in message


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
    stale_registrations: list[tuple[str, str, str]] = []
    rendered: list[str] = []

    for target in targets:
        payload = _render_and_collect(page, server, target)
        assert payload.get("route") == target.plugin, page.diagnose(
            f"{target.key} 未挂到插件路由（route={payload.get('route')!r}）"
        )
        # 只校验插件会放过「同插件错页」：必须确认停在目标页面 ID（hash 路由）。
        assert payload.get("hash") == target.hash_route, page.diagnose(
            f"{target.key} 实际停在 {payload.get('hash')!r}，页面 ID 与目标不一致"
        )
        assert payload.get("hostText", "").strip(), page.diagnose(f"{target.key} 主内容为空")
        assert not payload.get("errorState"), page.diagnose(
            f"{target.key} 渲染成通用错误卡片，页面文案不可验收"
        )
        assert payload.get("aria"), page.diagnose(f"{target.key} 没有可验收的 aria-label/title")

        page_problems, page_observed, page_stale = audit_rendered_page(target.key, payload)
        problems.extend(page_problems)
        observed |= page_observed
        stale_registrations.extend(page_stale)
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
    # KNOWN_VIOLATIONS 的过期口径是「登记文案不再实际出现」，而不是「术语不再命中」；
    # 后者会掩盖「文案已改、同词仍在别处」的情况。
    group_keys = {target.key for target in targets}
    stale_whitelist = sorted(
        key
        for key in DOM_WHITELIST
        if key[0] in group_keys and key not in observed
    )
    stale_known = sorted(stale_registrations)
    assert not stale_known, (
        f"分组 {group} 的已登记违规文案已不在页面 DOM 文本中，请删除对应 KNOWN_VIOLATIONS：\n"
        + _format_stale_registrations(stale_known)
    )
    assert not stale_whitelist, (
        f"分组 {group} 的 DOM 白名单已不再命中，请删除对应登记：\n"
        + "\n".join(f"  - {page_key} -> [{term}]" for page_key, term in stale_whitelist)
    )
