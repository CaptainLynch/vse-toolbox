import atexit
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("VSE_TOOLBOX.crawler")

BASE_DIR = Path(__file__).parent.parent
DRIVERS_DIR = BASE_DIR / "drivers"
_DRIVER_EXT = ".exe" if sys.platform == "win32" else ""


def _get_data_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return BASE_DIR


DATA_DIR = _get_data_root() / "data"
COOKIES_DIR = DATA_DIR / "cookies"


class DriverManager:
    """管理 Chrome 和 Edge 两个 WebDriver 实例，按 URL 域名自动选择浏览器。

    - feishu.cn / larksuite.com → Edge
    - 其他所有 URL → Chrome（内网 EWO/OTS 等）
    - Cookie 持久化到 data/cookies/，保留登录态
    """

    def __init__(self):
        self._chrome = None
        self._edge = None
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        atexit.register(self.quit_all)

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def get(self, url: str):
        """根据 URL 自动选择并返回对应的 WebDriver 实例。"""
        if self._is_edge_target(url):
            return self._edge_driver()
        return self._chrome_driver()

    def fetch_page(self, url: str) -> dict:
        """导航到目标页面，返回 title 和 HTML 内容。"""
        driver = self.get(url)
        driver.get(url)
        time.sleep(2)  # 等待页面加载
        self._save_cookies(driver)
        return {
            "url": driver.current_url,
            "title": driver.title or "",
            "content": driver.page_source,
            "browser_used": "edge" if driver is self._edge else "chrome",
        }

    def extract_table(self, url: str, xpath: str = "//table") -> dict:
        """导航到目标页面，提取第一个匹配表格的 headers 和 rows。"""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = self.get(url)
        driver.get(url)
        time.sleep(2)
        self._save_cookies(driver)

        try:
            table = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except Exception:
            logger.warning("Table not found with xpath: %s", xpath)
            return {"headers": [], "rows": [], "row_count": 0}

        headers = []
        rows = []

        # 提取表头
        thead_rows = table.find_elements(By.XPATH, ".//thead//th")
        if thead_rows:
            headers = [th.text.strip() for th in thead_rows]
        else:
            first_row = table.find_elements(By.XPATH, ".//tr[1]")
            if first_row:
                cells = first_row[0].find_elements(By.XPATH, ".//th|.//td")
                headers = [c.text.strip() for c in cells]

        # 提取数据行
        trs = table.find_elements(By.XPATH, ".//tbody//tr")
        if not trs:
            trs = table.find_elements(By.XPATH, ".//tr")[1:]  # 跳过表头行

        for tr in trs:
            cells = tr.find_elements(By.XPATH, ".//td")
            row = [c.text.strip() for c in cells]
            if any(row):  # 跳过全空行
                rows.append(row)

        return {
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
        }

    def quit_all(self):
        """安全退出所有 WebDriver 实例。"""
        for d, name in [(self._chrome, "chrome"), (self._edge, "edge")]:
            if d:
                try:
                    d.quit()
                    logger.info("%s WebDriver quit", name)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _is_edge_target(url: str) -> bool:
        return "feishu.cn" in url or "larksuite.com" in url

    def _chrome_driver(self):
        if self._chrome is None:
            self._chrome = self._create_driver("chrome")
        return self._chrome

    def _edge_driver(self):
        if self._edge is None:
            self._edge = self._create_driver("edge")
        return self._edge

    def _create_driver(self, browser: str):
        """创建并配置 WebDriver 实例，加载持久化 Cookie。"""
        from selenium import webdriver

        if browser == "chrome":
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            opts = Options()
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)

            svc = Service(str(DRIVERS_DIR / f"chromedriver{_DRIVER_EXT}"))
            driver = webdriver.Chrome(service=svc, options=opts)
            logger.info("Chrome WebDriver created")

        elif browser == "edge":
            from selenium.webdriver.edge.options import Options
            from selenium.webdriver.edge.service import Service

            opts = Options()
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)

            svc = Service(str(DRIVERS_DIR / f"msedgedriver{_DRIVER_EXT}"))
            driver = webdriver.Edge(service=svc, options=opts)
            logger.info("Edge WebDriver created")

        else:
            raise ValueError(f"Unsupported browser: {browser}")

        self._load_cookies(driver, browser)
        return driver

    # ------------------------------------------------------------------
    # Cookie 持久化
    # ------------------------------------------------------------------

    def _cookie_path(self, browser: str) -> Path:
        return COOKIES_DIR / f"{browser}_cookies.json"

    def _save_cookies(self, driver):
        """将当前浏览器的 Cookie 保存到 JSON 文件。"""
        try:
            cookies = driver.get_cookies()
            path = self._cookie_path(
                "chrome" if driver is self._chrome else "edge"
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to save cookies", exc_info=True)

    def _load_cookies(self, driver, browser: str):
        """从 JSON 文件加载 Cookie 并添加到浏览器。需要先导航到目标域。"""
        path = self._cookie_path(browser)
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            if not cookies:
                return
            # 从第一个 cookie 推断域名
            domain = cookies[0].get("domain", "")
            if domain:
                # 先导航到同 domain 的页面以设置 cookie
                proto = "https" if any(
                    c.get("secure", False) for c in cookies
                ) else "http"
                driver.get(f"{proto}://{domain.lstrip('.')}/")
                time.sleep(1)
            for cookie in cookies:
                try:
                    # 跳过可能导致问题的字段
                    cookie.pop("sameSite", None)
                    cookie.pop("httpOnly", None)
                    driver.add_cookie(cookie)
                except Exception:
                    pass
            logger.info("Loaded %d cookies for %s", len(cookies), browser)
        except Exception:
            logger.warning("Failed to load cookies for %s", browser, exc_info=True)


# 模块级单例
_driver_manager: DriverManager | None = None


def get_driver_manager() -> DriverManager:
    global _driver_manager
    if _driver_manager is None:
        _driver_manager = DriverManager()
    return _driver_manager
