# -*- coding: utf-8 -*-
"""DSH-V2-08：真实浏览器关键路径（启动票据 / 向导 / 报告入口）。

运行::

    python -B -m pytest -p no:cacheprovider tests/browser/test_v2_user_paths.py -q -rs

这些用例跑在**真实浏览器**里：真实 ES Module、真实 DOM、真实鼠标点击与文本
输入（Edge/Chrome 无头 + CDP，Node 内置 WebSocket），不是源码文本断言。
夹具见 ``tests/browser/v2_fixtures.py``；环境要求与 release 门禁接线见
``docs/refactor-v2/DSH_BROWSER_SETUP.md``。

三条路径：

1. ``?boot=<票据>`` → 外壳 ES Module 加载完成、会话 Cookie 建立、顶部导航可见；
2. 首次使用向导：真实点击「开始 / 跳过登录 / 下一步」，断言 DOM 步骤变化；
3. 报告类入口：项目概览（``#p/project-overview/status``）与 3D 单签署日报
   （``#p/sign-daily/report``）渲染出关键元素。

每条用例都收集浏览器 console 的 error 级日志并断言为空；失败时断言消息里带
DOM 片段与 console 日志（``BrowserPage.diagnose``）。
"""

from __future__ import annotations

import re

from tests.browser.v2_fixtures import (  # noqa: F401 - pytest fixture 注入
    BrowserPage,
    LiveServer,
    assert_no_console_errors,
    browser,
    page,
    server,
)

#: 已列明的已知 console error（只放行这一条，别的 4xx/5xx 仍然失败）。
#: 单项目环境（非启动器托管）点「下一步」新建项目会如实返回 409 NotManaged，
#: 浏览器把 4xx 响应记为 network error。这是预期业务分支——而且证明写请求穿过
#: 了会话 + Origin 防线（不是 401/403），不是页面缺陷。
# DSH-V2-03 契约 §5.12-3：页面启动握手先 POST boot-claim 一次，无预置授权时 409
# 是正常路径（例如直接用浏览器打开、或旧启动器的 ?boot= 兼容分支），页面静默忽略，
# 但浏览器仍会把这次 409 记为网络 error 日志。只放行这一条精确匹配。
BOOT_CLAIM_PROBE = re.compile(
    r"status of 409 \(CONFLICT\) \(http://127\.0\.0\.1:\d+/api/security/boot-claim\)"
)

KNOWN_CONSOLE_ENTRIES = (
    re.compile(r"status of 409 \(CONFLICT\) \(http://127\.0\.0\.1:\d+/api/p/workbench/projects\)"),
    BOOT_CLAIM_PROBE,
)


# ── 路径 1：启动票据 → 会话 Cookie → 外壳与导航 ────────────────────────────


def test_boot_ticket_establishes_session_and_loads_shell(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    """带票据打开首页：ES Module 外壳加载、会话 Cookie 建立、导航可见。"""
    page.goto(server.launch_url)

    # 外壳 ES Module 链（shell.js → manifest → 插件页面模块）真的执行完了。
    page.wait_for_selector("#plugin-host .wb-page")
    page.wait_for_selector("#hc-top-bar nav.hc-nav a[data-plugin-link]")

    nav = page.eval(
        "Array.from(document.querySelectorAll('#hc-top-bar nav.hc-nav a[data-plugin-link]'))"
        ".map((link) => link.textContent.trim())"
    )
    assert "今天" in nav and "报告" in nav, page.diagnose(f"顶部导航未按 manifest 渲染：{nav}")

    # 启动票据换来的真实会话 Cookie：HttpOnly + SameSite=Strict，JS 读不到。
    cookies = page.cookies([server.base_url])
    session_cookies = [item for item in cookies if item.get("name") == "vse_session"]
    assert len(session_cookies) == 1, page.diagnose(f"会话 Cookie 数量异常：{cookies}")
    cookie = session_cookies[0]
    assert cookie.get("httpOnly") is True, page.diagnose(f"会话 Cookie 必须是 HttpOnly：{cookie}")
    assert cookie.get("sameSite") == "Strict", page.diagnose(f"会话 Cookie 必须 SameSite=Strict：{cookie}")
    document_cookie = str(page.eval("document.cookie"))
    assert "vse_session" not in document_cookie, page.diagnose("HttpOnly 会话不应被页面 JS 读到")

    # runBootExchange 用 replaceState 清理了地址栏里的票据。
    assert page.eval("location.search") == "", page.diagnose("地址栏票据未被 replaceState 清理")

    # 默认路由落到工作台「今天」页：等数据加载完成后待办区出现。
    assert page.eval("document.body.dataset.routePlugin") == "workbench", page.diagnose(
        "默认路由未落到 workbench"
    )
    page.wait_for_selector(".wb-todos")
    body_text = str(page.eval("document.querySelector('#plugin-host').innerText"))
    assert "需要你处理" in body_text, page.diagnose("工作台首页主体未渲染")

    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ── 路径 2：首次使用向导的真实点击 ─────────────────────────────────────────


def test_wizard_advances_through_real_clicks(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    """打开向导并用真实鼠标点击推进步骤，断言 DOM 中的步骤变化。"""
    page.goto(server.launch_url)
    page.wait_for_selector(".wb-modal")
    page.wait_for_selector(".wb-modal h1")

    welcome = page.eval("document.querySelector('.wb-modal h1').textContent.trim()")
    assert "欢迎使用 VSE Toolbox" in welcome, page.diagnose(f"向导首屏标题异常：{welcome}")

    # 第 0 步 → 第 1 步（统一登录）
    page.click(text="开始")
    page.wait_for_function(
        "Boolean(document.querySelector('.wb-modal h2'))"
        " && document.querySelector('.wb-modal h2').textContent.includes('登录公司域账号')"
    )

    # 第 1 步 → 第 2 步（新建项目）：跳过登录，不触碰任何外部系统。
    page.click(text="跳过登录")
    page.wait_for_function(
        "Boolean(document.querySelector('.wb-modal h2'))"
        " && document.querySelector('.wb-modal h2').textContent.includes('新建或配置项目')"
    )

    # 真实输入车型后点「下一步」（表单提交 → POST /api/p/workbench/projects）。
    page.type_text('input[placeholder="例如 F610S"]', "F610S")
    page.click(text="下一步")
    page.wait_for_function(
        "Boolean(document.querySelector('.wb-modal h2'))"
        " && document.querySelector('.wb-modal h2').textContent.includes('选择要跟踪的交付物')"
    )

    # 步骤条 4 个点亮（0..3），且向导状态已按契约持久化到 localStorage。
    lit_steps = page.eval("document.querySelectorAll('.wb-modal .wb-steps i.on').length")
    assert lit_steps == 4, page.diagnose(f"向导步骤条未前进到第 4 步：{lit_steps}")
    persisted_step = page.eval("JSON.parse(window.localStorage.getItem('vse.wizardState')).step")
    assert persisted_step == 3, page.diagnose(f"向导步进未持久化：{persisted_step}")

    assert_no_console_errors(page, allow=KNOWN_CONSOLE_ENTRIES)


# ── 路径 3：报告类入口渲染出关键元素 ───────────────────────────────────────


def test_project_overview_report_entry_renders(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    """项目概览（报告类入口之一）渲染真实数据：时间轴、当前节点、交付物环图。"""
    page.goto(server.route_url("#p/project-overview/status"))
    page.wait_for_selector("section.project-overview[aria-label='项目状态概览']")
    page.wait_for_selector(".overview-switch [role=tab]")
    page.wait_for_function("!document.querySelector('.project-overview .loading')")
    page.wait_for_selector(".project-overview article.progress-ring")

    assert page.eval("document.body.dataset.routePlugin") == "project-overview", page.diagnose(
        "插件路由未切到 project-overview"
    )
    tabs = page.eval(
        "Array.from(document.querySelectorAll('.overview-switch [role=tab]'))"
        ".map((tab) => tab.textContent.trim())"
    )
    assert tabs == ["项目状态", "交付物明细", "主计划维护"], page.diagnose(f"概览 tab 未渲染：{tabs}")

    phase_title = page.eval("document.querySelector('.milestone-timeline h4').textContent.trim()")
    # init_database 的默认阶段种子是 VPI-T2 / F610S（core/db_manager.py::_seed_project_status）。
    assert phase_title == "F610S", page.diagnose(f"主计划时间轴未渲染默认项目：{phase_title}")

    milestones = page.eval("document.querySelectorAll('.project-overview .milestone-node').length")
    rings = page.eval("document.querySelectorAll('.project-overview article.progress-ring').length")
    assert milestones >= 1, page.diagnose(f"主计划节点未渲染：{milestones}")
    assert rings >= 1, page.diagnose(f"交付物完成状态未渲染：{rings}")

    load_error = page.eval("Boolean(document.querySelector('.project-overview .overview-load-error'))")
    assert load_error is False, page.diagnose("项目概览出现加载失败区块")

    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


def test_sign_daily_report_entry_renders(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    """3D 单签署日报（报告类入口）渲染出标题与「一键生成」入口。"""
    page.goto(server.route_url("#p/sign-daily/report"))
    page.wait_for_selector(".sd-page")
    page.wait_for_selector(".sd-page h2")

    title = page.eval("document.querySelector('.sd-page h2').textContent.trim()")
    assert title == "3D 单签署日报", page.diagnose(f"日报页标题异常：{title}")
    assert page.eval("document.body.dataset.routePlugin") == "sign-daily", page.diagnose(
        "插件路由未切到 sign-daily"
    )

    main_button = page.eval(
        "(() => { const button = document.querySelector('.sd-main-btn');"
        " return button ? button.textContent.trim() : null; })()"
    )
    assert main_button and "一键生成" in str(main_button), page.diagnose(
        f"「一键生成」按钮未渲染：{main_button}"
    )

    page_error = page.eval("Boolean(document.querySelector('.sd-page .vk-state.is-error'))")
    assert page_error is False, page.diagnose("日报页加载即进入错误态")

    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))
