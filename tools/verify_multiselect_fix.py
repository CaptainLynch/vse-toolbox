# -*- coding: utf-8 -*-
"""Verify multi-select dropdowns open on demand only (Plan A fix)."""

import time
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By

PORT = 5000
RUNTIME_DIR = ".runtime"


def option_boxes(driver):
    return driver.find_elements(By.CSS_SELECTOR, ".analysis-multi-select-options")


def visible(box):
    return box.is_displayed()


def main():
    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,1200")
    driver = webdriver.Edge(options=opts)
    try:
        driver.get(f"http://127.0.0.1:{PORT}/#deliverable/VPI-T2-D5")
        time.sleep(3.5)

        # 1. 默认状态：所有下拉必须收起
        boxes = option_boxes(driver)
        assert len(boxes) >= 4, f"expected >=4 multi-selects, got {len(boxes)}"
        open_by_default = [b for b in boxes if visible(b)]
        assert not open_by_default, f"{len(open_by_default)} dropdowns open by default!"
        print(f"PASS 1: 页面加载后 {len(boxes)} 个多选下拉全部收起，图表不被遮挡")

        # 2. 点击第一个输入框：只有它展开
        inputs = driver.find_elements(By.CSS_SELECTOR, ".analysis-multi-select-input")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inputs[0])
        time.sleep(0.3)
        inputs[0].click()
        time.sleep(0.5)
        boxes = option_boxes(driver)
        open_now = [b for b in boxes if visible(b)]
        assert len(open_now) == 1, f"expected exactly 1 open dropdown, got {len(open_now)}"
        print("PASS 2: 点击输入框后仅 1 个下拉展开")

        driver.save_screenshot(f"{RUNTIME_DIR}/screenshot_multiselect_single_open.png")

        # 3. 聚焦第二个输入框：第一个收起，第二个展开（全局单开）
        inputs = driver.find_elements(By.CSS_SELECTOR, ".analysis-multi-select-input")
        inputs[1].click()
        time.sleep(0.5)
        boxes = option_boxes(driver)
        open_now = [b for b in boxes if visible(b)]
        assert len(open_now) == 1, f"expected 1 open after switching focus, got {len(open_now)}"
        print("PASS 3: 切换聚焦后仍是仅 1 个展开（自动收起上一个）")

        # 4. Esc 关闭
        from selenium.webdriver.common.keys import Keys
        inputs = driver.find_elements(By.CSS_SELECTOR, ".analysis-multi-select-input")
        inputs[1].send_keys(Keys.ESCAPE)
        time.sleep(0.4)
        boxes = option_boxes(driver)
        open_now = [b for b in boxes if visible(b)]
        assert not open_now, f"Escape did not close, {len(open_now)} still open"
        print("PASS 4: Esc 键关闭下拉")

        # 5. 选中一个选项后：筛选栏既有设计是立即应用并重建视图。
        #    修复前：重建后所有下拉再次全部展开（遮挡回归）；
        #    修复后：重建后保持收起，且已选 token 正确生成。
        inputs = driver.find_elements(By.CSS_SELECTOR, ".analysis-multi-select-input")
        inputs[0].click()
        time.sleep(0.4)
        first_option = driver.find_element(By.CSS_SELECTOR, ".analysis-multi-select-option")
        first_option.click()
        time.sleep(1.2)
        boxes = option_boxes(driver)
        open_now = [b for b in boxes if visible(b)]
        assert not open_now, f"after selection + view reload, {len(open_now)} dropdowns reopened (occlusion regression)"
        chips = driver.find_elements(By.CSS_SELECTOR, ".form-filter-chip, .analysis-filter-token")
        assert chips, "selected filter token/chip not found after selection"
        print(f"PASS 5: 选中后视图重载，下拉保持收起（{len(chips)} 个已选条件正确显示）")

        driver.save_screenshot(f"{RUNTIME_DIR}/screenshot_multiselect_selected_state.png")
        print("全部验证通过")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
