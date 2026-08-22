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
                for r in range(1, rows + 1):
                    baseline_data[r] = tuple(bl_sheet.range((r, c)).value for c in range(1, cols + 1))

            for src in sources:
                src_path = Path(src)
                src_book = app.books.open(self._to_absolute(src_path), update_links=False, read_only=True)
                books.append(src_book)
                src_sheet = src_book.sheets[0]
                rows, cols = self._used_size(src_sheet)
                for r in range(1, rows + 1):
                    for c in range(1, cols + 1):
                        val = src_sheet.range((r, c)).value
                        out_sheet.range((write_row, c)).value = val
                        if baseline is not None:
                            bl_row = baseline_data.get(write_row)
                            bl_val = bl_row[c - 1] if bl_row and c - 1 < len(bl_row) else None
                            if val != bl_val:
                                self._highlight_cell(out_sheet, write_row, c, src_path.stem)
                    write_row += 1

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
                for r in range(1, rows + 1):
                    for c in range(1, cols + 1):
                        baseline_data[(r, c)] = bl_sheet.range((r, c)).value

            for src in sources:
                src_path = Path(src)
                src_book = app.books.open(self._to_absolute(src_path), update_links=False, read_only=True)
                books.append(src_book)
                src_sheet = src_book.sheets[0]
                rows, cols = self._used_size(src_sheet)
                for r in range(1, rows + 1):
                    for c in range(1, cols + 1):
                        val = src_sheet.range((r, c)).value
                        out_sheet.range((r, c)).value = val
                        if baseline is not None and val != baseline_data.get((r, c)):
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
