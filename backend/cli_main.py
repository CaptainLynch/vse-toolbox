# -*- coding: utf-8 -*-
"""VSE TOOLBOX CLI 主入口。

两种运行模式:
    1. 交互式菜单模式 (默认)
       python backend/cli_main.py

    2. 静默定时跑批模式 (供 Windows 任务计划调度)
       python backend/cli_main.py --task=crawler
       python backend/cli_main.py --task=export

Phase 1 任务: CLI-01 ~ CLI-04
"""

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径初始化: 确保 backend/ 在 sys.path 中
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from config import DATA_DIR, LOGS_DIR, TEMP_DIR, safe_path  # noqa: F401 (safe_path 预留 R-01)
from services.crawler_service import get_driver_manager
from services.db import DBManager

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
APP_NAME = "VSE TOOLBOX"
APP_VERSION = "2.0-cli"
COPYRIGHT = "© 2026 VSE Project Team"

# 导出全量数据时使用的 size 上限
_EXPORT_ALL_SIZE = 99999

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

def setup_logging(silent: bool = False) -> None:
    """配置 CLI 日志: 文件 + 终端(非静默时)。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"cli_{datetime.now():%Y%m%d}.log"

    handlers: list[logging.Handler] = [
        logging.FileHandler(str(log_file), encoding="utf-8"),
    ]
    if not silent:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.WARNING)
        handlers.append(stream_handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# 临时文件清理 (R-06)
# ---------------------------------------------------------------------------

def cleanup_temp() -> None:
    """启动时清理 temp/ 中超过 24 小时的文件。"""
    if not TEMP_DIR.exists():
        return
    cutoff = time.time() - 86400
    for item in TEMP_DIR.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
        except Exception as e:
            logging.getLogger("cli.cleanup").warning("清理临时文件失败 %s: %s", item.name, e)


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def show_banner() -> None:
    width = 52
    print()
    print("=" * width)
    print(f"  {APP_NAME}  v{APP_VERSION}")
    print(f"  汽车项目管理桌面工具箱 - 中文终端")
    print(f"  {COPYRIGHT}")
    print("=" * width)
    print()


# ---------------------------------------------------------------------------
# 主菜单
# ---------------------------------------------------------------------------

def show_main_menu() -> None:
    print("-" * 40)
    print("  【主菜单】")
    print()
    print("  1. 🕷️  爬虫工具")
    print("  2. 📊  Excel 工具 (开发中)")
    print("  3. 📽️  PPT 生成  (开发中)")
    print("  0. 🚪  退出")
    print("-" * 40)


def handle_main_menu() -> bool:
    """显示主菜单并处理用户选择。返回 False 表示退出。"""
    show_main_menu()
    choice = input("请选择功能 [0-3]: ").strip()

    if choice == "1":
        handle_crawler_menu()
    elif choice == "2":
        print("\n⚠️  Excel 工具模块正在开发中，敬请期待！\n")
    elif choice == "3":
        print("\n⚠️  PPT 生成模块正在开发中，敬请期待！\n")
    elif choice == "0":
        return False
    else:
        print("\n⚠️  无效选项，请重新输入。\n")
    return True


# ---------------------------------------------------------------------------
# 爬虫子菜单 (CLI-02)
# ---------------------------------------------------------------------------

def show_crawler_menu() -> None:
    print()
    print("-" * 40)
    print("  【爬虫工具】")
    print()
    print("  1. 🔍  抓取页面内容")
    print("  2. 📋  提取页面表格")
    print("  3. 📦  全量数据导出")
    print("  0. ↩️  返回上级")
    print("-" * 40)


def handle_crawler_menu() -> None:
    """爬虫工具子菜单循环。"""
    dm = get_driver_manager()

    while True:
        show_crawler_menu()
        choice = input("请选择功能 [0-3]: ").strip()

        if choice == "1":
            _crawler_fetch_page(dm)
        elif choice == "2":
            _crawler_extract_table(dm)
        elif choice == "3":
            _crawler_full_export()
        elif choice == "0":
            break
        else:
            print("\n⚠️  无效选项，请重新输入。\n")


def _validate_url(url: str) -> bool:
    """校验 URL 协议安全性，仅允许 http/https (R-07 + 安全加固)。"""
    if not url.startswith(("http://", "https://")):
        print("⚠️  仅支持 http/https 协议，请重新输入。\n")
        return False
    return True


def _crawler_fetch_page(dm) -> None:
    """交互式抓取页面内容。"""
    print()
    url = input("请输入目标 URL (http/https): ").strip()
    if not url:
        print("⚠️  URL 不能为空。\n")
        return
    if not _validate_url(url):
        return

    print(f"\n⏳ 正在抓取: {url}")
    print("   (首次加载浏览器可能需要 10-20 秒...)\n")

    try:
        result = dm.fetch_page(url)
        print("✅ 抓取成功!")
        print(f"   标题: {result['title']}")
        print(f"   浏览器: {result['browser_used']}")
        print(f"   内容长度: {len(result['content'])} 字符")
        print(f"   实际 URL: {result['url']}")
    except Exception as e:
        logging.getLogger("cli.crawler").error("抓取失败: %s", e)
        print("❌ 抓取失败，请检查 URL 是否正确或浏览器驱动是否可用。")

    print()


def _crawler_extract_table(dm) -> None:
    """交互式提取页面表格。"""
    print()
    url = input("请输入目标 URL (http/https): ").strip()
    if not url:
        print("⚠️  URL 不能为空。\n")
        return
    if not _validate_url(url):
        return

    xpath = input("请输入 XPath (回车使用默认 //table): ").strip() or "//table"

    print(f"\n⏳ 正在提取表格: {url}")
    print(f"   XPath: {xpath}\n")

    try:
        result = dm.extract_table(url, xpath)
        if result["row_count"] == 0:
            print("⚠️  未找到匹配的表格。\n")
            return

        print("✅ 提取成功!")
        print(f"   表头: {result['headers']}")
        print(f"   数据行数: {result['row_count']}")

        preview_count = min(5, result["row_count"])
        print(f"\n   --- 前 {preview_count} 行预览 ---")
        for i, row in enumerate(result["rows"][:preview_count]):
            print(f"   [{i+1}] {row}")

        if result["row_count"] > preview_count:
            print(f"   ... 共 {result['row_count']} 行")

    except Exception as e:
        logging.getLogger("cli.crawler").error("表格提取失败: %s", e)
        print("❌ 表格提取失败，请检查 URL 和 XPath 是否正确。")

    print()


def _crawler_full_export() -> None:
    """全量数据导出 (CLI-03)。

    执行流程:
    1. 从数据库读取所有 issues/ewo_ncr/tir 数据
    2. 导出为 Excel 文件到 temp/ 目录
    3. 返回导出文件路径
    """
    print()
    print("⏳ 正在执行全量数据导出...\n")

    try:
        exported_tables = _collect_export_data()

        if not exported_tables:
            print("\n❌ 没有可导出的数据。\n")
            return

        output_path = _write_export_excel(exported_tables)
        if output_path:
            print(f"\n✅ 导出完成: {output_path}")
            print(f"   共导出 {len(exported_tables)} 个数据表")
        else:
            print("\n❌ Excel 写入失败，请检查日志。")

    except Exception as e:
        logging.getLogger("cli.export").error("全量导出异常: %s", e)
        print("\n❌ 导出失败，请查看日志获取详情。")

    print()


def _collect_export_data() -> list:
    """收集所有需要导出的数据表。返回 [(label, data, count), ...]。"""
    exported_tables = []

    for label, fetcher in [
        ("造车问题", lambda: DBManager.list_issues(page=1, size=_EXPORT_ALL_SIZE)),
        ("EWO/NCR", lambda: DBManager.list_ewos(page=1, size=_EXPORT_ALL_SIZE)),
        ("TIR", lambda: DBManager.list_tirs(page=1, size=_EXPORT_ALL_SIZE)),
    ]:
        try:
            data, total = fetcher()
            exported_tables.append((label, data, total))
            print(f"   ✅ {label}: {total} 条")
        except Exception as e:
            logging.getLogger("cli.export").warning("导出 %s 失败: %s", label, e)
            print(f"   ⚠️  {label} 导出失败，请检查日志。")

    return exported_tables


def _write_export_excel(exported_tables: list) -> str | None:
    """将导出的数据写入 Excel 文件。返回文件路径。"""
    try:
        import openpyxl
    except ImportError:
        logging.getLogger("cli.export").error("openpyxl 未安装")
        print("   ⚠️  openpyxl 未安装，无法生成 Excel 文件。")
        return None

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"vse_export_{timestamp}.xlsx"
    output_path = safe_path(filename, TEMP_DIR)

    wb = None
    try:
        wb = openpyxl.Workbook()
        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])

        for table_name, data, count in exported_tables:
            if not data:
                continue
            ws = wb.create_sheet(title=table_name[:31])

            if isinstance(data[0], dict):
                headers = list(data[0].keys())
            else:
                headers = [f"col_{i}" for i in range(len(data[0]))]

            for col_idx, header in enumerate(headers, 1):
                ws.cell(row=1, column=col_idx, value=str(header))

            for row_idx, record in enumerate(data, 2):
                if isinstance(record, dict):
                    for col_idx, key in enumerate(headers, 1):
                        val = record.get(key)
                        ws.cell(row=row_idx, column=col_idx, value=str(val) if val is not None else "")
                else:
                    for col_idx, val in enumerate(record, 1):
                        ws.cell(row=row_idx, column=col_idx, value=str(val) if val is not None else "")

        wb.save(str(output_path))
        return str(output_path)
    except Exception as e:
        logging.getLogger("cli.export").error("写入 Excel 失败: %s", e)
        return None
    finally:
        if wb is not None:
            wb.close()


# ---------------------------------------------------------------------------
# 静默跑批模式 (CLI-04)
# ---------------------------------------------------------------------------

def run_silent(task: str) -> int:
    """静默定时任务调度入口。

    Args:
        task: 任务名称。支持 'crawler' / 'export'。

    Returns:
        退出码。0=成功，1=失败。
    """
    logger = logging.getLogger("cli.silent")
    logger.info("静默模式启动，任务: %s", task)

    try:
        if task == "export":
            _silent_export(logger)
            return 0
        elif task == "crawler":
            # Phase 1: 静默爬虫等同于全量导出（从 DB 读取已抓取数据）
            # 后续 Phase 可扩展为实时爬虫抓取 + DB 写入
            logger.info("crawler 任务: 执行全量数据导出")
            _silent_export(logger)
            return 0
        else:
            logging.getLogger("cli.silent").warning("未知任务: %s", task)
            print(f"❌ 未知任务: {task}，支持: crawler, export", file=sys.stderr)
            return 1
    except Exception as e:
        logger.exception("静默任务失败")
        print("❌ 任务执行失败，请查看日志获取详情。", file=sys.stderr)
        return 1


def _silent_export(logger: logging.Logger) -> None:
    """静默模式全量导出，不打印到终端，仅写日志。"""
    logger.info("开始全量数据导出...")

    exported_tables = []

    for label, fetcher in [
        ("造车问题", lambda: DBManager.list_issues(page=1, size=_EXPORT_ALL_SIZE)),
        ("EWO/NCR", lambda: DBManager.list_ewos(page=1, size=_EXPORT_ALL_SIZE)),
        ("TIR", lambda: DBManager.list_tirs(page=1, size=_EXPORT_ALL_SIZE)),
    ]:
        try:
            data, total = fetcher()
            exported_tables.append((label, data, total))
            logger.info("导出 %s: %d 条", label, total)
        except Exception as e:
            logger.warning("导出 %s 失败: %s", label, e)

    if not exported_tables:
        logger.warning("没有可导出的数据")
        return

    output_path = _write_export_excel(exported_tables)
    if output_path:
        logger.info("导出完成: %s", output_path)
    else:
        logger.error("Excel 写入失败")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vse-cli",
        description=f"{APP_NAME} v{APP_VERSION} - 汽车项目管理桌面工具箱 (中文终端)",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        choices=["crawler", "export"],
        help="静默模式: 指定定时任务名称 (crawler=全量导出, export=全量导出)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} v{APP_VERSION}",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # 1. 初始化
    silent = args.task is not None
    setup_logging(silent=silent)
    cleanup_temp()

    # 2. 模式分发
    if silent:
        return run_silent(args.task)

    # 3. 交互式模式
    show_banner()
    print("欢迎使用 VSE TOOLBOX CLI！")
    print("输入数字选择功能，输入 0 返回/退出。\n")

    try:
        while handle_main_menu():
            pass
    except KeyboardInterrupt:
        print("\n\n👋 用户中断，正在退出...")
    except Exception as e:
        logging.getLogger("cli").exception("主循环异常")
        print("\n❌ 程序异常，请查看日志获取详情。")

    # 4. 清理
    print(f"\n感谢使用 {APP_NAME}，再见！👋\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())