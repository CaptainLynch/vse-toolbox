# -*- coding: utf-8 -*-
"""P0 Excel toolbox backed by xlwings and native Excel SaveAs."""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import BACKUP_DIR, OUTPUT_DIR

logger = logging.getLogger("vse_toolbox.excel_toolbox")

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

_xlwings: Any = None


def _get_xlwings() -> Any:
    """Lazily import xlwings so tests can monkeypatch the Excel bridge."""
    global _xlwings
    if _xlwings is None:
        try:
            import xlwings as xw
        except ImportError as exc:
            raise ImportError("xlwings is not installed; run: pip install xlwings") from exc
        _xlwings = xw
    return _xlwings


class ExcelToolbox:
    """File-level Excel merge, overlay, and diff helpers."""

    def __init__(self) -> None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._color_map: dict[str, int] = {}
        self._palette_idx = 0

    @staticmethod
    def _to_absolute(path: Path) -> str:
        return str(path.resolve())

    @staticmethod
    def _check_file_not_locked(file_path: Path) -> bool:
        if not file_path.exists():
            return True
        try:
            with open(file_path, "r+b"):
                pass
            return True
        except (PermissionError, OSError):
            return False

    @staticmethod
    def _auto_output_name(src: Path, suffix: str = "-汇总") -> Path:
        return OUTPUT_DIR / (src.stem + suffix + src.suffix)

    def _backup(self, target: Path) -> Path:
        if not target.exists():
            raise FileNotFoundError(f"Backup target does not exist: {target}")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{target.name}.{ts}.bak"
        shutil.copy2(target, backup_path)
        logger.info("Backup completed for %s", target.name)
        return backup_path

    def _rollback(self, target: Path, backup: Path) -> None:
        if not backup.exists():
            logger.warning("Rollback skipped because backup is missing: %s", backup)
            return
        shutil.copy2(backup, target)
        logger.info("Rollback completed for %s", target.name)

    def _reset_color_state(self) -> None:
        self._color_map = {}
        self._palette_idx = 0

    def _highlight_cell(self, sheet: Any, row: int, col: int, source_tag: str) -> None:
        cell = sheet.range((row, col))
        if source_tag not in self._color_map:
            color = MORANDI_PALETTE[self._palette_idx % len(MORANDI_PALETTE)]
            try:
                existing_color = cell.api.Interior.Color
            except Exception:
                existing_color = -1

            attempts = 0
            while existing_color == color and attempts < len(MORANDI_PALETTE):
                self._palette_idx += 1
                color = MORANDI_PALETTE[self._palette_idx % len(MORANDI_PALETTE)]
                attempts += 1

            self._color_map[source_tag] = color
            self._palette_idx += 1

        cell.api.Interior.Color = self._color_map[source_tag]

    def _write_legend(self, workbook: Any, color_map: dict[str, int]) -> None:
        legend_sheet = workbook.sheets.add(name="图例说明", after=workbook.sheets[-1])
        legend_sheet.range((1, 1)).value = "来源标签"
        legend_sheet.range((1, 2)).value = "颜色示例"
        legend_sheet.range((1, 1)).api.Font.Bold = True
        legend_sheet.range((1, 2)).api.Font.Bold = True
        for row_idx, (tag, color) in enumerate(color_map.items(), start=2):
            legend_sheet.range((row_idx, 1)).value = tag
            legend_sheet.range((row_idx, 2)).api.Interior.Color = color

    def collect_sources(
        self,
        paths: list[Path] | None = None,
        directory: Path | None = None,
    ) -> list[Path]:
        result: set[Path] = set()
        if paths:
            for p in paths:
                path = Path(p)
                if path.is_file():
                    result.add(path.resolve())
                else:
                    logger.warning("Source file skipped because it is missing: %s", path)
        if directory:
            root = Path(directory)
            for ext in ("*.xlsx", "*.xls"):
                for f in root.glob(ext):
                    result.add(f.resolve())
        return sorted(result)

    @staticmethod
    def _used_size(sheet: Any) -> tuple[int, int]:
        used = sheet.api.UsedRange
        return used.Rows.Count, used.Columns.Count

    @staticmethod
    def _close_books(books: list[Any]) -> None:
        for book in reversed(books):
            try:
                book.close()
            except Exception:
                logger.warning("Excel workbook close failed during task cleanup")

    @staticmethod
    def _close_app(app: Any) -> None:
        """Close the task-owned Excel process without masking task failures."""
        try:
            app.quit()
        except Exception:
            logger.warning("Excel application quit failed during task cleanup")
        kill = getattr(app, "kill", None)
        if callable(kill):
            try:
                kill()
            except Exception:
                logger.warning("Excel application kill failed during task cleanup")

    @staticmethod
    def _configure_app(app: Any) -> None:
        app.api.DisplayAlerts = False
        app.api.ScreenUpdating = False
        app.api.EnableEvents = False

    def merge_append(
        self,
        sources: list[Path],
        output_path: Path | None = None,
        baseline: Path | None = None,
    ) -> Path:
        if not sources:
            raise ValueError("sources cannot be empty")
        if output_path is None:
            output_path = self._auto_output_name(Path(sources[0]))
        output_path = Path(output_path)

        if not self._check_file_not_locked(output_path):
            raise PermissionError(f"Output file is locked: {output_path}")

        backup = self._backup(output_path) if output_path.exists() else None
        self._reset_color_state()

        app = None
        books: list[Any] = []
        try:
            xw = _get_xlwings()
            app = xw.App(visible=False, add_book=False)
            self._configure_app(app)

            out_book = app.books.add()
            books.append(out_book)
            out_sheet = out_book.sheets[0]
            out_sheet.name = "合并汇总"
            write_row = 1

            baseline_data: dict[int, tuple[Any, ...]] = {}
            if baseline is not None:
                bl_book = app.books.open(self._to_absolute(Path(baseline)), update_links=False, read_only=True)
                books.append(bl_book)
                bl_sheet = bl_book.sheets[0]
                rows, cols = self._used_size(bl_sheet)
                if rows > 0 and cols > 0:
                    raw_vals = bl_sheet.range((1, 1), (rows, cols)).value
                    if isinstance(raw_vals, list) and raw_vals and isinstance(raw_vals[0], list):
                        for r, row_vals in enumerate(raw_vals, start=1):
                            baseline_data[r] = tuple(row_vals)
                    elif isinstance(raw_vals, list):
                        baseline_data[1] = tuple(raw_vals)
                    else:
                        baseline_data[1] = (raw_vals,)

            for src in sources:
                src_path = Path(src)
                src_book = app.books.open(self._to_absolute(src_path), update_links=False, read_only=True)
                books.append(src_book)
                src_sheet = src_book.sheets[0]
                rows, cols = self._used_size(src_sheet)
                if rows > 0 and cols > 0:
                    raw_vals = src_sheet.range((1, 1), (rows, cols)).value
                    if isinstance(raw_vals, list) and raw_vals and isinstance(raw_vals[0], list):
                        matrix = raw_vals
                    elif isinstance(raw_vals, list):
                        matrix = [raw_vals]
                    else:
                        matrix = [[raw_vals]]

                    out_sheet.range((write_row, 1), (write_row + len(matrix) - 1, cols)).value = matrix
                    if baseline is not None:
                        for r_offset, row_vals in enumerate(matrix):
                            curr_r = write_row + r_offset
                            bl_row = baseline_data.get(curr_r)
                            for c_idx, val in enumerate(row_vals, start=1):
                                bl_val = bl_row[c_idx - 1] if bl_row and c_idx - 1 < len(bl_row) else None
                                if val != bl_val:
                                    self._highlight_cell(out_sheet, curr_r, c_idx, src_path.stem)
                    write_row += len(matrix)

            if baseline is not None and self._color_map:
                self._write_legend(out_book, self._color_map)

            out_book.api.SaveAs(self._to_absolute(output_path), FileFormat=51)
            return output_path
        except Exception:
            if backup is not None:
                self._rollback(output_path, backup)
            raise
        finally:
            self._close_books(books)
            if app is not None:
                self._close_app(app)

    def merge_overlay(
        self,
        sources: list[Path],
        target: Path,
        output_path: Path | None = None,
        baseline: Path | None = None,
    ) -> Path:
        target = Path(target)
        if not target.exists():
            raise FileNotFoundError(f"target file does not exist: {target}")

        if output_path is None:
            output_path = target
        output_path = Path(output_path)

        if not self._check_file_not_locked(output_path):
            raise PermissionError(f"Output file is locked: {output_path}")

        backup = self._backup(output_path) if output_path.exists() else None
        if output_path.resolve() != target.resolve():
            shutil.copy2(target, output_path)

        self._reset_color_state()
        app = None
        books: list[Any] = []
        try:
            xw = _get_xlwings()
            app = xw.App(visible=False, add_book=False)
            self._configure_app(app)

            out_book = app.books.open(self._to_absolute(output_path), update_links=False, read_only=False)
            books.append(out_book)
            out_sheet = out_book.sheets[0]

            baseline_data: dict[tuple[int, int], Any] = {}
            if baseline is not None:
                bl_book = app.books.open(self._to_absolute(Path(baseline)), update_links=False, read_only=True)
                books.append(bl_book)
                bl_sheet = bl_book.sheets[0]
                rows, cols = self._used_size(bl_sheet)
                if rows > 0 and cols > 0:
                    raw_vals = bl_sheet.range((1, 1), (rows, cols)).value
                    if isinstance(raw_vals, list) and raw_vals and isinstance(raw_vals[0], list):
                        bl_matrix = raw_vals
                    elif isinstance(raw_vals, list):
                        bl_matrix = [raw_vals]
                    else:
                        bl_matrix = [[raw_vals]]
                    for r, row_vals in enumerate(bl_matrix, start=1):
                        for c, val in enumerate(row_vals, start=1):
                            baseline_data[(r, c)] = val

            for src in sources:
                src_path = Path(src)
                src_book = app.books.open(self._to_absolute(src_path), update_links=False, read_only=True)
                books.append(src_book)
                src_sheet = src_book.sheets[0]
                rows, cols = self._used_size(src_sheet)
                if rows > 0 and cols > 0:
                    raw_vals = src_sheet.range((1, 1), (rows, cols)).value
                    if isinstance(raw_vals, list) and raw_vals and isinstance(raw_vals[0], list):
                        matrix = raw_vals
                    elif isinstance(raw_vals, list):
                        matrix = [raw_vals]
                    else:
                        matrix = [[raw_vals]]
                    out_sheet.range((1, 1), (len(matrix), cols)).value = matrix
                    if baseline is not None:
                        for r, row_vals in enumerate(matrix, start=1):
                            for c, val in enumerate(row_vals, start=1):
                                if val != baseline_data.get((r, c)):
                                    self._highlight_cell(out_sheet, r, c, src_path.stem)

            if baseline is not None and self._color_map:
                self._write_legend(out_book, self._color_map)

            out_book.api.SaveAs(self._to_absolute(output_path), FileFormat=51)
            return output_path
        except Exception:
            if backup is not None:
                self._rollback(output_path, backup)
            raise
        finally:
            self._close_books(books)
            if app is not None:
                self._close_app(app)

    def diff_against_baseline(
        self,
        target: Path,
        baseline: Path,
        output_path: Path | None = None,
    ) -> Path:
        target = Path(target)
        baseline = Path(baseline)
        if not target.exists():
            raise FileNotFoundError(f"target file does not exist: {target}")
        if not baseline.exists():
            raise FileNotFoundError(f"baseline file does not exist: {baseline}")

        if output_path is None:
            output_path = self._auto_output_name(target, suffix="-比对")
        output_path = Path(output_path)

        if not self._check_file_not_locked(output_path):
            raise PermissionError(f"Output file is locked: {output_path}")

        backup = self._backup(output_path) if output_path.exists() else None
        shutil.copy2(target, output_path)

        self._reset_color_state()
        app = None
        books: list[Any] = []
        try:
            xw = _get_xlwings()
            app = xw.App(visible=False, add_book=False)
            self._configure_app(app)

            out_book = app.books.open(self._to_absolute(output_path), update_links=False, read_only=False)
            bl_book = app.books.open(self._to_absolute(baseline), update_links=False, read_only=True)
            books.extend([out_book, bl_book])
            out_sheet = out_book.sheets[0]
            bl_sheet = bl_book.sheets[0]

            out_rows, out_cols = self._used_size(out_sheet)
            bl_rows, bl_cols = self._used_size(bl_sheet)
            for r in range(1, max(out_rows, bl_rows) + 1):
                for c in range(1, max(out_cols, bl_cols) + 1):
                    out_cell = out_sheet.range((r, c))
                    bl_cell = bl_sheet.range((r, c))
                    tgt_val = out_cell.value
                    tgt_formula = out_cell.formula
                    bl_val = bl_cell.value
                    bl_formula = bl_cell.formula

                    if tgt_val is None and tgt_formula in (None, ""):
                        if bl_val is not None or bl_formula not in (None, ""):
                            self._highlight_cell(out_sheet, r, c, "删除")
                    elif bl_val is None and bl_formula in (None, ""):
                        self._highlight_cell(out_sheet, r, c, "新增")
                    elif tgt_val != bl_val or tgt_formula != bl_formula:
                        self._highlight_cell(out_sheet, r, c, "修改")

            if self._color_map:
                self._write_legend(out_book, self._color_map)

            out_book.api.SaveAs(self._to_absolute(output_path), FileFormat=51)
            return output_path
        except Exception:
            if backup is not None:
                self._rollback(output_path, backup)
            raise
        finally:
            self._close_books(books)
            if app is not None:
                self._close_app(app)


# ── 只读取数（签署日报「Excel 代读」第 1 期，2026-11-12）────────────────
#
# 公司终端加密的 xlsx，本进程读到的是密文；Excel 是受信进程，能读到内容。
# 这里只做一件事：用**独立的** Excel 实例只读打开工作簿，把第一张工作表的
# 值一次取回内存。不保存、不另存、不落任何文件；不解密、不剥文件头。

#: read_sheet_matrix 的失败原因闭集（调用方只按这些词映射文案，不看异常原文）。
SHEET_REASON_EXCEL_UNAVAILABLE = "excel_unavailable"
SHEET_REASON_CANNOT_OPEN = "excel_cannot_open"
SHEET_REASON_HAS_FORMULA = "has_formula"
SHEET_REASON_NOT_AT_A1 = "range_not_at_a1"
SHEET_REASON_TOO_LARGE = "too_large"
SHEET_REASON_CELL_ERROR = "cell_error"
SHEET_REASONS = (
    SHEET_REASON_EXCEL_UNAVAILABLE,
    SHEET_REASON_CANNOT_OPEN,
    SHEET_REASON_HAS_FORMULA,
    SHEET_REASON_NOT_AT_A1,
    SHEET_REASON_TOO_LARGE,
    SHEET_REASON_CELL_ERROR,
)
#: msoAutomationSecurityForceDisable：打开时不执行任何宏。
_AUTOMATION_SECURITY_FORCE_DISABLE = 3


class SheetReadError(RuntimeError):
    """只读取数失败；reason 是 SHEET_REASONS 之一，消息里不带任何单元格内容或路径。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"sheet read failed: {reason}")
        self.reason = reason


def _matrix_from_value2(raw: Any, rows: int, cols: int) -> list[list[Any]]:
    """把 Range.Value2 统一成二维列表：单格返回标量、单行/单列可能返回一维。"""
    if rows == 1 and cols == 1:
        if isinstance(raw, (list, tuple)):
            raw = raw[0]
            if isinstance(raw, (list, tuple)):
                raw = raw[0]
        return [[raw]]
    if not isinstance(raw, (list, tuple)):
        raise SheetReadError(SHEET_REASON_CELL_ERROR)
    if raw and not isinstance(raw[0], (list, tuple)):
        # 一维：单行按行摆，单列按列摆。
        matrix = [list(raw)] if rows == 1 else [[value] for value in raw]
    else:
        matrix = [list(row) for row in raw]
    if len(matrix) != rows or any(len(row) != cols for row in matrix):
        raise SheetReadError(SHEET_REASON_CELL_ERROR)
    return matrix


def read_sheet_matrix(
    path: Path,
    *,
    max_rows: int,
    max_cols: int,
    on_app_started: Any = None,
) -> list[list[Any]]:
    """用独立 Excel 实例只读打开 ``path``，返回第一张工作表 A1 起的值矩阵（Value2）。

    约束（任何一条不满足都抛 ``SheetReadError``，不返回部分结果）：

    - 独立实例（不附着用户已开的 Excel）、``DisplayAlerts=False``、禁宏；
      ``read_only=True``、不更新链接、不进最近使用列表、不弹通知；关闭时不保存；
    - 工作表取第一张（与 zip 读取路一致），不用 ``ActiveSheet``；
    - UsedRange 必须起于 A1；先读行列数，超过上限即拒，再一次取 ``Value2``；
    - ``UsedRange.HasFormula`` 只有明确为 False 才放行；
    - 单元格只接受 str / float / None；布尔、整数（错误码）等一律 ``cell_error``。

    ``on_app_started(app)`` 在实例创建后立刻回调（调用方借此登记 Excel 的 PID）。
    """
    if max_rows <= 0 or max_cols <= 0:
        raise ValueError("sheet limits must be positive")
    try:
        xw = _get_xlwings()
        app = xw.App(visible=False, add_book=False)
    except Exception:  # noqa: BLE001 - 没装 xlwings / 起不了 Excel 都是「本机不能代读」
        raise SheetReadError(SHEET_REASON_EXCEL_UNAVAILABLE) from None

    book = None
    try:
        if on_app_started is not None:
            on_app_started(app)
        try:
            app.api.DisplayAlerts = False
            app.api.AutomationSecurity = _AUTOMATION_SECURITY_FORCE_DISABLE
            book = app.books.open(
                str(path),
                read_only=True,
                update_links=False,
                notify=False,
                add_to_mru=False,
            )
            sheet = book.sheets[0]
            used = sheet.api.UsedRange
            first_row, first_col = int(used.Row), int(used.Column)
            rows, cols = int(used.Rows.Count or 0), int(used.Columns.Count or 0)
        except SheetReadError:
            raise
        except Exception:  # noqa: BLE001 - 只报枚举，不带 COM 异常原文
            raise SheetReadError(SHEET_REASON_CANNOT_OPEN) from None
        if first_row != 1 or first_col != 1:
            raise SheetReadError(SHEET_REASON_NOT_AT_A1)
        if rows <= 0 or cols <= 0 or rows > max_rows or cols > max_cols:
            raise SheetReadError(SHEET_REASON_TOO_LARGE)
        try:
            has_formula = used.HasFormula
            raw = sheet.range((1, 1), (rows, cols)).api.Value2
        except Exception:  # noqa: BLE001
            raise SheetReadError(SHEET_REASON_CANNOT_OPEN) from None
        if has_formula is not False:
            # True（全是公式）或 None（部分是公式）都拒：公式值不是导出件的原始内容。
            raise SheetReadError(SHEET_REASON_HAS_FORMULA)
        matrix = _matrix_from_value2(raw, rows, cols)
        for row in matrix:
            for value in row:
                if value is None or isinstance(value, str):
                    continue
                if isinstance(value, bool) or not isinstance(value, float):
                    raise SheetReadError(SHEET_REASON_CELL_ERROR)
                if value != value or value in (float("inf"), float("-inf")):
                    raise SheetReadError(SHEET_REASON_CELL_ERROR)
        return matrix
    finally:
        if book is not None:
            try:
                book.api.Close(SaveChanges=False)
            except Exception:  # noqa: BLE001 - 关闭失败不掩盖读取结论
                pass
        try:
            app.quit()
        except Exception:  # noqa: BLE001
            kill = getattr(app, "kill", None)
            if callable(kill):
                try:
                    kill()
                except Exception:  # noqa: BLE001
                    pass
