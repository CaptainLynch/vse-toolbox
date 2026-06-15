from playwright.sync_api import sync_playwright
import time
import os

def test_playwright_crawler():
    print("正在启动 Playwright 爬虫测试...")
    try:
        with sync_playwright() as p:
            # 使用 Chromium 引擎，设为非无头模式（headless=False）以便于观察登录过程
            print("拉起浏览器...")
            browser = p.chromium.launch(headless=False) 
            
            # 也可以尝试直接调用本地安装的 Chrome 或 Edge
            # browser = p.chromium.launch(headless=False, channel="msedge")
            
            context = browser.new_context()
            page = context.new_page()
            
            # 这里以百度为例验证网络连通性。实际应用中请换成内网交付物网址
            test_url = "https://www.baidu.com"
            print(f"尝试访问网页: {test_url}")
            page.goto(test_url)
            
            # 等待网页加载完成
            page.wait_for_load_state("networkidle")
            title = page.title()
            print(f"成功打开网页，网页标题为: {title}")
            
            print("截图保存为 test_screenshot.png ...")
            current_dir = os.path.abspath(os.path.dirname(__file__))
            screenshot_path = os.path.join(current_dir, "test_screenshot.png")
            page.screenshot(path=screenshot_path)
            print("截图成功！")
            
            print("浏览器将在 5 秒后关闭。如果在公司电脑上能成功拉起浏览器并访问，证明爬虫方案可行。")
            time.sleep(5)
            browser.close()
            
    except Exception as e:
        print(f"测试失败，出现异常: {e}")

if __name__ == "__main__":
    test_playwright_crawler()
    input("按回车键退出...")
