# -*- coding: utf-8 -*-
"""Live verification of the 2026-09-07 three UI requests."""

import time

from selenium import webdriver
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

    # ── 需求1：明细表无负责人表头，表头/数据对齐 ──
    d = make_driver()
    try:
        open_dark(d, f"{BASE}/#overview")
        d.execute_script(
            "for (const t of document.querySelectorAll('button'))"
            "{ if (t.textContent.includes('交付物明细')) { t.click(); break; } }"
        )
        time.sleep(1)
        headers = d.execute_script(
            "return [...document.querySelectorAll("
            "'.overview-details-table thead th')].map((th) => th.textContent.trim());"
        )
        first_row = d.execute_script(
            "const row = document.querySelector('.deliverable-detail-row');"
            "return [...row.querySelectorAll('td')].map((td) => td.textContent.trim());"
        )
        results["①表头"] = headers[:-1]
        results["①首行数据"] = first_row[:-1]
        results["①无负责人表头"] = "负责人" not in headers
        # 对齐：数据第 3 列应为计划完成日期（2026-05-12）
        results["①对齐正确"] = first_row[2] == "2026-05-12"
        d.save_screenshot(".runtime/req1_header_aligned.png")
    finally:
        d.quit()

    # ── 需求2：交付物工作台目录仅剩 6 个可用条目 ──
    d = make_driver()
    try:
        open_dark(d, f"{BASE}/#deliverables")
        time.sleep(1)
        names = d.execute_script(
            "return [...document.querySelectorAll("
            "'.deliverable-item .deliverable-name')].map((el) => el.textContent);"
        )
        unavailable = d.execute_script(
            "return document.querySelectorAll('.deliverable-item.is-unavailable').length;"
        )
        cat_options = d.execute_script(
            "return [...document.querySelectorAll("
            "'#deliverable-category-filter option')].map((o) => o.textContent);"
        )
        results["②目录条目"] = names
        results["②不可用条目数"] = unavailable
        results["②分类下拉"] = cat_options
        d.save_screenshot(".runtime/req2_catalog_slim.png")
    finally:
        d.quit()

    # ── 需求3：车型项目默认值同步主计划名称 ──
    d = make_driver()
    try:
        open_dark(d, f"{BASE}/#scheduled-archive")
        time.sleep(2)
        # 选中第一个任务（Aras EWO 变更记录）
        card = d.execute_script("""
          const card = [...document.querySelectorAll('.archive-config-card, article')]
            .find((c) => c.textContent.includes('Aras EWO'));
          if (card) card.click();
          return !!card;
        """)
        time.sleep(1.5)
        value_info = d.execute_script("""
          const input = document.querySelector('[data-archive-filter-name="projectCode"]');
          if (!input) return null;
          return {
            value: input.value,
            placeholder: input.placeholder,
            title: input.title,
            jsonHasProjectCode: document.querySelector('.archive-json-input, textarea')
              ? document.querySelector('.archive-json-input, textarea').value.includes('projectCode')
              : null,
          };
        """)
        results["③EWO任务卡片"] = card
        results["③车型项目字段"] = value_info
        d.save_screenshot(".runtime/req3_value_sync.png")
    finally:
        d.quit()

    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
