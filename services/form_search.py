# -*- coding: utf-8 -*-
"""交付物表单明细的多值搜索（3D单签署日报规格 §9 S2–S4）。

搜索框一次可输入多个检索词：分隔符认空格、逗号、分号、顿号、换行、制表符，全角半角都认，
从 Excel 复制一列可直接粘贴。每个词在快照行的 ``search_text`` 里做包含匹配、不分大小写，
词与词之间是「或」（SQL 见 core/db_common.py 的 ``terms`` 过滤键）。
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Mapping, Sequence

MAX_TERMS = 100
MAX_TERM_LENGTH = 200
PLACEHOLDER = "输入流水单号、零件名称、零件号或申请人；多个用空格、逗号或换行分隔，可直接粘贴 Excel 一列"
_SEPARATORS = re.compile(r"[\s,;、]+")


def parse_terms(text: Any) -> list[str]:
    """S2：原文 -> 去重后的检索词（保持顺序，最多 100 个）。"""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    terms: list[str] = []
    for token in _SEPARATORS.split(normalized):
        token = token.strip()[:MAX_TERM_LENGTH]
        if token and token.casefold() not in {t.casefold() for t in terms}:
            terms.append(token)
        if len(terms) >= MAX_TERMS:
            break
    return terms


def _serial_index(schema: Mapping[str, Any] | None) -> int | None:
    header_rows = (schema or {}).get("headerRows") if isinstance(schema, Mapping) else None
    if not header_rows:
        return None
    headers = [str(h or "").strip() for h in header_rows[0]]
    return headers.index("流水单号") if "流水单号" in headers else None


def term_summary(db: Any, form_key: str, terms: Sequence[str]) -> dict[str, Any]:
    """S4：-> 匹配多少份表单（按流水单号去重，没有该列的表单按行数）、哪些词没有匹配。"""
    latest = db.get_latest_deliverable_form_snapshot(form_key)
    if latest is None or not terms:
        return {"terms": list(terms), "forms": 0, "rows": 0, "unmatched": list(terms)}
    snapshot_id = int(latest["id"])
    schema = latest.get("schema")
    if schema is None and latest.get("schema_json"):
        try:
            schema = json.loads(latest["schema_json"])
        except ValueError:
            schema = None
    index = _serial_index(schema)
    rows = db.list_deliverable_form_snapshot_rows(snapshot_id, {"terms": list(terms)})
    if index is None:
        forms = len(rows)
    else:
        forms = len({
            str((row.get("values") or [None] * (index + 1))[index] or "").strip()
            for row in rows
        } - {""})
    unmatched = [
        term for term in terms
        if not db.list_deliverable_form_snapshot_rows(snapshot_id, {"terms": [term]}, limit=1)
    ]
    return {"terms": list(terms), "forms": forms, "rows": len(rows), "unmatched": unmatched}


def form_serials(db: Any, form_key: str) -> set[str]:
    """最新表单快照里出现过的流水单号（关注清单「未找到」判定，S8）。"""
    latest = db.get_latest_deliverable_form_snapshot(form_key)
    if latest is None:
        return set()
    schema = latest.get("schema")
    if schema is None and latest.get("schema_json"):
        try:
            schema = json.loads(latest["schema_json"])
        except ValueError:
            schema = None
    index = _serial_index(schema)
    if index is None:
        return set()
    serials = set()
    for row in db.list_deliverable_form_snapshot_rows(int(latest["id"])):
        values = row.get("values") or []
        if index < len(values) and values[index] not in (None, ""):
            serials.add(str(values[index]).strip())
    return serials
