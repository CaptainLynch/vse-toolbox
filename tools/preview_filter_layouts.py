# -*- coding: utf-8 -*-
"""Render layout previews of the filter bar (Option A vs Option B) on the real page.

No source files are modified: both variants are injected at runtime.
"""

import time
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By

PORT = 5000
URL = f"http://127.0.0.1:{PORT}/#archive-deliverable/aras_ncr_progress"
THEME_KEY = "vse-toolbox-theme"

VARIANT_A_CSS = """
.form-filter-controls { display: grid !important; grid-template-columns: 1fr !important; gap: 10px !important; }
.form-filter-row-search { display: grid; grid-template-columns: minmax(240px, 2fr) minmax(160px, 1fr) auto; gap: 8px; align-items: end; }
.form-filter-row-dims { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
.form-filter-row-time { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 200px)); gap: 8px; }
.form-filter-field-wide { min-width: 0 !important; }
.form-filter-title { display: inline-flex; align-items: center; gap: 6px; }
.form-filter-info { cursor: help; color: var(--muted); font-size: 12px; border: 1px solid var(--hairline-strong); border-radius: 999px; padding: 0 6px; }
"""

VARIANT_B_CSS = """
.form-filter-controls { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)) !important; }
.form-filter-field-wide { min-width: 0 !important; }
"""


def chineseize_overdue_state(driver):
    """Preview-only: localize the overdueState field label and its options."""
    driver.execute_script("""
      document.querySelectorAll('.form-filter-label').forEach((el) => {
        if (el.textContent.trim() === 'overdueState') el.textContent = '逾期状态';
      });
      document.querySelectorAll('.analysis-multi-select-option').forEach((btn) => {
        const v = btn.dataset.value;
        if (v === 'not_applicable') btn.textContent = '已完成 / 不适用';
        else if (v === 'overdue') btn.textContent = '逾期风险';
      });
    """)


def inject_css(driver, css):
    driver.execute_script("""
      const style = document.createElement('style');
      style.dataset.preview = 'layout';
      style.textContent = arguments[0];
      document.head.appendChild(style);
    """, css)


def shorten_placeholders(driver):
    driver.execute_script("""
      document.querySelectorAll('.analysis-multi-select-input').forEach((el) => {
        el.placeholder = '搜索或多选';
      });
    """)


def build_variant_a_dom(driver):
    driver.execute_script("""
      const controls = document.querySelector('.form-filter-controls');
      if (!controls || controls.querySelector('.form-filter-row-dims')) return;

      const keyword = controls.querySelector(':scope > .form-filter-keyword');
      const wideLabels = [...controls.querySelectorAll(':scope > label.form-filter-field-wide')];
      const allDirectLabels = [...controls.querySelectorAll(':scope > label.form-filter-field')];
      const relation = allDirectLabels.find((l) => l.querySelector('input[aria-label="关联EWO"]'));
      const dateLabels = allDirectLabels.filter((l) => l.querySelector('input[type="date"]'));
      const actions = controls.querySelector(':scope > .form-filter-actions');

      const row1 = document.createElement('div');
      row1.className = 'form-filter-row-search';
      row1.append(keyword, relation, actions);
      const row2 = document.createElement('div');
      row2.className = 'form-filter-row-dims';
      row2.append(...wideLabels);
      const row3 = document.createElement('div');
      row3.className = 'form-filter-row-time';
      row3.append(...dateLabels);
      controls.replaceChildren(row1, row2, row3);

      const head = document.querySelector('.form-filter-head');
      const scope = head.querySelector('.form-filter-scope');
      scope.textContent = 'ⓘ';
      scope.className = 'form-filter-info';
      scope.title = '仅作用于当前图表页签与表单明细；同一字段内多选为或，字段之间为且';
      scope.setAttribute('aria-label', scope.title);
      const title = head.querySelector('.form-filter-title');
      title.appendChild(scope);
    """)


def open_page(driver):
    driver.get("about:blank")
    driver.get(URL)
    driver.execute_script(f"localStorage.setItem('{THEME_KEY}', 'dark');")
    driver.refresh()
    time.sleep(3.5)
    bar = driver.find_element(By.CSS_SELECTOR, ".form-filter-bar")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", bar)
    time.sleep(0.8)
    chineseize_overdue_state(driver)


def shoot(driver, name):
    driver.save_screenshot(f".runtime/{name}_viewport.png")
    bar = driver.find_element(By.CSS_SELECTOR, ".form-filter-bar")
    bar.screenshot(f".runtime/{name}_bar.png")
    print(f"saved: .runtime/{name}_viewport.png / .runtime/{name}_bar.png")


def main():
    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,960")
    driver = webdriver.Edge(options=opts)
    try:
        # 方案 A：分组三行网格
        open_page(driver)
        inject_css(driver, VARIANT_A_CSS)
        build_variant_a_dom(driver)
        shorten_placeholders(driver)
        time.sleep(0.5)
        shoot(driver, "preview_option_a_grouped")

        # 方案 B：流式换行
        open_page(driver)
        inject_css(driver, VARIANT_B_CSS)
        shorten_placeholders(driver)
        time.sleep(0.5)
        shoot(driver, "preview_option_b_flow")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
