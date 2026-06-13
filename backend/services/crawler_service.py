import atexit
import json
import logging
import sys
import time
import threading
from urllib.parse import urlparse, urlunparse
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


    # ------------------------------------------------------------------
    # Aras Innovator EWO / NCR 报表解析
    # ------------------------------------------------------------------

    # EWO 表格列映射 (data-index → 字段含义)
    # 0: 复选框/图标 (跳过)  1: EWO编号  2: 二级WO类别  3: 责任工程师
    # 4: TDC专业科室  5: 主题  6: 车型信息  7: 创建时间
    _EWO_COL_MAP = {
        1: "_aras_id",
        2: "description",
        3: "assignee",
        4: "department",
        5: "title",
        6: "_vehicle",
        7: "raised_date",
    }

    # NCR 表格列映射 (data-index → 字段含义)
    # 0: 复选框/图标 (跳过)  1: NCR编号  2: 创建时间  3: 提交日期
    # 4: 提交人  5: 关联NCR项目  6: NCR状态  7: 当前节点
    # 8: 阶段滞留天数  9: NCR更改类别  10: 主题
    _NCR_COL_MAP = {
        1: "_aras_id",
        2: "raised_date",
        3: "target_date",
        4: "assignee",
        5: "description",
        6: "_raw_status",
        7: "_current_node",
        8: "_stage_days",
        9: "department",
        10: "title",
    }

    # NCR 状态 → ewo_ncr 表 status 枚举映射
    _NCR_STATUS_MAP = {
        "open": "open",
        "opened": "open",
        "新建": "open",
        "进行中": "investigating",
        "in progress": "investigating",
        "investigating": "investigating",
        "已解决": "resolved",
        "resolved": "resolved",
        "closed": "closed",
        "已关闭": "closed",
        "已完成": "closed",
    }

    def _parse_aras_grid(
        self,
        driver,
        url: str,
        col_map: dict,
        record_type: str,
        wait_timeout: int = 30,
    ) -> list[dict]:
        """通用 Aras Innovator .aras-grid-viewport 表格解析器。

        Args:
            driver: 已导航到目标页的 WebDriver 实例。
            url: 当前页面 URL（记录到 source_file）。
            col_map: {data-index: field_name} 列映射。
            record_type: 'EWO' 或 'NCR'。
            wait_timeout: 等待表格加载的最大秒数。

        Returns:
            list[dict] — 每条记录对应一个字典。
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        # 等待数据表格出现
        try:
            WebDriverWait(driver, wait_timeout).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "table.aras-grid-viewport")
                )
            )
        except Exception:
            logger.warning("Aras grid not found: %s", url)
            return []

        # --- 提取表头（用于日志调试） ---
        head_cells = driver.find_elements(
            By.CSS_SELECTOR, "table.aras-grid-head th.aras-grid-head-cell"
        )
        if head_cells:
            head_names = [c.text.strip() for c in head_cells if c.text.strip()]
            logger.debug("Aras %s 表头: %s", record_type, head_names)

        # --- 提取数据行 ---
        row_elements = driver.find_elements(
            By.CSS_SELECTOR, "table.aras-grid-viewport tr.aras-grid-row"
        )

        records = []
        for row_el in row_elements:
            cells = row_el.find_elements(
                By.CSS_SELECTOR, "td.aras-grid-row-cell"
            )
            if not cells:
                continue

            # 按 data-index 收集各列纯文本
            cell_texts = {}
            for cell in cells:
                idx_str = cell.get_attribute("data-index")
                if idx_str is None:
                    continue
                try:
                    idx = int(idx_str)
                except (ValueError, TypeError):
                    continue
                # .text 自动剥离嵌套 <span> 等标签
                cell_texts[idx] = cell.text.strip()

            # 过滤空白行：所有映射列都为空则跳过
            mapped_values = [
                cell_texts.get(i, "")
                for i in col_map
                if i != 0
            ]
            if not any(mapped_values):
                continue

            # 组装记录
            record = {
                "type": record_type,
                "severity": "minor",
                "status": "open",
                "source": "aras_crawler",
                "source_file": self._sanitize_url(url),
            }
            for col_idx, field_name in col_map.items():
                record[field_name] = cell_texts.get(col_idx, "")

            records.append(record)

        logger.info(
            "Aras %s 解析完成: %d 行（空白行已过滤）", record_type, len(records)
        )
        return records

    def extract_ewo_list(self, url: str, wait_timeout: int = 30) -> list[dict]:
        """从 Aras Innovator EWO 报表页面提取列表数据。

        导航到指定 URL，解析 .aras-grid-viewport 表格，
        按 EWO 列定义映射为 ewo_ncr 表兼容的字典列表。

        Args:
            url: EWO 报表页面 URL（需已登录或有 Cookie）。
            wait_timeout: 等待表格加载的最大秒数，默认 30。

        Returns:
            list[dict] — 每条 EWO 记录，key 对应 ewo_ncr 表字段。
            额外字段 _aras_id（EWO编号）、_vehicle（车型信息）保留原始数据。
        """
        driver = self.get(url)
        driver.get(url)
        time.sleep(2)
        self._save_cookies(driver)

        records = self._parse_aras_grid(
            driver, url, self._EWO_COL_MAP, "EWO", wait_timeout
        )

        # EWO status 默认 open（EWO 报表通常无状态列）
        for r in records:
            r["status"] = "open"

        return records

    def extract_ncr_list(self, url: str, wait_timeout: int = 30) -> list[dict]:
        """从 Aras Innovator NCR 报表页面提取列表数据。

        导航到指定 URL，解析 .aras-grid-viewport 表格，
        按 NCR 列定义映射为 ewo_ncr 表兼容的字典列表。

        NCR 表格中人名含嵌套 <span class="aras-grid-link">，
        使用 .text 属性自动剥离嵌套标签获取纯文本。

        Args:
            url: NCR 报表页面 URL（需已登录或有 Cookie）。
            wait_timeout: 等待表格加载的最大秒数，默认 30。

        Returns:
            list[dict] — 每条 NCR 记录，key 对应 ewo_ncr 表字段。
            额外字段 _aras_id（NCR编号）、_current_node、_stage_days 保留原始数据。
            status 已映射为 open/investigating/resolved/closed。
        """
        driver = self.get(url)
        driver.get(url)
        time.sleep(2)
        self._save_cookies(driver)

        records = self._parse_aras_grid(
            driver, url, self._NCR_COL_MAP, "NCR", wait_timeout
        )

        # NCR status 映射
        for r in records:
            raw = r.pop("_raw_status", "").lower().strip()
            r["status"] = self._NCR_STATUS_MAP.get(raw, "open")

        return records

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
    def _sanitize_url(url: str) -> str:
        """剥离 URL 中的 query/fragment，防止敏感参数泄露 (R-07)。"""
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    @staticmethod
    def _is_edge_target(url: str) -> bool:
        """精确域名匹配，防止子串绕过（如 evil-feishu.cn.attacker.com）。"""
        host = (urlparse(url).hostname or "").lower()
        return (
            host == "feishu.cn" or host.endswith(".feishu.cn")
            or host == "larksuite.com" or host.endswith(".larksuite.com")
        )

    def _chrome_driver(self):
        if self._chrome is not None:
            try:
                _ = self._chrome.title  # 存活检测
            except Exception:
                try:
                    self._chrome.quit()
                except Exception:
                    pass
                self._chrome = None
        if self._chrome is None:
            self._chrome = self._create_driver("chrome")
        return self._chrome

    def _edge_driver(self):
        if self._edge is not None:
            try:
                _ = self._edge.title  # 存活检测
            except Exception:
                try:
                    self._edge.quit()
                except Exception:
                    pass
                self._edge = None
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
            opts.add_argument(r"--user-data-dir=C:\Users\Lynch\AppData\Local\Google\Chrome\User Data")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--auth-server-whitelist=*sgmw.com.cn")
            opts.add_argument("--auth-negotiate-delegate-whitelist=*sgmw.com.cn")
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
            opts.add_argument("--auth-server-whitelist=*sgmw.com.cn")
            opts.add_argument("--auth-negotiate-delegate-whitelist=*sgmw.com.cn")
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
                    removed = []
                    for key in ("sameSite", "httpOnly"):
                        if cookie.pop(key, None) is not None:
                            removed.append(key)
                    if removed:
                        logger.debug("Cookie security fields removed: %s for %s", removed, cookie.get("name", "?"))
                    driver.add_cookie(cookie)
                except Exception:
                    pass
            logger.info("Loaded %d cookies for %s", len(cookies), browser)
        except Exception:
            logger.warning("Failed to load cookies for %s", browser, exc_info=True)


# 模块级单例
_driver_manager: DriverManager | None = None
_driver_manager_lock = threading.Lock()


def get_driver_manager() -> DriverManager:
    global _driver_manager
    if _driver_manager is None:
        with _driver_manager_lock:
            if _driver_manager is None:
                _driver_manager = DriverManager()
    return _driver_manager
