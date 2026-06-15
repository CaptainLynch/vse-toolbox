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

from rich.console import Console
from rich.prompt import Confirm

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        WebDriverException,
        NoSuchElementException,
    )

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from core.db_manager import DatabaseManager

logger = logging.getLogger("vse_toolbox.intranet_scraper")
console = Console()

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
            console.print("[red]错误: 未安装 selenium 库，请执行 pip install selenium[/]")
            raise ImportError("selenium 未安装")

    def _create_driver(self) -> Any:
        """
        创建 Chrome WebDriver 实例。

        Returns:
            配置好的 webdriver.Chrome 实例

        Raises:
            WebDriverException: WebDriver 启动失败
        """
        options = ChromeOptions()
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

        通过 rich 高亮提示，确保用户不会错过此步骤。
        """
        console.print()
        console.print(
            "[bold yellow]⚠ 请在弹出的浏览器窗口中完成内网登录[/]",
        )
        console.print(
            "[bold yellow]  登录成功后，请回到此终端按 [green]回车键[/] 继续...[/]",
        )
        console.print()

        try:
            input()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]用户取消操作[/]")
            raise

    def _scrape_data(self) -> list[dict[str, Any]]:
        """
        执行实际的数据抓取逻辑。

        注意: 此方法中的选择器和解析逻辑需根据实际内网页面结构调整。

        Returns:
            抓取到的数据列表，每条为一个 dict
        """
        scraped_items: list[dict[str, Any]] = []

        try:
            # 等待页面关键元素加载
            WebDriverWait(self._driver, self._timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # ──────────────────────────────────────────────
            # TODO: 在此添加实际的页面解析逻辑
            # 示例:
            #   rows = self._driver.find_elements(By.CSS_SELECTOR, "table.data tbody tr")
            #   for row in rows:
            #       cols = row.find_elements(By.TAG_NAME, "td")
            #       scraped_items.append({
            #           "name": cols[0].text.strip(),
            #           "owner": cols[1].text.strip(),
            #           "status": cols[2].text.strip(),
            #       })
            # ──────────────────────────────────────────────

            console.print(f"[green]✓ 抓取到 {len(scraped_items)} 条数据[/]")

        except TimeoutException:
            console.print("[red]错误: 页面加载超时，请检查网络连接[/]")
            logger.error("页面加载超时: %s", self._intranet_url)
            raise
        except NoSuchElementException as e:
            console.print(f"[red]错误: 页面元素未找到 — {e}[/]")
            logger.error("页面元素未找到: %s", e)
            raise

        return scraped_items

    def _save_to_database(self, items: list[dict[str, Any]]) -> None:
        """
        将抓取到的数据保存到 SQLite。

        Args:
            items: 抓取到的数据列表
        """
        if not items:
            console.print("[yellow]无数据需要保存[/]")
            return

        try:
            with self._db.get_connection() as conn:
                for item in items:
                    conn.execute(
                        """
                        INSERT INTO deliverables (project_id, name, owner, status)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            item.get("project_id", 1),
                            item.get("name", "未命名"),
                            item.get("owner", ""),
                            item.get("status", "pending"),
                        ),
                    )
                conn.commit()

            console.print(f"[green]✓ {len(items)} 条数据已入库[/]")
            logger.info("内网抓取数据入库 %d 条", len(items))

        except Exception as e:
            console.print(f"[red]错误: 数据入库失败 — {e}[/]")
            logger.exception("内网抓取数据入库失败")
            raise

    def run(self) -> None:
        """
        执行完整的内网爬取流程。

        流程: 启动浏览器 → 等待登录 → 抓取数据 → 保存 → 关闭浏览器
        """
        self._check_selenium()

        console.print("\n[bold cyan]═══ 内网数据抓取 ═══[/]\n")
        console.print(f"[dim]目标地址: {self._intranet_url}[/]")

        try:
            # 步骤 1: 启动浏览器
            console.print("[dim]正在启动 Chrome 浏览器...[/]")
            self._driver = self._create_driver()
            self._driver.get(self._intranet_url)
            console.print("[green]✓ 浏览器已启动[/]")

            # 步骤 2: 等待用户手动登录
            self._wait_for_user_login()

            # 步骤 3: 抓取数据
            console.print("[dim]开始抓取数据...[/]")
            data = self._scrape_data()

            # 步骤 4: 保存到数据库
            self._save_to_database(data)

            console.print("[bold green]内网数据抓取流程完成[/]")

        except KeyboardInterrupt:
            console.print("\n[yellow]用户中断抓取[/]")
            logger.info("用户中断内网抓取")

        except Exception as e:
            console.print(f"[red]错误: 爬虫运行异常 — {e}[/]")
            logger.exception("内网爬虫运行异常")

        finally:
            # 确保 WebDriver 正确退出，防止 Chrome 进程残留
            if self._driver:
                try:
                    self._driver.quit()
                    console.print("[dim]浏览器已关闭[/]")
                    logger.info("WebDriver 已退出")
                except Exception as e:
                    console.print(f"[yellow]警告: 浏览器关闭时出现异常 — {e}[/]")
                    logger.warning("WebDriver 退出异常: %s", e)


# ── 独立运行测试入口 ────────────────────────────────────────────
if __name__ == "__main__":
    console.print("[bold cyan]IntranetScraper 独立测试[/]\n")

    if not SELENIUM_AVAILABLE:
        console.print("[red]selenium 未安装，无法运行测试[/]")
    else:
        test_db = DatabaseManager()
        test_db.init_database()
        scraper = IntranetScraper(test_db)
        scraper.run()
