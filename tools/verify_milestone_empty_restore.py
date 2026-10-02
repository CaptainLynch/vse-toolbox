# -*- coding: utf-8 -*-
"""Verify delete-all milestone auto-restore flow, then restore user data."""

import json
import time
import urllib.request

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions

THEME_KEY = "vse-toolbox-theme"
BASE = "http://127.0.0.1:5000"


def api_state():
    with urllib.request.urlopen(f"{BASE}/api/project-status?phase=VPI-T2") as r:
        return json.load(r)["data"]


def api_patch_milestones(backup, updated_at):
    payload = {
        "milestones": [
            {
                "id": m["id"],
                "name": m["name"],
                "date": m["date"],
                "status": m["status"],
                "type": m["type"],
                "sortOrder": i + 1,
            }
            for i, m in enumerate(backup)
        ],
        "updatedAt": updated_at,
    }
    req = urllib.request.Request(
        f"{BASE}/api/project-status/phases/VPI-T2/milestones",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    backup = api_state()["milestones"]
    print("备份节点:", [m["name"] for m in backup])

    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,1200")
    d = webdriver.Edge(options=opts)
    try:
        d.get("about:blank")
        d.get(f"{BASE}/#overview")
        d.execute_script(f"localStorage.setItem('{THEME_KEY}', 'dark');")
        d.refresh()
        time.sleep(3.5)
        for tab in d.find_elements(By.TAG_NAME, "button"):
            if "主计划维护" in tab.text:
                tab.click()
                break
        time.sleep(1.2)
        edit_btn = d.find_element(By.CSS_SELECTOR, ".milestone-edit-btn")
        d.execute_script("arguments[0].click();", edit_btn)
        time.sleep(0.8)
        print("编辑态节点行:", len(d.find_elements(By.CSS_SELECTOR, ".milestone-edit-row")))
        for _ in range(15):
            rows = d.find_elements(By.CSS_SELECTOR, ".milestone-edit-row")
            if not rows:
                break
            delete_btn = rows[0].find_element(By.CSS_SELECTOR, ".milestone-delete-btn")
            d.execute_script("arguments[0].click();", delete_btn)
            time.sleep(0.3)
        print("删除全部后编辑表单仍在:", d.execute_script(
            "return !!document.getElementById('milestone-edit-form');"))
        d.execute_script(
            "arguments[0].click();",
            d.find_element(By.CSS_SELECTOR, ".milestone-save-btn"),
        )
        time.sleep(1.8)
        msg = d.execute_script(
            "return [...document.querySelectorAll('.edit-request-info')]"
            ".map((el) => el.textContent.trim());"
        )
        names = d.execute_script(
            "return [...document.querySelectorAll("
            "'.milestone-main-row .milestone-main-name')].map((el) => el.textContent);"
        )
        print("提示消息:", msg)
        print("保存后只读列表节点:", names)
        assert any("已自动恢复默认节点模板" in m for m in msg), msg
        assert len(names) == 11 and names[0] == "VPI" and names[-1] == "用户体验阀", names
        print("PASS: 删除全部节点保存后自动恢复默认模板（含提示）")
        d.save_screenshot(".runtime/req_delete_all_restore.png")
    finally:
        d.quit()

    state = api_state()
    body = api_patch_milestones(backup, state["phase"]["updatedAt"])
    restored = body["data"]["projectStatus"]["milestones"]
    print("已还原用户节点:", body["ok"], [m["name"] for m in restored])


if __name__ == "__main__":
    main()
