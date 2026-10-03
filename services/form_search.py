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
#: 「全部加入关注清单」一次最多带回的流水单号，与关注清单上限一致。
MAX_SERIALS = 500
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


def snapshot_schema(snapshot: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """表单快照的 schema：列表接口给解析好的 ``schema``，最新快照接口给 ``schema_json`` 原文。"""
    if not snapshot:
        return None
    schema = snapshot.get("schema")
    if schema is None and snapshot.get("schema_json"):
        try:
            schema = json.loads(snapshot["schema_json"])
        except ValueError:
            schema = None
    return schema if isinstance(schema, Mapping) else None


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
        return {"terms": list(terms), "forms": 0, "rows": 0, "unmatched": list(terms), "serials": []}
    snapshot_id = int(latest["id"])
    index = _serial_index(snapshot_schema(latest))
    rows = db.list_deliverable_form_snapshot_rows(snapshot_id, {"terms": list(terms)})
    serials: list[str] = []
    if index is None:
        forms = len(rows)
    else:
        found = {
            str(values[index]).strip()
            for values in (row.get("values") or [] for row in rows)
            if index < len(values) and values[index] not in (None, "")
        }
        forms = len(found)
        serials = sorted(found)[:MAX_SERIALS]
    # 先在合并结果里认出已匹配的词（一次遍历）；只有这里没认出来的词才单独回库确认，
    # 以库里的 search_text 为准（它可能截断或脱敏，Python 侧的拼接不完全等价）。
    haystacks = [" ".join(str(v) for v in (row.get("values") or []) if v is not None).lower() for row in rows]
    seen = {term for term in terms if any(term.lower() in text for text in haystacks)}
    unmatched = [
        term for term in terms
        if term not in seen
        and not db.list_deliverable_form_snapshot_rows(snapshot_id, {"terms": [term]}, limit=1)
    ]
    return {"terms": list(terms), "forms": forms, "rows": len(rows), "unmatched": unmatched, "serials": serials}


def form_serials(db: Any, form_key: str) -> set[str]:
    """最新表单快照里出现过的流水单号（关注清单「未找到」判定，S8）。"""
    latest = db.get_latest_deliverable_form_snapshot(form_key)
    if latest is None:
        return set()
    index = _serial_index(snapshot_schema(latest))
    if index is None:
        return set()
    serials = set()
    for row in db.list_deliverable_form_snapshot_rows(int(latest["id"])):
        values = row.get("values") or []
        if index < len(values) and values[index] not in (None, ""):
            serials.add(str(values[index]).strip())
    return serials
