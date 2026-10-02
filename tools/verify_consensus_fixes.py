# -*- coding: utf-8 -*-
"""Spot checks for the consensus fix round (M8/N3/M1/M2 regressions)."""

import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions

THEME_KEY = "vse-toolbox-theme"
BASE = "http://127.0.0.1:5000"


def make_driver(width=1440, height=1000):
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


def main():
    results = {}

    # ── M8：多选变更后未提交的关键词应保留 ──
    d = make_driver()
    try:
        open_dark(d, f"{BASE}/#deliverable/VPI-T2-D2")
        keyword = d.find_element(By.CSS_SELECTOR, ".form-filter-keyword")
        keyword.clear()
        keyword.send_keys("审计保留关键字")
        # 打开状态多选下拉并点击第一个选项（触发即改即生效 + 重绘）
        ms_input = d.find_element(By.CSS_SELECTOR, ".analysis-multi-select-input")
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", ms_input)
        d.execute_script("arguments[0].click();", ms_input)
        time.sleep(0.4)
        option = d.find_element(By.CSS_SELECTOR, ".analysis-multi-select-option")
        d.execute_script("arguments[0].click();", option)
        time.sleep(1.5)
        kept = d.execute_script(
            "const el = document.querySelector('.form-filter-keyword');"
            "return el ? el.value : null;"
        )
        results["M8 重绘后关键词保留"] = kept
        results["M8 通过"] = kept == "审计保留关键字"
        d.save_screenshot(".runtime/fix_m8_keyword_kept.png")
    finally:
        d.quit()

    # ── 回归抽查：N3 默认值同步 + 目录精简未回归 ──
    d = make_driver()
    try:
        open_dark(d, f"{BASE}/#scheduled-archive")
        time.sleep(2)
        value = d.execute_script(
            "const input = document.querySelector("
            "'[data-archive-filter-name=\"projectCode\"]');"
            "return input ? input.value : null;"
        )
        results["N3回归 车型项目默认值"] = value
        open_dark(d, f"{BASE}/#deliverables")
        time.sleep(1)
        count = d.execute_script(
            "return document.querySelectorAll('.deliverable-item').length;"
        )
        results["M2回归 目录条目数"] = count
    finally:
        d.quit()

    for key, value in results.items():
        print(f"{key}: {value}")
    assert results["M8 通过"], "M8 未生效"
    assert results["N3回归 车型项目默认值"] == "F610S"
    assert results["M2回归 目录条目数"] == 6
    print("SPOT CHECK PASS")


if __name__ == "__main__":
    main()
