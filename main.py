# -*- coding: utf-8 -*-
"""
VSE TOOLBOX (CLI Edition) — 主入口模块

功能概述:
    基于 rich 终端渲染的交互式主菜单循环，
    通过数字选项路由到各 service 模块的独立功能。

架构约束:
    - main.py 仅做路由，不包含任何业务逻辑
    - 所有功能调用均通过 services/ 下的模块完成
    - 数据库操作通过 core/db_manager 统一管理
"""

import sys
import logging
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm

# ── 项目路径初始化 ──────────────────────────────────────────────
# 确保项目根目录在 sys.path 中，支持从任意位置启动
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db_manager import DatabaseManager
from services.intranet_scraper import IntranetScraper
from services.feishu_imap import FeishuImapParser
from services.office_toolbox import OfficeToolbox

# ── 日志配置 ────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "data"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "vse_toolbox.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("vse_toolbox")

# ── 全局 rich 控制台 ────────────────────────────────────────────
console = Console()

# ── 菜单配置 ────────────────────────────────────────────────────
# 键: 菜单数字选项  值: (显示文本, 对应处理函数名)
MENU_OPTIONS: dict[str, tuple[str, str]] = {
    "1": ("更新交付物状态", "handle_update_deliverables"),
    "2": ("生成周报 PPT", "handle_generate_ppt"),
    "3": ("扫描飞书待办", "handle_scan_feishu"),
    "4": ("内网数据抓取", "handle_intranet_scrape"),
    "5": ("查看项目概览", "handle_project_overview"),
    "0": ("退出系统", "handle_exit"),
}


def show_banner() -> None:
    """显示启动横幅"""
    banner = Text()
    banner.append("VSE TOOLBOX", style="bold cyan")
    banner.append(" (CLI Edition)", style="dim")
    banner.append("\n汽车行业项目管理自动化工具箱", style="green")
    console.print(Panel(banner, border_style="cyan", expand=False))


def show_menu() -> None:
    """渲染主菜单选项"""
    console.print()
    for key, (label, _) in MENU_OPTIONS.items():
        style = "bold red" if key == "0" else "bold white"
        console.print(f"  [{style}]{key}[/] ── {label}")
    console.print()


def handle_update_deliverables(db: DatabaseManager) -> None:
    """【菜单 1】交互式更新交付物状态"""
    console.print("\n[bold cyan]═══ 更新交付物状态 ═══[/]\n")
    try:
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, owner, status, due_date FROM deliverables ORDER BY due_date"
            ).fetchall()

        if not rows:
            console.print("[yellow]当前无交付物记录，请先通过其他方式导入数据。[/]")
            return

        # 展示当前交付物列表
        from rich.table import Table

        table = Table(title="当前交付物列表", show_lines=True)
        table.add_column("ID", justify="center", style="cyan")
        table.add_column("名称", style="white")
        table.add_column("负责人", style="green")
        table.add_column("状态", style="yellow")
        table.add_column("截止日期", style="magenta")

        status_styles = {
            "pending": "[yellow]待开始[/]",
            "in_progress": "[blue]进行中[/]",
            "done": "[green]已完成[/]",
            "blocked": "[red]阻塞[/]",
        }
        for row in rows:
            sid, name, owner, status, due = row
            styled_status = status_styles.get(status, status)
            table.add_row(str(sid), name, owner or "-", styled_status, due or "-")

        console.print(table)

        # 交互式选择
        deliverable_id = Prompt.ask(
            "\n请输入要更新的交付物 ID（输入 q 返回主菜单）"
        )
        if deliverable_id.lower() == "q":
            return

        new_status = Prompt.ask(
            "选择新状态",
            choices=["pending", "in_progress", "done", "blocked"],
            default="pending",
        )
        remark = Prompt.ask("备注（可选，直接回车跳过）", default="")

        with db.get_connection() as conn:
            conn.execute(
                "UPDATE deliverables SET status=?, remark=?, updated_at=datetime('now','localtime') WHERE id=?",
                (new_status, remark, int(deliverable_id)),
            )
            conn.commit()

        console.print(f"[green]✓ 交付物 #{deliverable_id} 状态已更新为 {new_status}[/]")
        logger.info("交付物 #%s 状态更新为 %s", deliverable_id, new_status)

    except (ValueError, TypeError) as e:
        console.print(f"[red]错误: 输入无效 — {e}[/]")
        logger.error("更新交付物状态时输入无效: %s", e)
    except Exception as e:
        console.print(f"[red]错误: 更新失败 — {e}[/]")
        logger.exception("更新交付物状态时发生异常")


def handle_generate_ppt(db: DatabaseManager) -> None:
    """【菜单 2】基于 SQLite 数据生成周报 PPT"""
    console.print("\n[bold cyan]═══ 生成周报 PPT ═══[/]\n")
    try:
        toolbox = OfficeToolbox(db)
        output_path = toolbox.refresh_weekly_ppt()
        console.print(f"[green]✓ 周报 PPT 已生成: {output_path}[/]")
    except FileNotFoundError as e:
        console.print(f"[red]错误: 模板文件未找到 — {e}[/]")
        logger.error("PPT 模板文件未找到: %s", e)
    except PermissionError as e:
        console.print(f"[red]错误: 文件被占用或无写入权限 — {e}[/]")
        logger.error("PPT 写入权限错误: %s", e)
    except Exception as e:
        console.print(f"[red]错误: PPT 生成失败 — {e}[/]")
        logger.exception("生成周报 PPT 时发生异常")


def handle_scan_feishu(db: DatabaseManager) -> None:
    """【菜单 3】扫描飞书 IMAP 邮件并解析待办任务"""
    console.print("\n[bold cyan]═══ 扫描飞书待办 ═══[/]\n")
    try:
        parser = FeishuImapParser(db)
        count = parser.scan_and_parse()
        console.print(f"[green]✓ 本次解析并入库 {count} 条飞书待办任务[/]")
    except ConnectionError as e:
        console.print(f"[red]错误: IMAP 连接失败 — {e}[/]")
        logger.error("IMAP 连接失败: %s", e)
    except Exception as e:
        console.print(f"[red]错误: 飞书邮件解析失败 — {e}[/]")
        logger.exception("扫描飞书待办时发生异常")


def handle_intranet_scrape(db: DatabaseManager) -> None:
    """【菜单 4】启动 Selenium 内网爬虫"""
    console.print("\n[bold cyan]═══ 内网数据抓取 ═══[/]\n")
    try:
        scraper = IntranetScraper(db)
        scraper.run()
        console.print("[green]✓ 内网数据抓取完成[/]")
    except Exception as e:
        console.print(f"[red]错误: 内网抓取失败 — {e}[/]")
        logger.exception("内网数据抓取时发生异常")


def handle_project_overview(db: DatabaseManager) -> None:
    """【菜单 5】查看项目概览统计"""
    console.print("\n[bold cyan]═══ 项目概览 ═══[/]\n")
    try:
        with db.get_connection() as conn:
            # 项目统计
            projects = conn.execute(
                "SELECT status, COUNT(*) FROM projects GROUP BY status"
            ).fetchall()

            # 交付物统计
            deliverables = conn.execute(
                "SELECT status, COUNT(*) FROM deliverables GROUP BY status"
            ).fetchall()

            # 飞书待办统计
            feishu_total = conn.execute("SELECT COUNT(*) FROM feishu_tasks").fetchone()[0]
            feishu_synced = conn.execute(
                "SELECT COUNT(*) FROM feishu_tasks WHERE synced=1"
            ).fetchone()[0]

        from rich.table import Table

        table = Table(title="项目统计概览", show_lines=True)
        table.add_column("类别", style="cyan")
        table.add_column("状态", style="white")
        table.add_column("数量", justify="right", style="green")

        for status, count in projects:
            table.add_row("项目", status, str(count))
        for status, count in deliverables:
            table.add_row("交付物", status, str(count))
        table.add_row("飞书待办", "总计", str(feishu_total))
        table.add_row("飞书待办", "已同步", str(feishu_synced))

        console.print(table)

    except Exception as e:
        console.print(f"[red]错误: 查询概览失败 — {e}[/]")
        logger.exception("查看项目概览时发生异常")


def handle_exit(db: DatabaseManager) -> None:
    """【菜单 0】退出系统"""
    if Confirm.ask("确定要退出 VSE TOOLBOX 吗？", default=True):
        console.print("[bold green]再见！VSE TOOLBOX 已安全退出。[/]")
        logger.info("用户正常退出系统")
        sys.exit(0)
    # 用户选择不退出，回到主循环


def main() -> None:
    """CLI 主循环入口"""
    logger.info("VSE TOOLBOX 启动")
    show_banner()

    # 初始化数据库
    db = DatabaseManager()
    db.init_database()
    console.print("[dim]数据库已就绪[/]")

    # 主菜单循环
    while True:
        try:
            show_menu()
            choice = Prompt.ask(
                "[bold]请输入选项编号[/]",
                choices=list(MENU_OPTIONS.keys()),
                default="0",
            )

            label, handler_name = MENU_OPTIONS[choice]
            handler = globals().get(handler_name)

            if handler and callable(handler):
                handler(db)
            else:
                console.print(f"[red]内部错误: 处理函数 {handler_name} 未找到[/]")

        except KeyboardInterrupt:
            console.print("\n\n[bold green]收到中断信号，安全退出。[/]")
            logger.info("用户通过 Ctrl+C 中断退出")
            sys.exit(0)
        except EOFError:
            console.print("\n[bold green]输入流结束，安全退出。[/]")
            logger.info("EOF 输入流结束")
            sys.exit(0)
        except Exception as e:
            console.print(f"[red]未预期的错误: {e}[/]")
            logger.exception("主循环中发生未预期异常")


if __name__ == "__main__":
    main()
