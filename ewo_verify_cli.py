"""EWO 导出件离线验证器（生产环境无第三方依赖运行）。

用途：在不能安装 Python/依赖的生产机上，验证一份 EWO 导出件是否满足 111 列契约、
第 58 列（BF）起是否真有数据、业务编号是否空/重复；可选输出 111 列 CSV。

支持两种输入：
- ``.csv``：程序「全量导出 CSV」的产物（UTF-8 BOM，111 列表头）；
- ``.xlsx``：上游官方报表工作簿（sheet ``Innovator``，111 列表头）。

边界：只读本地文件，不触网、不读取任何凭据、不写除 --out 指定文件以外的路径。

退出码：0 通过；1 校验失败；2 参数或读取错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from services.ewo_official_rows import (
    EwoExportGateError,
    contract_labels,
    label_rows,
    project_official_ewo_rows,
    read_official_ewo_rows,
)

_STRICT_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_BF_INDEX = 57  # 0-based；第 58 列 = BF
_TAIL_START = 57
_CSV_SUFFIXES = (".csv", ".txt")


class VerifyError(Exception):
    """验证器自身的输入错误（不是工作簿问题）。"""


def _cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    probe = text.lstrip()
    if probe and probe[0] in _FORMULA_PREFIXES and not _STRICT_NUMBER.match(probe):
        return "'" + text
    return text


def _write_csv(path: Path, labels: list[str], rows: list[list[object | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(labels)
            for row in rows:
                writer.writerow([_cell(value) for value in row])
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def _business_numbers(rows: list[dict[str, object]], index: int = 0) -> tuple[int, int]:
    values = []
    for row in rows:
        value = row.get(contract_labels()[index])
        text = str(value).strip() if value is not None else ""
        if text:
            values.append(text)
    blank = sum(
        1 for row in rows
        if not str(row.get(contract_labels()[index]) or "").strip()
    )
    duplicates = len(values) - len(set(values))
    return blank, duplicates


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[object]]]:
    """读取「全量导出 CSV」产物：UTF-8 BOM、111 列表头、CRLF。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise EwoExportGateError("E_WORKBOOK_INVALID", "文件为空，没有表头行") from None
        rows = [list(row) for row in reader if any(str(value).strip() for value in row)]
    return [str(value or "").strip() for value in header], rows


def _load_rows(path: Path) -> list[dict[str, object]]:
    """按扩展名选择读取路径；两种来源都经过同一套表头/契约外列门禁。"""
    if path.suffix.lower() in _CSV_SUFFIXES:
        header, matrix = _read_csv_rows(path)
        return list(label_rows(header, matrix))
    return list(read_official_ewo_rows(path))


def verify(path: Path, *, max_rows: int = 5001) -> dict[str, object]:
    labels = contract_labels()
    rows = _load_rows(path)
    if len(rows) > max_rows:
        raise EwoExportGateError("E_TOO_MANY_ROWS", f"数据行 {len(rows)} 超过上限 {max_rows}")
    tail: dict[str, int] = {}
    for index in range(_TAIL_START, len(labels)):
        label = labels[index]
        tail[label] = sum(1 for row in rows if str(row.get(label) or "").strip() != "")
    blank, duplicates = _business_numbers(rows)
    bf_value = tail.get(labels[_BF_INDEX], 0)
    ok = (
        len(rows) > 0
        and bf_value > 0
        and blank == 0
        and duplicates == 0
    )
    return {
        "ok": ok,
        "source_kind": "csv" if path.suffix.lower() in _CSV_SUFFIXES else "xlsx",
        "data_rows": len(rows),
        "header_width": len(labels),
        "bf_column": labels[_BF_INDEX],
        "bf_nonempty": bf_value,
        "tail_nonempty": tail,
        "blank_business_numbers": blank,
        "duplicate_business_numbers": duplicates,
    }


def _print_report(report: dict[str, object], source: Path) -> None:
    print("EWO 导出件验证")
    print(f"文件: {source.name}")
    where = "CSV（程序全量导出产物）" if report.get("source_kind") == "csv" else "工作表 Innovator（官方报表工作簿）"
    print(f"来源: {where}")
    print(f"表头: {report['header_width']} 列 | 数据行: {report['data_rows']}")
    print("表头契约: 通过（111/111 逐字一致）")
    print(f"第 58 列（BF）{report['bf_column']}: 非空 {report['bf_nonempty']} 行")
    print("尾部 54 列非空统计:")
    for label, count in report["tail_nonempty"].items():
        print(f"  {label}: {count}")
    print(
        f"业务编号: 空 {report['blank_business_numbers']} | 重复 {report['duplicate_business_numbers']}"
    )
    verdict = "通过（BF 起有值，编号无空无重复）" if report["ok"] else "未通过（见上方统计）"
    print(f"结论: {verdict}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="VSE-EWO-Verify",
        description="离线验证 EWO 导出件（.csv 或 .xlsx）：111 列契约、BF 起非空、编号唯一",
    )
    parser.add_argument("workbook", help="EWO 导出件路径（程序导出的 .csv 或官方 .xlsx）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 报告")
    parser.add_argument("--out", metavar="CSV", help="额外生成 111 列 CSV（UTF-8 BOM）")
    parser.add_argument("--max-rows", type=int, default=5001, help="数据行上限（默认 5001）")
    args = parser.parse_args(argv)

    path = Path(args.workbook).expanduser()
    if not path.is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2
    try:
        report = verify(path, max_rows=args.max_rows)
    except EwoExportGateError as exc:
        payload = {"ok": False, "error": exc.code, "detail": exc.detail}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"校验失败: {exc.code} {exc.detail}".rstrip(), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"工作簿无法读取: {exc}", file=sys.stderr)
        return 2

    if args.out:
        labels = contract_labels()
        rows = _load_rows(path)
        matrix = project_official_ewo_rows(rows, labels)
        target = Path(args.out).expanduser()
        _write_csv(target, labels, matrix)
        report["csv_out"] = str(target)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _print_report(report, path)
        if report.get("csv_out"):
            print(f"已生成 CSV: {report['csv_out']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - 入口由 ewo_verify_main.py 提供
    raise SystemExit(main())
