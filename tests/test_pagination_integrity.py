# -*- coding: utf-8 -*-
"""分页完整性契约的单一来源与判定矩阵（P2 架构收敛）。

守护目标：`stop_reason` 词表与元数据驱动的终局判定只有一个拥有者
（`services.pagination_integrity`），TDC 与 Aras 两个生产者都从它派生
`complete`，不允许任一侧再立字面集合。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services import aras_crawler, tdc_crawler
from services.pagination_integrity import (
    COMPLETE_STOP_REASONS,
    CONTINUE_STOP_REASON,
    PageBookkeeping,
    WorkbookBookkeeping,
    decide_page_outcome,
    decide_workbook_outcome,
    is_complete,
)
from services.project_status_records import (
    COMPLETE_RESULT_STOP_REASONS,
)


def _book(**overrides) -> PageBookkeeping:
    base = dict(
        page=1,
        page_size=50,
        rows_on_page=50,
        accumulated_count=50,
        unique_count=50,
        duplicate_count=0,
        reported_total=None,
        reported_pages=None,
        max_records=5000,
        max_pages=100,
    )
    base.update(overrides)
    return PageBookkeeping(**base)


# ── 单一来源 ────────────────────────────────────────────────────────────────


def test_complete_stop_reasons_has_a_single_owner() -> None:
    """词表在 project_status_records 处的旧公开名必须就是同一对象（非副本）。"""
    assert COMPLETE_RESULT_STOP_REASONS is COMPLETE_STOP_REASONS


def test_both_crawlers_derive_complete_from_the_shared_predicate() -> None:
    assert tdc_crawler.is_complete is is_complete
    assert aras_crawler.is_complete is is_complete


def test_crawlers_do_not_reintroduce_a_literal_complete_set() -> None:
    """反向守护：两个生产者不得再出现字面集合（否则又会各自漂移）。"""
    for module in (tdc_crawler, aras_crawler):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert '"reported_pages", "reported_total", "empty_page", "short_page"' not in source
        assert '"reported_pages","reported_total","empty_page","short_page"' not in source


def test_is_complete_matches_the_declared_vocabulary() -> None:
    assert is_complete("short_page") is True
    assert is_complete("reported_pages") is True
    assert is_complete("duplicate_records") is False
    assert is_complete(CONTINUE_STOP_REASON) is False
    assert is_complete("unknown_reason") is False


# ── 判定矩阵（分支优先级即契约）─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # 优先级 1-3：页簿记自相矛盾，优先于其它任何证明
        (dict(page_mismatch=True), "inconsistent_page"),
        (dict(size_mismatch=True), "inconsistent_page_size"),
        (dict(metadata_inconsistent=True), "inconsistent_metadata"),
        # 优先级 4：出现重复行
        (dict(duplicate_count=1), "duplicate_records"),
        # 优先级 5：声明记录已齐（页数驱动 / 总数驱动两种证明）
        (dict(reported_pages=1, reported_total=50), "reported_pages"),
        (dict(reported_total=50), "reported_total"),
        # 优先级 6：空页——只有不与声明矛盾才视为取完
        (dict(rows_on_page=0, accumulated_count=0, unique_count=0), "empty_page"),
        (
            dict(rows_on_page=0, accumulated_count=0, unique_count=0, reported_pages=3),
            "incomplete_page",
        ),
        (
            dict(rows_on_page=0, accumulated_count=0, unique_count=0, reported_total=50),
            "incomplete_page",
        ),
        # 优先级 7：短页——只有已满足声明才视为取完
        (dict(rows_on_page=30, accumulated_count=30, unique_count=30), "short_page"),
        (
            dict(
                rows_on_page=30,
                accumulated_count=30,
                unique_count=30,
                reported_pages=5,
            ),
            "incomplete_page",
        ),
        # 优先级 8-9：上限
        (dict(unique_count=5000), "max_records"),
        (dict(page=100), "max_pages"),
        # 缺省：继续翻页
        (dict(), CONTINUE_STOP_REASON),
    ],
)
def test_decide_page_outcome_branch_matrix(overrides: dict, expected: str) -> None:
    assert decide_page_outcome(_book(**overrides)) == expected


def test_overflowed_page_cannot_claim_an_end_of_data_proof() -> None:
    """越过调用方安全边界时，即使页元数据自称已完，也不得判为 complete。"""
    verdict = decide_page_outcome(
        _book(reported_pages=1, reported_total=50, overflowed=True)
    )
    assert verdict not in COMPLETE_STOP_REASONS


def test_total_claim_requires_unique_rows_not_raw_accumulation() -> None:
    """身份过粗（去重后不足声明总数）必须仍判不完整，fail-closed。"""
    verdict = decide_page_outcome(
        _book(
            reported_total=50,
            accumulated_count=52,
            unique_count=48,
            duplicate_count=4,
        )
    )
    assert verdict == "duplicate_records"
    assert is_complete(verdict) is False


def test_decide_page_outcome_continues_on_intermediate_duplicate_with_declared_pages() -> None:
    """真实数据复现守护：第 1 页（共 17 页）存在 1 条重复时，不得中断熔断，必须 continue 翻页。"""
    verdict = decide_page_outcome(
        _book(
            page=1,
            page_size=50,
            rows_on_page=50,
            accumulated_count=50,
            unique_count=49,
            duplicate_count=1,
            reported_total=809,
            reported_pages=17,
        )
    )
    assert verdict == CONTINUE_STOP_REASON


def test_decide_page_outcome_accepts_minor_duplicates_on_final_page() -> None:
    """终局轻微重复容忍：全量 17 页全部爬取完毕且去重覆盖率 >= 95% 时，判为 reported_pages 完成。"""
    verdict = decide_page_outcome(
        _book(
            page=17,
            page_size=50,
            rows_on_page=9,
            accumulated_count=809,
            unique_count=808,
            duplicate_count=1,
            reported_total=809,
            reported_pages=17,
        )
    )
    assert verdict == "reported_pages"
    assert is_complete(verdict) is True


def test_decide_page_outcome_rejects_severe_identity_collapse_on_final_page() -> None:
    """终局严重重复拦截：若去重行数严重偏离总数（< 95%），依然 fail-closed 判为 duplicate_records。"""
    verdict = decide_page_outcome(
        _book(
            page=17,
            page_size=50,
            rows_on_page=9,
            accumulated_count=809,
            unique_count=400,
            duplicate_count=409,
            reported_total=809,
            reported_pages=17,
        )
    )
    assert verdict == "duplicate_records"
    assert is_complete(verdict) is False


# ── 官方工作簿准入（NCR）判定矩阵 ────────────────────────────────────────────


def _wb(**overrides) -> WorkbookBookkeeping:
    base = dict(read_rows=10, parsed_rows=8, blank_rows=2, header_rows=0)
    base.update(overrides)
    return WorkbookBookkeeping(**base)


def test_workbook_admission_passes_only_on_balanced_accounting() -> None:
    """簿记平衡且无未归类行 → workbook_rows，且它是唯一的准入通过原因。"""
    verdict = decide_workbook_outcome(_wb())
    assert verdict == "workbook_rows"
    assert is_complete(verdict) is True
    workbook_reasons = {
        reason for reason in COMPLETE_STOP_REASONS if reason.startswith("workbook_")
    }
    assert workbook_reasons == {"workbook_rows"}


@pytest.mark.parametrize(
    ("book", "expected"),
    [
        (_wb(unreadable=True), "workbook_unreadable"),
        (_wb(header_contract_ok=False), "workbook_header_mismatch"),
        (_wb(truncated=True), "workbook_truncated"),
        (_wb(row_rejected=True), "workbook_rows_rejected"),
        (_wb(unclassified_rows=1, read_rows=11), "workbook_rows_unclassified"),
        (_wb(read_rows=11), "workbook_accounting_mismatch"),
        (_wb(read_rows=0, parsed_rows=0, blank_rows=0), "workbook_empty"),
    ],
)
def test_workbook_admission_fails_closed(book: WorkbookBookkeeping, expected: str) -> None:
    """任一簿记疑点都必须 fail-closed（不得把可能的少行当完整）。"""
    verdict = decide_workbook_outcome(book)
    assert verdict == expected
    assert is_complete(verdict) is False


def test_workbook_admission_rejects_negative_counters_that_balance_the_equation() -> None:
    """负数计数即使让账目等式"刚好平衡"也必须 fail-closed（不得假平衡放行）。"""
    for negative in (
        _wb(read_rows=8, parsed_rows=9, blank_rows=-1, header_rows=0),
        _wb(read_rows=8, parsed_rows=9, blank_rows=0, header_rows=-1),
        _wb(read_rows=8, parsed_rows=9, blank_rows=0, header_rows=0, unclassified_rows=-1),
    ):
        assert negative.accounted_rows() == negative.read_rows
        assert (
            decide_workbook_outcome(negative) == "workbook_accounting_mismatch"
        )


def test_workbook_admission_priority_is_contract() -> None:
    """分支优先级即契约：不可读 > 表头不符 > 截断 > 行被拒 > 不平 > 未归类 > 空表。"""
    both = _wb(unreadable=True, header_contract_ok=False, truncated=True)
    assert decide_workbook_outcome(both) == "workbook_unreadable"
    header_and_truncated = _wb(header_contract_ok=False, truncated=True)
    assert decide_workbook_outcome(header_and_truncated) == "workbook_header_mismatch"
    truncated_and_rejected = _wb(truncated=True, row_rejected=True)
    assert decide_workbook_outcome(truncated_and_rejected) == "workbook_truncated"
