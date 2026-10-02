# -*- coding: utf-8 -*-
"""
services/intranet_scraper.py — 基于 Selenium 的内网数据爬虫

职责:
    1. 启动 Chrome WebDriver 并打开内网登录页
    2. 通过 rich 终端提示用户手动完成内网登录
    3. 登录后自动抓取指定页面数据并存入 SQLite

设计要点:
    - 用户登录为人工介入点，必须有清晰的终端提示
    - WebDriver 必须在 finally 中调用 driver.quit() 防止进程残留
    - 所有元素等待使用 WebDriverWait，避免 time.sleep 硬等待
    - 兼容 Windows 环境下的 chromedriver 路径配置

依赖:
    - selenium (WebDriver)
    - rich (终端交互)
    - core.db_manager (数据持久化)
"""

import logging
from pathlib import Path
from typing import Any
import os
import time
import glob

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from core.db_manager import DatabaseManager

logger = logging.getLogger("vse_toolbox.intranet_scraper")

# ── 默认配置 ────────────────────────────────────────────────────
# 可按实际内网地址修改
DEFAULT_INTRANET_URL = "https://intranet.example.com"
DEFAULT_TIMEOUT = 30  # 元素等待超时（秒）


class IntranetScraper:
    """
    内网数据爬虫

    工作流程:
        1. 启动 headless=False 的 Chrome（需要用户看到浏览器界面）
        2. 导航至内网登录页
        3. 终端提示用户手动登录
        4. 用户按回车后，开始自动抓取
        5. 抓取结果写入 SQLite
        6. 无论成功失败，确保 WebDriver 正确退出

    用法:
        scraper = IntranetScraper(db_manager)
        scraper.run()
    """

    def __init__(
        self,
        db: DatabaseManager,
        intranet_url: str = DEFAULT_INTRANET_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """
        初始化爬虫。

        Args:
            db: 数据库管理器实例
            intranet_url: 内网登录页 URL
            timeout: 元素等待超时秒数
        """
        self._db = db
        self._intranet_url = intranet_url
        self._timeout = timeout
        self._driver: Any = None  # webdriver.Chrome | None

    def _check_selenium(self) -> None:
        """检查 Selenium 是否可用"""
        if not SELENIUM_AVAILABLE:
            raise ImportError("selenium 未安装")
        if not PANDAS_AVAILABLE:
            raise ImportError("pandas 未安装")

    def _create_driver(self) -> Any:
        """
        创建 Chrome WebDriver 实例。

        Returns:
            配置好的 webdriver.Chrome 实例

        Raises:
            WebDriverException: WebDriver 启动失败
        """
        options = ChromeOptions()

        # 设定静默下载目录为项目 data 文件夹
        download_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        options.add_experimental_option("prefs", prefs)

        # 非无头模式 — 用户需要看到浏览器完成手动登录
        # options.add_argument("--headless")  # 如需无头模式，取消此行注释
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--ignore-certificate-errors")
        # 禁用自动化检测提示
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        # 尝试查找项目目录下的 chromedriver
        local_driver = Path(__file__).resolve().parent.parent / "chromedriver.exe"
        if local_driver.exists():
            service = ChromeService(executable_path=str(local_driver))
            driver = webdriver.Chrome(service=service, options=options)
        else:
            # 使用系统 PATH 中的 chromedriver
            driver = webdriver.Chrome(options=options)

        driver.implicitly_wait(5)
        return driver

    def _wait_for_user_login(self) -> None:
        """
        终端阻塞等待用户手动完成内网登录。
        """
        logger.info("请在弹出的浏览器窗口中完成内网登录，完成后按回车继续...")
        try:
            input("请在弹出的浏览器窗口中完成内网登录，完成后按回车继续: ")
        except (EOFError, KeyboardInterrupt):
            logger.warning("用户取消操作")
            raise

    def _scrape_data(self) -> list[dict[str, Any]]:
        """
        执行实际的数据抓取逻辑。

        基于静默下载 Excel 的策略：
        1. 穿透 iframe 定位查询/导出按钮
        2. 点击并等待 Excel 落盘到 data 目录
        3. 使用 Pandas 解析
        """
        scraped_items: list[dict[str, Any]] = []
        download_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))

        try:
            wait = WebDriverWait(self._driver, self._timeout)

            # Aras Innovator 的表单通常在 iframe 中，尝试自动切换
            try:
                iframes = self._driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    src = iframe.get_attribute("src") or ""
                    if "ShowFormInFrame" in src or "itemsGrid" in src or "index.html" in src:
                        self._driver.switch_to.frame(iframe)
                        break
            except Exception as e:
                logger.debug("Iframe 切换异常: %s", e)

            # 定位“查询审批进度”按钮，支持常见的 button 标签或带有文本的 div/span
            query_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//*[contains(text(), '审批进度')] | //input[contains(@value, '审批进度')]")
            ))

            # 记录下载前文件夹内的 .xlsx 文件集合
            files_before = set(glob.glob(os.path.join(download_dir, "*.xlsx")))

            logger.info("正在触发报表生成并等待下载 (最多60秒)...")
            query_btn.click()

            # 轮询等待新 Excel 出现
            downloaded_file = None
            for _ in range(60):
                time.sleep(1)
                files_after = set(glob.glob(os.path.join(download_dir, "*.xlsx")))
                new_files = files_after - files_before

                if new_files:
                    potential_file = new_files.pop()
                    if not potential_file.endswith('.crdownload'):
                        downloaded_file = potential_file
                        break

            if not downloaded_file:
                raise TimeoutException("等待 Excel 下载超时，请检查网络或按钮是否正确点击。")

            # 切回主页面
            self._driver.switch_to.default_content()

            # 解析下载好的 Excel 文件，第一行为副标题，第二行(index=1)为真实表头
            df = pd.read_excel(downloaded_file, header=1)

            def map_status(s: str) -> str:
                s = str(s).strip()
                if "关闭" in s or "完成" in s:
                    return "done"
                elif "终止" in s or "作废" in s:
                    return "blocked"
                elif not s or s == "nan":
                    return "pending"
                return "in_progress"

            # 遍历数据行转换为字典 (根据刚刚读取到的真实表头进行映射)
            for index, row in df.iterrows():
                scraped_items.append({
                    "name": str(row.get('NCR编号', f'Unknown_{index}')),
                    "project_id": str(row.get('项目', '1')),
                    "owner": str(row.get('当前审批人', '未知')),
                    "status": map_status(row.get('状态', ''))
                })

            logger.info("从 Excel 中成功提取了 %d 条数据", len(scraped_items))

        except TimeoutException:
            logger.exception("抓取/下载超时: %s", self._intranet_url)
            raise
        except Exception:
            logger.exception("抓取操作异常")
            raise

        return scraped_items

    def _save_to_database(self, items: list[dict[str, Any]]) -> None:
        """
        将抓取到的数据保存到 SQLite。

        Args:
            items: 抓取到的数据列表
        """
        if not items:
            logger.warning("无数据需要保存")
            return

        try:
            count = self._db.persist_scraped_deliverables(items)
            logger.info("内网抓取数据入库 %d 条", count)
        except Exception as e:
            logger.exception("内网抓取数据入库失败: %s", e)
            raise

    def run(self) -> None:
        """
        执行完整的内网爬取流程。

        流程: 启动浏览器 → 等待登录 → 抓取数据 → 保存 → 关闭浏览器
        """
        self._check_selenium()

        try:
            # 步骤 1: 启动浏览器
            self._driver = self._create_driver()
            self._driver.get(self._intranet_url)

            # 步骤 2: 等待用户手动登录
            self._wait_for_user_login()

            # 步骤 3: 抓取数据
            data = self._scrape_data()

            # 步骤 4: 保存到数据库
            self._save_to_database(data)

        except KeyboardInterrupt:
            logger.info("用户中断内网抓取")

        except Exception:
            logger.exception("内网爬虫运行异常")

        finally:
            # 确保 WebDriver 正确退出，防止 Chrome 进程残留
            if self._driver:
                try:
                    self._driver.quit()
                    logger.info("WebDriver 已退出")
                except Exception as e:
                    logger.warning("WebDriver 退出异常: %s", e)


# ── 独立运行测试入口 ────────────────────────────────────────────
if __name__ == "__main__":
    if not SELENIUM_AVAILABLE:
        print("selenium 未安装，无法运行测试")
    else:
        test_db = DatabaseManager()
        test_db.init_database()
        scraper = IntranetScraper(test_db)
        scraper.run()
