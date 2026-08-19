# -*- coding: utf-8 -*-
"""
services/office_toolbox.py — Office 文档操作工具箱 (COM 自动化版)

职责:
    1. 基于 SQLite 中的最新数据刷新周报 PPT 模板
    2. 封装 win32com.client 的 Excel / PowerPoint COM 操作
    3. 导出交付物清单为 Excel 文件

设计要点:
    - **核心禁令**: 禁止使用 pandas / openpyxl / python-pptx 直接读写文件
      （公司 DLP 透明加密会导致乱码）。必须通过 win32com 调用本地 Office 进程。
    - 所有 COM 操作必须在 try...finally 中确保 Workbook.Close / Application.Quit，
      防止残留幽灵 Excel/PowerPoint 进程。
    - 文件操作前检查是否被占用。
    - 使用 pathlib 处理所有路径，兼容中文。

依赖:
    - pywin32 (win32com.client)
    - core.db_manager (数据源)
"""

import logging
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

from rich.console import Console

from core.db_manager import DatabaseManager
from core.runtime_paths import app_root

logger = logging.getLogger("vse_toolbox.office_toolbox")
console = Console()

# ── 默认路径配置 ────────────────────────────────────────────────
PROJECT_ROOT = app_root()
TEMPLATE_DIR = PROJECT_ROOT / "data" / "templates"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

DEFAULT_PPT_TEMPLATE = TEMPLATE_DIR / "weekly_report_template.pptx"
DEFAULT_EXCEL_TEMPLATE = TEMPLATE_DIR / "deliverables_template.xlsx"

# ── 延迟导入 win32com（仅 Windows 可用）────────────────────────
_win32com: Any = None


def _get_win32com() -> Any:
    """延迟导入 win32com.client，避免非 Windows 平台导入失败"""
    global _win32com
    if _win32com is None:
        try:
            import win32com.client as wc
            _win32com = wc
        except ImportError:
            console.print("[red]错误: 未安装 pywin32，请执行:[/]")
            console.print("[red]  pip install pywin32[/]")
            raise
    return _win32com


class OfficeToolbox:
    """
    Office 文档操作工具箱 (COM 自动化)

    通过 win32com.client 驱动本地 Office 进程完成 Excel / PPT 操作，
    绕过 DLP 透明加密导致的文件乱码问题。

    用法:
        toolbox = OfficeToolbox(db_manager)
        ppt_path = toolbox.refresh_weekly_ppt()
        xlsx_path = toolbox.export_deliverables_excel()
    """

    def __init__(self, db: DatabaseManager) -> None:
        """
        初始化 Office 工具箱。

        Args:
            db: 数据库管理器实例
        """
        self._db = db
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    # ── 辅助方法 ───────────────────────────────────────────────

    @staticmethod
    def _check_file_not_locked(file_path: Path) -> bool:
        """
        检查文件是否被其他进程占用。

        Args:
            file_path: 要检查的文件路径

        Returns:
            True 如果文件可写（未被锁定），False 如果被占用
        """
        if not file_path.exists():
            return True
        try:
            with open(file_path, "r+b") as f:
                pass
            return True
        except (PermissionError, IOError):
            return False

    @staticmethod
    def _to_absolute(path: Path) -> str:
        """
        将 Path 转为绝对路径字符串（COM 接口要求绝对路径）。

        Args:
            path: 文件路径

        Returns:
            绝对路径字符串
        """
        return str(path.resolve())

    # ── 数据查询 ───────────────────────────────────────────────

    def _fetch_deliverables(self) -> list[dict]:
        """
        从 SQLite 中查询所有交付物数据（附带项目信息）。

        Returns:
            交付物字典列表
        """
        try:
            with self._db.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        p.name    AS project_name,
                        p.manager AS project_manager,
                        d.name    AS deliverable_name,
                        d.owner,
                        d.due_date,
                        d.status,
                        d.remark,
                        d.updated_at
                    FROM deliverables d
                    JOIN projects p ON d.project_id = p.id
                    ORDER BY d.due_date ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            console.print(f"[red]错误: 查询交付物数据失败 — {e}[/]")
            logger.exception("查询交付物数据失败")
            raise

    def _fetch_feishu_summary(self) -> list[dict]:
        """
        从 SQLite 中查询飞书待办汇总。

        Returns:
            待办字典列表
        """
        try:
            with self._db.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT title, assignee, deadline, synced
                    FROM feishu_tasks
                    ORDER BY deadline ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.exception("查询飞书待办失败")
            return []

    # ── Excel 操作 (COM) ───────────────────────────────────────

    def export_deliverables_excel(self, output_path: Optional[Path] = None) -> Path:
        """
        将交付物数据导出为 Excel 文件，通过 Excel.Application COM 自动化。

        Args:
            output_path: 输出文件路径。为 None 时使用默认路径。

        Returns:
            生成的 Excel 文件路径

        Raises:
            PermissionError: 输出文件被占用
            ImportError: pywin32 未安装
            com_error: COM 调用失败
        """
        wc = _get_win32com()

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = OUTPUT_DIR / f"交付物清单_{timestamp}.xlsx"

        output_path = Path(output_path)

        # 检查文件是否被占用
        if not self._check_file_not_locked(output_path):
            error_msg = f"文件 {output_path} 正在被其他程序使用，请关闭后重试"
            console.print(f"[red]错误: {error_msg}[/]")
            raise PermissionError(error_msg)

        # 查询数据
        data = self._fetch_deliverables()
        if not data:
            console.print("[yellow]警告: 无交付物数据可导出[/]")

        # ── COM 自动化: 启动 Excel ──────────────────────────
        excel = None
        workbook = None
        try:
            console.print("[dim]正在启动 Excel 进程...[/]")
            excel = wc.Dispatch("Excel.Application")
            excel.Visible = False       # 后台运行
            excel.DisplayAlerts = False  # 抑制弹窗

            # 新建工作簿
            workbook = excel.Workbooks.Add()
            sheet = workbook.ActiveSheet
            sheet.Name = "交付物清单"

            # 写入表头
            headers = [
                "项目名称", "项目经理", "交付物名称",
                "负责人", "截止日期", "状态", "备注", "更新时间",
            ]
            for col_idx, header in enumerate(headers, start=1):
                sheet.Cells(1, col_idx).Value = header
                # 表头加粗
                sheet.Cells(1, col_idx).Font.Bold = True

            # 写入数据行
            status_map = {
                "pending": "待开始",
                "in_progress": "进行中",
                "done": "已完成",
                "blocked": "阻塞",
            }
            for row_idx, item in enumerate(data, start=2):
                sheet.Cells(row_idx, 1).Value = item.get("project_name", "")
                sheet.Cells(row_idx, 2).Value = item.get("project_manager", "")
                sheet.Cells(row_idx, 3).Value = item.get("deliverable_name", "")
                sheet.Cells(row_idx, 4).Value = item.get("owner", "")
                sheet.Cells(row_idx, 5).Value = item.get("due_date", "")
                raw_status = item.get("status", "")
                sheet.Cells(row_idx, 6).Value = status_map.get(raw_status, raw_status)
                sheet.Cells(row_idx, 7).Value = item.get("remark", "")
                sheet.Cells(row_idx, 8).Value = item.get("updated_at", "")

            # 自动调整列宽
            sheet.Columns("A:H").AutoFit()

            # 保存为 xlsx (FileFormat=51)
            abs_path = self._to_absolute(output_path)
            workbook.SaveAs(abs_path, FileFormat=51)

            console.print(f"[green]✓ Excel 已导出: {output_path}[/]")
            logger.info("Excel 导出完成: %s", output_path)
            return output_path

        except Exception as e:
            console.print(f"[red]错误: Excel 导出失败 — {e}[/]")
            logger.exception("Excel 导出失败")
            raise

        finally:
            # 确保 Workbook 和 Excel 进程正确退出，防止幽灵进程
            if workbook is not None:
                try:
                    workbook.Close(SaveChanges=0)  # 0 = 不保存
                except Exception:
                    pass
            if excel is not None:
                try:
                    excel.Quit()
                except Exception:
                    pass
            # 释放 COM 对象引用
            del workbook
            del excel
            console.print("[dim]Excel 进程已释放[/]")

    # ── PPT 操作 (COM) ─────────────────────────────────────────

    def refresh_weekly_ppt(
        self,
        template_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        基于 PPT 模板和 SQLite 最新数据生成周报 PPT，通过 PowerPoint.Application COM 自动化。

        工作流程:
            1. 检查模板文件是否存在
            2. 检查输出文件是否被占用
            3. 复制模板到输出路径
            4. 用 PowerPoint COM 打开并替换占位符 / 填充表格

        Args:
            template_path: PPT 模板路径。为 None 时使用默认模板。
            output_path: 输出路径。为 None 时使用时间戳命名。

        Returns:
            生成的 PPT 文件路径

        Raises:
            FileNotFoundError: 模板文件不存在
            PermissionError: 输出文件被占用
            com_error: COM 调用失败
        """
        wc = _get_win32com()

        if template_path is None:
            template_path = DEFAULT_PPT_TEMPLATE

        template_path = Path(template_path)

        # 检查模板是否存在
        if not template_path.exists():
            error_msg = f"PPT 模板文件不存在: {template_path}"
            console.print(f"[red]错误: {error_msg}[/]")
            console.print("[yellow]请将周报 PPT 模板放置到以下目录:[/]")
            console.print(f"[yellow]  {TEMPLATE_DIR}[/]")
            raise FileNotFoundError(error_msg)

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = OUTPUT_DIR / f"周报_{timestamp}.pptx"

        output_path = Path(output_path)

        # 检查输出文件是否被占用
        if not self._check_file_not_locked(output_path):
            error_msg = f"文件 {output_path} 正在被其他程序使用，请关闭后重试"
            console.print(f"[red]错误: {error_msg}[/]")
            raise PermissionError(error_msg)

        # 复制模板到输出路径
        try:
            shutil.copy2(str(template_path), str(output_path))
        except (shutil.Error, IOError) as e:
            console.print(f"[red]错误: 模板复制失败 — {e}[/]")
            raise

        # 查询最新数据
        deliverables = self._fetch_deliverables()
        feishu_tasks = self._fetch_feishu_summary()
        current_date = datetime.now().strftime("%Y年%m月%d日")

        # 占位符映射
        placeholder_map = {
            "{{日期}}": current_date,
            "{{交付物总数}}": str(len(deliverables)),
            "{{待办总数}}": str(len(feishu_tasks)),
            "{{已完成数}}": str(
                sum(1 for d in deliverables if d.get("status") == "done")
            ),
        }

        # ── COM 自动化: 启动 PowerPoint ─────────────────────
        ppt_app = None
        presentation = None
        try:
            console.print("[dim]正在启动 PowerPoint 进程...[/]")
            ppt_app = wc.Dispatch("PowerPoint.Application")
            ppt_app.Visible = True  # PowerPoint COM 要求 Visible=True

            abs_output = self._to_absolute(output_path)
            presentation = ppt_app.Presentations.Open(abs_output, WithWindow=False)

            # 遍历所有幻灯片，替换占位符和填充表格
            for slide_idx in range(1, presentation.Slides.Count + 1):
                slide = presentation.Slides(slide_idx)

                for shape_idx in range(1, slide.Shapes.Count + 1):
                    shape = slide.Shapes(shape_idx)

                    # 替换文本框中的占位符
                    if shape.HasTextFrame:
                        text_frame = shape.TextFrame
                        for para_idx in range(1, text_frame.TextRange.Paragraphs().Count + 1):
                            para = text_frame.TextRange.Paragraphs(para_idx)
                            text = para.Text
                            for placeholder, value in placeholder_map.items():
                                if placeholder in text:
                                    # 使用 Replace 方法整体替换
                                    text = text.replace(placeholder, value)
                            # 回写替换后的文本
                            para.Text = text

                    # 如果有表格，填充交付物数据
                    if shape.HasTable:
                        table = shape.Table
                        col_count = table.Columns.Count
                        if col_count >= 4:
                            # 保留表头（第 1 行），删除其余行
                            while table.Rows.Count > 1:
                                table.Rows(table.Rows.Count).Delete()

                            # 填充实际数据
                            for item in deliverables:
                                # 添加新行
                                new_row = table.Rows.Add()
                                row_idx = table.Rows.Count
                                table.Cell(row_idx, 1).Shape.TextFrame.TextRange.Text = (
                                    item.get("deliverable_name", "")
                                )
                                table.Cell(row_idx, 2).Shape.TextFrame.TextRange.Text = (
                                    item.get("owner", "")
                                )
                                table.Cell(row_idx, 3).Shape.TextFrame.TextRange.Text = (
                                    item.get("status", "")
                                )
                                table.Cell(row_idx, 4).Shape.TextFrame.TextRange.Text = (
                                    item.get("due_date", "")
                                )

            # 保存
            presentation.Save()

            console.print(f"[green]✓ 周报 PPT 已生成: {output_path}[/]")
            logger.info("周报 PPT 生成完成: %s", output_path)
            return output_path

        except Exception as e:
            console.print(f"[red]错误: PPT 生成失败 — {e}[/]")
            logger.exception("PPT 生成失败")
            raise

        finally:
            # 确保 PowerPoint 进程正确退出
            if presentation is not None:
                try:
                    presentation.Close()
                except Exception:
                    pass
            if ppt_app is not None:
                try:
                    ppt_app.Quit()
                except Exception:
                    pass
            del presentation
            del ppt_app
            console.print("[dim]PowerPoint 进程已释放[/]")


# ── 独立运行测试入口 ────────────────────────────────────────────
if __name__ == "__main__":
    console.print("[bold cyan]OfficeToolbox (COM) 独立测试[/]\n")

    test_db = DatabaseManager()
    test_db.init_database()

    toolbox = OfficeToolbox(test_db)

    # 测试 Excel 导出
    try:
        xlsx_path = toolbox.export_deliverables_excel()
        console.print(f"[green]Excel 测试通过: {xlsx_path}[/]")
    except Exception as e:
        console.print(f"[yellow]Excel 测试跳过: {e}[/]")

    # 测试 PPT 生成
    try:
        ppt_path = toolbox.refresh_weekly_ppt()
        console.print(f"[green]PPT 测试通过: {ppt_path}[/]")
    except FileNotFoundError:
        console.print("[yellow]PPT 测试跳过: 模板文件不存在[/]")
    except Exception as e:
        console.print(f"[yellow]PPT 测试跳过: {e}[/]")

    console.print("\n[green]测试完成[/]")
