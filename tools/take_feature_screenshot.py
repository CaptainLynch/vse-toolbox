# -*- coding: utf-8 -*-
"""Capture focused screenshots of the deliverable form analysis component."""

import os
import subprocess
import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By

PORT = 55321
RUNTIME_DIR = Path(".runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def start_server():
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "webui.py", "--host", "127.0.0.1", "--port", str(PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2.5)
    return proc


def capture():
    server = start_server()
    driver = None
    try:
        opts = EdgeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1440,1800")
        opts.add_argument("--hide-scrollbars")
        opts.add_argument("--disable-gpu")
        driver = webdriver.Edge(options=opts)

        url_tdc = f"http://127.0.0.1:{PORT}/#deliverable/VPI-T2-D5"
        print(f"正在访问: {url_tdc}")
        driver.get(url_tdc)
        time.sleep(3.5)

        # 滚动到表单分析区域
        analysis_elem = driver.find_element(By.CSS_SELECTOR, ".deliverable-form-analysis")
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'start'});", analysis_elem)
        time.sleep(1)

        # 1. 截取 TDC 数模设计审核流程统一分析看板（项目状态 tab + 筛选栏 + 表格）
        out_path1 = RUNTIME_DIR / "screenshot_tdc_form_analysis_project_tab.png"
        driver.save_screenshot(str(out_path1))
        print(f"项目状态截图已保存: {out_path1}")

        # 2. 切换到“部门状态”Tab
        tabs = driver.find_elements(By.CSS_SELECTOR, ".form-chart-tab")
        for tab in tabs:
            if "部门状态" in tab.text:
                tab.click()
                time.sleep(1)
                break
        out_path2 = RUNTIME_DIR / "screenshot_tdc_form_analysis_dept_tab.png"
        driver.save_screenshot(str(out_path2))
        print(f"部门状态截图已保存: {out_path2}")

        # 3. 截取单个 element（整个 .deliverable-form-analysis 元素）
        out_elem_path = RUNTIME_DIR / "screenshot_tdc_element_only.png"
        analysis_elem.screenshot(str(out_elem_path))
        print(f"纯组件元素截图已保存: {out_elem_path}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        if server:
            try:
                server.terminate()
                server.wait(timeout=3)
            except Exception:
                try:
                    server.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    capture()
