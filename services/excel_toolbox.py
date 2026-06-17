# -*- coding: utf-8 -*-
"""
services/excel_toolbox.py — P0 Excel 工具箱（全 win32com COM 自动化）

职责:
    1. 多 .xlsx 文件纵向追加合并（merge_append）
    2. 坐标重合覆盖合并（merge_overlay）
    3. 单元格级差异比对并高亮（diff_against_baseline）
    4. 莫兰迪色板高亮 + 图例说明 Sheet
    5. 改写前磁盘 .bak 备份 + 异常回滚

架构约束:
    - 禁止 import rich / flask / 任何界面库
    - 禁止 import pandas / openpyxl / python-pptx（DLP 透明加密绕过）
    - 无 DatabaseManager 依赖（纯文件工具）
    - 所有 COM 操作在 try…finally 释放（Close+Quit+del）
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import BACKUP_DIR, OUTPUT_DIR

logger = logging.getLogger("vse_toolbox.excel_toolbox")

# ── 莫兰迪低饱和色板（BGR 十进制，COM Interior.Color 用 BGR）────────
# 顺序: 藕粉 · 灰蓝 · 薄荷 · 米杏 · 丁香紫 · 橄榄 · 月白 · 玫瑰灰
MORANDI_PALETTE: list[int] = [
    0xC5B8C8,
    0xC4B8A8,
    0xA8C4B8,
    0xB8C4D8,
    0xC8B8A8,
    0xA8B8A8,
    0xD8D0C0,
    0xB8A8B0,
]

# ── 延迟导入 win32com（仅 Windows 可用）───────────────────────────
_win32com: Any = None


def _get_win32com() -> Any:
    """延迟导入 win32com.client，避免非 Windows 平台导入失败。"""
    global _win32com
    if _win32com is None:
        try:
            import win32com.client as wc
            _win32com = wc
        except ImportError:
            raise ImportError(
                "pywin32 未安装，请执行: pip install pywin32 "
                "并运行 python Scripts/pywin32_postinstall.py -install"
            )
    return _win32com


class ExcelToolbox:
    """
    Excel 工具箱（win32com COM 自动化）

    无 DatabaseManager 依赖，纯文件级别操作：合并、比对、备份/回滚。
    """

    def __init__(self) -> None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # 实例级 color_map，在一次 merge/diff 操作内贯穿高亮与图例
        self._color_map: dict[str, int] = {}
        self._palette_idx: int = 0

    # ────────────────────────── 辅助：路径 ──────────────────────────

    @staticmethod
    def _to_absolute(path: Path) -> str:
        """返回绝对路径字符串（COM 接口要求）。"""
        return str(path.resolve())

    @staticmethod
    def _check_file_not_locked(file_path: Path) -> bool:
        """检查文件是否被其他进程占用（True = 可写）。"""
        if not file_path.exists():
            return True
        try:
            with open(file_path, "r+b"):
                pass
            return True
        except (PermissionError, IOError):
            return False

    @staticmethod
    def _auto_output_name(src: Path, suffix: str = "-汇总") -> Path:
        """在 OUTPUT_DIR 下，以 src 文件名 + suffix 生成默认输出路径。"""
        return OUTPUT_DIR / (src.stem + suffix + src.suffix)

    # ────────────────────────── 辅助：备份/回滚 ─────────────────────

    def _backup(self, target: Path) -> Path:
        """
        将 target 文件备份到 BACKUP_DIR。

        Returns:
            备份文件路径

        Raises:
            FileNotFoundError: target 不存在
        """
        if not target.exists():
            raise FileNotFoundError(f"备份目标不存在: {target}")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{target.name}.{ts}.bak"
        shutil.copy2(target, backup_path)
        logger.info("备份完成: %s → %s", target, backup_path)
        return backup_path

    def _rollback(self, target: Path, backup: Path) -> None:
        """将 backup 文件复制回 target（备份缺失则记录并静默返回）。"""
        if not backup.exists():
            logger.warning("回滚备份文件不存在，跳过回滚: %s", backup)
            return
        shutil.copy2(backup, target)
        logger.info("回滚完成: %s → %s", backup, target)

    # ────────────────────────── 辅助：颜色 ──────────────────────────

    def _highlight_cell(
        self, sheet: Any, row: int, col: int, source_tag: str
    ) -> None:
        """
        按 source_tag 分配/复用莫兰迪色并写入单元格底色。

        写入前读取原底色，若撞色则顺延取色板下一色。
        """
        # 分配/复用颜色
        if source_tag not in self._color_map:
            color = MORANDI_PALETTE[self._palette_idx % len(MORANDI_PALETTE)]
            # 防撞色：读取目标单元格当前底色
            try:
                existing_color = sheet.Cells(row, col).Interior.Color
            except Exception:
                existing_color = -1
            # 若撞色，顺延取下一色
            attempts = 0
            while existing_color == color and attempts < len(MORANDI_PALETTE):
                self._palette_idx += 1
                color = MORANDI_PALETTE[self._palette_idx % len(MORANDI_PALETTE)]
                attempts += 1
            if attempts == len(MORANDI_PALETTE):
                logger.warning("色板耗尽，无可用非冲突色: row=%d col=%d，将使用当前色", row, col)
            self._color_map[source_tag] = color
            self._palette_idx += 1

        sheet.Cells(row, col).Interior.Color = self._color_map[source_tag]

    def _write_legend(self, workbook: Any, color_map: dict[str, int]) -> None:
        """在 workbook 中新增「图例说明」Sheet，逐行写来源标签 ↔ 色块。"""
        legend_sheet = workbook.Sheets.Add()
        legend_sheet.Name = "图例说明"
        legend_sheet.Cells(1, 1).Value = "来源标签"
        legend_sheet.Cells(1, 2).Value = "颜色示例"
        legend_sheet.Cells(1, 1).Font.Bold = True
        legend_sheet.Cells(1, 2).Font.Bold = True
        for row_idx, (tag, color) in enumerate(color_map.items(), start=2):
            legend_sheet.Cells(row_idx, 1).Value = tag
            legend_sheet.Cells(row_idx, 2).Interior.Color = color

    def _reset_color_state(self) -> None:
        """每次 merge/diff 操作开始前重置颜色分配状态。"""
        self._color_map = {}
        self._palette_idx = 0

    # ────────────────────────── 来源收集 ────────────────────────────

    def collect_sources(
        self,
        paths: list[Path] | None = None,
        directory: Path | None = None,
    ) -> list[Path]:
        """
        汇总显式文件列表 + 扫描目录下 *.xlsx/*.xls，去重排序返回。

        Args:
            paths:     显式文件路径列表
            directory: 要扫描的目录

        Returns:
            去重后按路径排序的文件列表
        """
        result: set[Path] = set()
        if paths:
            for p in paths:
                p = Path(p)
                if p.is_file():
                    result.add(p.resolve())
                else:
                    logger.warning("来源文件不存在，已跳过: %s", p)
        if directory:
            directory = Path(directory)
            for ext in ("*.xlsx", "*.xls"):
                for f in directory.glob(ext):
                    result.add(f.resolve())
        return sorted(result)

    # ────────────────────────── merge_append ────────────────────────

    def merge_append(
        self,
        sources: list[Path],
        output_path: Path | None = None,
        baseline: Path | None = None,
    ) -> Path:
        """
        纵向追加合并：将各 source 的行依次追加到同一工作簿。

        Args:
            sources:     源文件列表
            output_path: 输出路径（None 时自动生成）
            baseline:    基线文件；非空时对新增/变更行高亮并写图例

        Returns:
            输出文件路径

        Raises:
            PermissionError: 输出文件被占用
            FileNotFoundError: 来源文件不存在
        """
        if not sources:
            raise ValueError("sources 不能为空")
        if output_path is None:
            output_path = self._auto_output_name(sources[0])
        output_path = Path(output_path)

        if not self._check_file_not_locked(output_path):
            raise PermissionError(f"输出文件被占用: {output_path}")

        backup: Path | None = None
        if output_path.exists():
            backup = self._backup(output_path)

        self._reset_color_state()
        wc = _get_win32com()
        excel = workbook = None
        try:
            excel = wc.Dispatch("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            workbook = excel.Workbooks.Add()
            out_sheet = workbook.ActiveSheet
            out_sheet.Name = "合并汇总"
            write_row = 1

            # 读取 baseline 数据用于差异比对
            baseline_data: dict[int, Any] = {}
            if baseline is not None:
                baseline = Path(baseline)
                bl_wb = None
                try:
                    bl_wb = excel.Workbooks.Open(self._to_absolute(baseline))
                    bl_sheet = bl_wb.Sheets(1)
                    used = bl_sheet.UsedRange
                    for r in range(1, used.Rows.Count + 1):
                        row_vals = tuple(
                            bl_sheet.Cells(r, c).Value
                            for c in range(1, used.Columns.Count + 1)
                        )
                        baseline_data[r] = row_vals
                finally:
                    if bl_wb is not None:
                        try:
                            bl_wb.Close(SaveChanges=0)
                        except Exception:
                            pass

            for src in sources:
                src = Path(src)
                src_tag = src.stem
                src_wb = None
                try:
                    src_wb = excel.Workbooks.Open(self._to_absolute(src))
                    src_sheet = src_wb.Sheets(1)
                    used = src_sheet.UsedRange

                    for r in range(1, used.Rows.Count + 1):
                        for c in range(1, used.Columns.Count + 1):
                            val = src_sheet.Cells(r, c).Value
                            out_sheet.Cells(write_row, c).Value = val
                            # 高亮差异行
                            if baseline is not None:
                                bl_row = baseline_data.get(write_row)
                                bl_val = bl_row[c - 1] if bl_row and c - 1 < len(bl_row) else None
                                if val != bl_val:
                                    self._highlight_cell(out_sheet, write_row, c, src_tag)
                        write_row += 1
                finally:
                    if src_wb is not None:
                        try:
                            src_wb.Close(SaveChanges=0)
                        except Exception:
                            pass

            if baseline is not None and self._color_map:
                self._write_legend(workbook, self._color_map)

            workbook.SaveAs(self._to_absolute(output_path), FileFormat=51)
            logger.info("merge_append 完成: %s", output_path)
            return output_path

        except Exception:
            if backup is not None:
                self._rollback(output_path, backup)
            raise

        finally:
            if workbook is not None:
                try:
                    workbook.Close(SaveChanges=0)
                except Exception as _e:
                    logger.debug("merge_append: workbook.Close 失败（可忽略）: %s", _e)
            if excel is not None:
                try:
                    excel.Quit()
                except Exception as _e:
                    logger.debug("merge_append: excel.Quit 失败（可忽略）: %s", _e)
            del workbook
            del excel

    # ────────────────────────── merge_overlay ───────────────────────

    def merge_overlay(
        self,
        sources: list[Path],
        target: Path,
        output_path: Path | None = None,
        baseline: Path | None = None,
    ) -> Path:
        """
        坐标重合覆盖合并：以 target 为底，各 source 按相同单元格坐标覆盖写入。

        Args:
            sources:     覆盖来源文件列表
            target:      底层目标文件
            output_path: 输出路径（None → 覆盖 target）
            baseline:    基线；非空时对变更格高亮并写图例

        Returns:
            输出文件路径
        """
        target = Path(target)
        if not target.exists():
            raise FileNotFoundError(f"target 文件不存在: {target}")

        if output_path is None:
            output_path = target
        output_path = Path(output_path)

        if not self._check_file_not_locked(output_path):
            raise PermissionError(f"输出文件被占用: {output_path}")

        backup: Path | None = None
        if output_path.exists():
            backup = self._backup(output_path)

        # 若输出与 target 不同，先复制 target 到 output
        if output_path.resolve() != target.resolve():
            shutil.copy2(target, output_path)

        self._reset_color_state()
        wc = _get_win32com()
        excel = workbook = None
        try:
            excel = wc.Dispatch("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            workbook = excel.Workbooks.Open(self._to_absolute(output_path))
            out_sheet = workbook.Sheets(1)

            # 读取 baseline 数据
            baseline_data: dict[tuple[int, int], Any] = {}
            if baseline is not None:
                baseline = Path(baseline)
                bl_wb = None
                try:
                    bl_wb = excel.Workbooks.Open(self._to_absolute(baseline))
                    bl_sheet = bl_wb.Sheets(1)
                    used_bl = bl_sheet.UsedRange
                    for r in range(1, used_bl.Rows.Count + 1):
                        for c in range(1, used_bl.Columns.Count + 1):
                            baseline_data[(r, c)] = bl_sheet.Cells(r, c).Value
                finally:
                    if bl_wb is not None:
                        try:
                            bl_wb.Close(SaveChanges=0)
                        except Exception:
                            pass

            for src in sources:
                src = Path(src)
                src_tag = src.stem
                src_wb = None
                try:
                    src_wb = excel.Workbooks.Open(self._to_absolute(src))
                    src_sheet = src_wb.Sheets(1)
                    used = src_sheet.UsedRange

                    for r in range(1, used.Rows.Count + 1):
                        for c in range(1, used.Columns.Count + 1):
                            val = src_sheet.Cells(r, c).Value
                            out_sheet.Cells(r, c).Value = val
                            if baseline is not None:
                                bl_val = baseline_data.get((r, c))
                                if val != bl_val:
                                    self._highlight_cell(out_sheet, r, c, src_tag)
                finally:
                    if src_wb is not None:
                        try:
                            src_wb.Close(SaveChanges=0)
                        except Exception:
                            pass

            if baseline is not None and self._color_map:
                self._write_legend(workbook, self._color_map)

            workbook.SaveAs(self._to_absolute(output_path), FileFormat=51)
            logger.info("merge_overlay 完成: %s", output_path)
            return output_path

        except Exception:
            if backup is not None:
                self._rollback(output_path, backup)
            raise

        finally:
            if workbook is not None:
                try:
                    workbook.Close(SaveChanges=0)
                except Exception as _e:
                    logger.debug("merge_overlay: workbook.Close 失败（可忽略）: %s", _e)
            if excel is not None:
                try:
                    excel.Quit()
                except Exception as _e:
                    logger.debug("merge_overlay: excel.Quit 失败（可忽略）: %s", _e)
            del workbook
            del excel

    # ────────────────────────── diff_against_baseline ───────────────

    def diff_against_baseline(
        self,
        target: Path,
        baseline: Path,
        output_path: Path | None = None,
    ) -> Path:
        """
        逐单元格比对 .Value 与 .Formula；差异格高亮并输出标注副本。

        color_map 语义标签：「新增」/ 「修改」/ 「删除」。

        Args:
            target:      待比对文件（只读用于比对，写入 output）
            baseline:    基线文件（只读）
            output_path: 输出路径（None 时自动生成）

        Returns:
            输出文件路径
        """
        target = Path(target)
        baseline = Path(baseline)
        if not target.exists():
            raise FileNotFoundError(f"target 文件不存在: {target}")
        if not baseline.exists():
            raise FileNotFoundError(f"baseline 文件不存在: {baseline}")

        if output_path is None:
            output_path = self._auto_output_name(target, suffix="-比对")
        output_path = Path(output_path)

        if not self._check_file_not_locked(output_path):
            raise PermissionError(f"输出文件被占用: {output_path}")

        backup: Path | None = None
        if output_path.exists():
            backup = self._backup(output_path)

        # 先复制 target 到 output（baseline 只读）
        shutil.copy2(target, output_path)

        self._reset_color_state()
        wc = _get_win32com()
        excel = out_wb = bl_wb = None
        try:
            excel = wc.Dispatch("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            out_wb = excel.Workbooks.Open(self._to_absolute(output_path))
            bl_wb = excel.Workbooks.Open(self._to_absolute(baseline))

            out_sheet = out_wb.Sheets(1)
            bl_sheet = bl_wb.Sheets(1)

            out_used = out_sheet.UsedRange
            bl_used = bl_sheet.UsedRange
            max_row = max(out_used.Rows.Count, bl_used.Rows.Count)
            max_col = max(out_used.Columns.Count, bl_used.Columns.Count)

            for r in range(1, max_row + 1):
                for c in range(1, max_col + 1):
                    try:
                        tgt_val = out_sheet.Cells(r, c).Value
                        tgt_formula = out_sheet.Cells(r, c).Formula
                    except Exception:
                        tgt_val = tgt_formula = None
                    try:
                        bl_val = bl_sheet.Cells(r, c).Value
                        bl_formula = bl_sheet.Cells(r, c).Formula
                    except Exception:
                        bl_val = bl_formula = None

                    if tgt_val is None and tgt_formula in (None, ""):
                        if bl_val is not None or (bl_formula not in (None, "")):
                            self._highlight_cell(out_sheet, r, c, "删除")
                    elif bl_val is None and bl_formula in (None, ""):
                        self._highlight_cell(out_sheet, r, c, "新增")
                    elif tgt_val != bl_val or tgt_formula != bl_formula:
                        self._highlight_cell(out_sheet, r, c, "修改")

            bl_wb.Close(SaveChanges=0)
            bl_wb = None

            if self._color_map:
                self._write_legend(out_wb, self._color_map)

            out_wb.SaveAs(self._to_absolute(output_path), FileFormat=51)
            logger.info("diff_against_baseline 完成: %s", output_path)
            return output_path

        except Exception:
            if backup is not None:
                self._rollback(output_path, backup)
            raise

        finally:
            if bl_wb is not None:
                try:
                    bl_wb.Close(SaveChanges=0)
                except Exception as _e:
                    logger.debug("diff: bl_wb.Close 失败（可忽略）: %s", _e)
            if out_wb is not None:
                try:
                    out_wb.Close(SaveChanges=0)
                except Exception as _e:
                    logger.debug("diff: out_wb.Close 失败（可忽略）: %s", _e)
            if excel is not None:
                try:
                    excel.Quit()
                except Exception as _e:
                    logger.debug("diff: excel.Quit 失败（可忽略）: %s", _e)
            del out_wb
            del bl_wb
            del excel
