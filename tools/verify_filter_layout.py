# -*- coding: utf-8 -*-
"""Screenshot the implemented grouped filter bar (Plan A) after source changes."""

import time
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By

PORT = 5000
URL = f"http://127.0.0.1:{PORT}/#archive-deliverable/aras_ncr_progress"
THEME_KEY = "vse-toolbox-theme"


def main():
    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,960")
    driver = webdriver.Edge(options=opts)
    try:
        driver.get("about:blank")
        driver.get(URL)
        driver.execute_script(f"localStorage.setItem('{THEME_KEY}', 'dark');")
        driver.refresh()
        time.sleep(3.5)
        bar = driver.find_element(By.CSS_SELECTOR, ".form-filter-bar")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", bar)
        time.sleep(0.8)

        # 断言：三行结构存在
        rows = driver.execute_script("""
          return {
            search: !!document.querySelector('.form-filter-row-search'),
            dims: !!document.querySelector('.form-filter-row-dims'),
            time: !!document.querySelector('.form-filter-row-time'),
            info: !!document.querySelector('.form-filter-info'),
            overdueLabel: [...document.querySelectorAll('.form-filter-label')]
              .some((el) => el.textContent === '逾期状态'),
            placeholderShort: [...document.querySelectorAll('.analysis-multi-select-input')]
              .every((el) => el.placeholder === '搜索或多选'),
            scopeTextGone: !document.querySelector('.form-filter-scope'),
          };
        """)
        assert rows["search"] and rows["dims"] and rows["time"], rows
        assert rows["info"] and rows["overdueLabel"] and rows["placeholderShort"] and rows["scopeTextGone"], rows
        print("结构断言通过:", rows)

        # 断言：选项中文
        texts = driver.execute_script("""
          return [...document.querySelectorAll('.analysis-multi-select-option')]
            .map((b) => b.textContent);
        """)
        assert "已完成 / 不适用" in texts and "overdue" not in texts, texts
        print("选项中文断言通过:", texts)

        # 断言：多选框间距（同行相邻字段间隙 >= 10px）
        gap = driver.execute_script("""
          const row = document.querySelector('.form-filter-row-dims');
          const labels = [...row.querySelectorAll(':scope > .form-filter-field')];
          if (labels.length < 2) return -1;
          const a = labels[0].getBoundingClientRect();
          const b = labels[1].getBoundingClientRect();
          return Math.round(b.left - a.right);
        """)
        assert gap >= 10, f"multi-select gap too small: {gap}px"
        print(f"间距断言通过: 相邻多选框间隙 {gap}px")

        driver.save_screenshot(".runtime/plan_a_final_viewport.png")
        bar.screenshot(".runtime/plan_a_final_bar.png")
        print("截图: .runtime/plan_a_final_viewport.png / .runtime/plan_a_final_bar.png")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
