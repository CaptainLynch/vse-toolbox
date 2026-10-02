# -*- coding: utf-8 -*-
"""Deterministic verification of the 2026-09-06 five UI requests."""

import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions

THEME_KEY = "vse-toolbox-theme"


def make_driver(width=1440, height=1100):
    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument(f"--window-size={width},{height}")
    return webdriver.Edge(options=opts)


def open_dark(driver, url):
    driver.get("about:blank")
    driver.get(url)
    driver.execute_script(f"localStorage.setItem('{THEME_KEY}', 'dark');")
    driver.refresh()
    time.sleep(3.5)


def js_click(driver, selector):
    driver.execute_script(
        "arguments[0].click();", driver.find_element(By.CSS_SELECTOR, selector)
    )


def results_print(results):
    for key, value in results.items():
        print(f"{key}: {value}")


def main():
    results = {}

    # ── 需求①③：详情页折叠 + 无负责人 + 备注内联编辑 ──
    d = make_driver()
    try:
        open_dark(d, "http://127.0.0.1:5000/#deliverable/VPI-T2-D2")
        collapse = d.find_element(By.CSS_SELECTOR, ".detail-inline-collapse")
        results["①默认收起"] = collapse.is_displayed() and not d.execute_script(
            "return document.querySelector('.detail-inline-collapse').open;"
        )
        labels = d.execute_script(
            "return [...document.querySelectorAll("
            "'.detail-inline-collapse .detail-property-label')]"
            ".map((el) => el.textContent);"
        )
        results["③无负责人"] = "负责人" not in labels

        def note_value(dd):
            return dd.execute_script(
                "const el = [...document.querySelectorAll("
                "'.detail-inline-collapse .detail-property')]"
                ".find(c => c.querySelector('.detail-property-label')"
                ".textContent === '风险与备注');"
                "return el ? el.querySelector('.detail-property-value')"
                ".textContent.replace('✎ 编辑','').trim() : null;"
            )

        d.execute_script("document.querySelector('.detail-inline-collapse').open = true;")
        time.sleep(0.3)
        js_click(d, ".note-inline-edit")
        time.sleep(0.4)
        active = d.switch_to.active_element
        active.send_keys("内联编辑验证-键盘路径")
        active.send_keys("\ue007")
        time.sleep(1.5)
        results["③键盘路径保存"] = note_value(d)

        # JS 路径还原为原值"无"
        d.execute_script("document.querySelector('.detail-inline-collapse').open = true;")
        time.sleep(0.3)
        js_click(d, ".note-inline-edit")
        time.sleep(0.4)
        d.execute_script(
            "const input = document.querySelector('.note-inline-input');"
            "input.value = '无';"
            "input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));"
        )
        time.sleep(1.5)
        results["③还原为无"] = note_value(d)
        d.save_screenshot(".runtime/req123_done.png")
    finally:
        d.quit()

    # ── 需求②：1130 视口无溢出 ──
    d = make_driver(1130, 900)
    try:
        open_dark(d, "http://127.0.0.1:5000/#deliverable/VPI-T2-D2")
        overflow = d.execute_script(
            "const row = document.querySelector('.form-filter-row-dims');"
            "const sels = [...row.querySelectorAll('.analysis-multi-select')];"
            "const rowRight = row.getBoundingClientRect().right;"
            "return sels.map((s) => Math.round(s.getBoundingClientRect().right - rowRight));"
        )
        results["②最大溢出px"] = max(overflow)
    finally:
        d.quit()

    # ── 需求④：归档筛选统一名称 + 动态占位 ──
    d = make_driver()
    try:
        open_dark(d, "http://127.0.0.1:5000/#scheduled-archive")
        time.sleep(1.5)
        labels = d.execute_script(
            "return [...document.querySelectorAll('.archive-filter-field span')]"
            ".map((el) => el.textContent);"
        )
        placeholders = d.execute_script(
            "return [...document.querySelectorAll('[data-archive-filter-name]')]"
            ".filter((i) => ['projectCode','vehicleKeyword','projectModel',"
            "'carTypeProject'].includes(i.dataset.archiveFilterName))"
            ".map((i) => [i.dataset.archiveFilterName, i.placeholder]);"
        )
        results["④含旧称呼"] = any(
            ("项目代码" in label or "车辆关键词" in label) for label in labels
        )
        results["④占位符样例"] = placeholders[:2]
    finally:
        d.quit()

    # ── 需求⑤：主计划名称内联编辑（改名后还原） ──
    d = make_driver()
    try:
        open_dark(d, "http://127.0.0.1:5000/#overview")
        for tab in d.find_elements(By.TAG_NAME, "button"):
            if "主计划维护" in tab.text:
                tab.click()
                break
        time.sleep(1.2)

        def phase_name(dd):
            return dd.execute_script(
                "const el = [...document.querySelectorAll('.phase-meta-cell')]"
                ".find(c => c.querySelector('.phase-meta-label')?.textContent"
                " === '主计划名称');"
                "return el ? el.querySelector('.phase-meta-value')"
                ".textContent.replace('✎','').trim() : null;"
            )

        def js_rename(dd, name):
            if not dd.find_elements(By.CSS_SELECTOR, ".phase-name-inline-input"):
                js_click(dd, ".phase-name-inline-btn")
                time.sleep(0.4)
            dd.execute_script(
                "const input = document.querySelector('.phase-name-inline-input');"
                f"input.value = {name!r};"
                "input.dispatchEvent(new KeyboardEvent('keydown',"
                " {key: 'Enter', bubbles: true}));"
            )
            time.sleep(1.5)

        btn = d.find_element(By.CSS_SELECTOR, ".phase-name-inline-btn")
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        d.execute_script("arguments[0].click();", btn)
        time.sleep(0.4)
        results["⑤输入框出现"] = bool(
            d.find_elements(By.CSS_SELECTOR, ".phase-name-inline-input")
        )
        js_rename(d, "F610L")
        results["⑤改名生效"] = phase_name(d)
        js_rename(d, "F610S")
        results["⑤还原"] = phase_name(d)
    finally:
        d.quit()

    results_print(results)


if __name__ == "__main__":
    main()
