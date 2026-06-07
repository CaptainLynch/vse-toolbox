import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("VSE_TOOLBOX.excel")


def _generate_output_name(prefix: str, suffix: str = ".xlsx") -> str:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{now}{suffix}"


def merge_excel(files: list[Path], output_dir: Path) -> dict[str, Any]:
    """
    多文件多 Sheet 合并到一个工作簿。
    每个源文件的 Sheet 复制到目标工作簿，名称冲突时追加数字后缀。
    """
    try:
        import openpyxl
    except ImportError as e:
        raise RuntimeError("openpyxl 未安装，无法处理 Excel 文件") from e

    if not files:
        raise ValueError("未提供 Excel 文件")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = _generate_output_name("merged")
    output_path = output_dir / output_name

    # 创建新工作簿，移除默认 sheet
    wb_out = openpyxl.Workbook()
    if "Sheet" in wb_out.sheetnames:
        wb_out.remove(wb_out["Sheet"])

    total_sheets = 0
    try:
        for src_path in files:
            if not src_path.exists():
                logger.warning("文件不存在，跳过: %s", src_path)
                continue
            try:
                wb_src = openpyxl.load_workbook(str(src_path), data_only=True)
                for sheet_name in wb_src.sheetnames:
                    ws_src = wb_src[sheet_name]
                    # 处理名称冲突
                    unique_name = sheet_name
                    counter = 1
                    while unique_name in wb_out.sheetnames:
                        unique_name = f"{sheet_name}_{counter}"
                        counter += 1
                    ws_out = wb_out.create_sheet(title=unique_name)
                    # 复制单元格值和格式
                    for row in ws_src.iter_rows():
                        for cell in row:
                            ws_out[cell.coordinate].value = cell.value
                    total_sheets += 1
                wb_src.close()
            except Exception as e:
                logger.error("读取文件失败 %s: %s", src_path, e)
                raise RuntimeError(f"读取文件失败 {src_path.name}: {e}") from e

        if total_sheets == 0:
            raise ValueError("没有有效的 Sheet 可复制")

        wb_out.save(str(output_path))
    finally:
        wb_out.close()

    return {
        "file_path": str(output_path),
        "file_name": output_name,
        "sheet_count": total_sheets,
    }


def merge_same_structure(
    files: list[Path],
    output_dir: Path,
    header_row: int = 0,
) -> dict[str, Any]:
    """
    同结构表格纵向拼接。
    保留第一个文件的表头，其余文件跳过表头行。
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise RuntimeError("pandas 未安装，无法处理 Excel 文件") from e

    if not files:
        raise ValueError("未提供 Excel 文件")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = _generate_output_name("merged_same")
    output_path = output_dir / output_name

    all_dfs = []
    first_header = None
    total_rows = 0

    for idx, src_path in enumerate(files):
        if not src_path.exists():
            logger.warning("文件不存在，跳过: %s", src_path)
            continue
        try:
            # header=None 时 pandas 不将任何行识别为表头
            if header_row is None or header_row < 0:
                df = pd.read_excel(str(src_path))
            else:
                df = pd.read_excel(str(src_path), header=header_row)

            if df.empty:
                logger.warning("文件为空，跳过: %s", src_path)
                continue

            if idx == 0:
                first_header = df.columns.tolist()
                all_dfs.append(df)
                total_rows += len(df)
            else:
                # 强制统一列名，避免列名不一致导致拼接失败
                if len(df.columns) == len(first_header):
                    df.columns = first_header
                else:
                    logger.warning(
                        "列数不匹配 %s: 期望 %d，实际 %d",
                        src_path, len(first_header), len(df.columns)
                    )
                    continue
                all_dfs.append(df)
                total_rows += len(df)
        except Exception as e:
            logger.error("读取文件失败 %s: %s", src_path, e)
            raise RuntimeError(f"读取文件失败 {src_path.name}: {e}") from e

    if not all_dfs:
        raise ValueError("没有有效的数据可合并")

    merged = pd.concat(all_dfs, ignore_index=True)
    merged.to_excel(str(output_path), index=False)

    return {
        "file_path": str(output_path),
        "file_name": output_name,
        "row_count": len(merged),
    }


def batch_rename(
    folder: Path,
    pattern: str,
    replacement: str,
) -> dict[str, Any]:
    """
    批量正则改名。
    只处理 folder 直接子目录中的文件，不递归。
    跳过会导致文件名不变的改名。
    """
    if not folder.exists():
        raise ValueError(f"文件夹不存在: {folder}")
    if not folder.is_dir():
        raise ValueError(f"路径不是文件夹: {folder}")

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"无效的正则表达式: {e}") from e

    renamed = []
    skipped = []

    for item in folder.iterdir():
        if not item.is_file():
            continue
        old_name = item.name
        new_name = compiled.sub(replacement, old_name)
        if new_name == old_name:
            skipped.append(old_name)
            continue
        # 避免覆盖已有文件
        dest = folder / new_name
        if dest.exists():
            skipped.append(old_name)
            logger.warning("目标文件已存在，跳过: %s -> %s", old_name, new_name)
            continue
        try:
            item.rename(dest)
            renamed.append({"old": old_name, "new": new_name})
            logger.info("重命名: %s -> %s", old_name, new_name)
        except OSError as e:
            logger.error("重命名失败 %s: %s", old_name, e)
            skipped.append(old_name)

    return {
        "renamed_files": renamed,
        "skipped_files": skipped,
        "count": len(renamed),
    }
