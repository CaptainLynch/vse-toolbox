# -*- coding: utf-8 -*-
"""build_aggregate_candidate_values：多记录风险备注摘要化契约（G34）。

- ``report=None``（历史调用方）保持旧明细行为；
- ``report`` 给定（连接器接线后）多记录返回确定性摘要；
- 单记录分支两种取值下完全一致。
"""

from __future__ import annotations

from services.project_status_records import build_aggregate_candidate_values

NOTE_MAPPING = {"note": ["状态", "卡点说明"]}


def _identified(*rows: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    return [(f"NO-{index}", row) for index, row in enumerate(rows, 1)]


def test_empty_identified_returns_empty_regardless_of_report() -> None:
    assert build_aggregate_candidate_values([], NOTE_MAPPING) == {}
    assert build_aggregate_candidate_values([], NOTE_MAPPING, report="paa") == {}


def test_report_none_keeps_legacy_detail_behavior() -> None:
    identified = _identified(
        {"状态": "审批中", "卡点说明": "缺夹具"},
        {"状态": "已完成", "卡点说明": "无"},
    )
    assert build_aggregate_candidate_values(identified, NOTE_MAPPING) == {
        "note": "NO-1：审批中｜缺夹具；NO-2：已完成｜无"
    }
    long_text = "长" * 600
    identified_long = _identified(
        {"状态": "审批中", "卡点说明": long_text},
        {"状态": "审批中", "卡点说明": long_text},
    )
    note = build_aggregate_candidate_values(identified_long, NOTE_MAPPING)["note"]
    assert note is not None and len(note) == 1000


def test_single_record_branch_is_unchanged_with_report() -> None:
    row = {"状态": "审批中", "卡点说明": "缺夹具", "负责人": "张三"}
    mapping = {"note": ["卡点说明"], "owner": "负责人"}
    single = [("K-1", row)]
    assert (
        build_aggregate_candidate_values(single, mapping)
        == build_aggregate_candidate_values(single, mapping, report="paa")
        == {"note": "缺夹具", "owner": "张三"}
    )


def test_sor_summary_counts_and_deterministic_order() -> None:
    identified = _identified(
        {"processInstanceStatus": "审批中"},
        {"processInstanceStatus": "已完成 "},
        {"approvalStatus": "审批中", "processInstanceStatus": ""},
        {"审批状态": "已终止"},
        {"processInstanceStatus": ""},
    )
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="sor")["note"]
    # 计数降序、同数按状态名升序；空状态计为「未填写」；原文 trim。
    assert note == "共 5 条；审批中 2、已完成 1、已终止 1、未填写 1"


def test_data_model_summary_normalizes_codes_and_reports_unknown() -> None:
    identified = _identified(
        {"status": "2"},
        {"状态": "2"},
        {"status": "4"},
        {"status": "9"},
        {"状态": "  "},
    )
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="data_model")["note"]
    assert note == "共 5 条；审批中 2、其他(码9) 1、已完成 1、未填写 1"


def test_paa_summary_uses_state_then_current_state_name() -> None:
    identified = _identified(
        {"state": "OPEN"},
        {"state": "", "current_state__name": "PROC"},
        {"current_state__name": "OPEN"},
        {},
    )
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="paa")["note"]
    assert note == "共 4 条；OPEN 2、PROC 1、未填写 1"


def test_ncr_progress_and_detail_summaries_use_chinese_status_first() -> None:
    identified = _identified(
        {"状态": "审批中", "status": "ignored"},
        {"status": "CLOSE"},
        {"状态": ""},
    )
    assert (
        build_aggregate_candidate_values(identified, NOTE_MAPPING, report="ncr_progress")["note"]
        == "共 3 条；CLOSE 1、审批中 1、未填写 1"
    )
    assert (
        build_aggregate_candidate_values(identified, NOTE_MAPPING, report="ncr_detail")["note"]
        == "共 3 条；CLOSE 1、审批中 1、未填写 1"
    )


def test_ewo_summary_falls_back_through_state_keys() -> None:
    identified = _identified(
        {"state": "DRAFT1"},
        {"state": "", "current_state__name": "CANCELLED"},
        {"current_state__name": "", "current_state__keyed_name": "HOLD"},
        {},
    )
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="ewo")["note"]
    assert note == "共 4 条；CANCELLED 1、DRAFT1 1、HOLD 1、未填写 1"


def test_ncr_detail_summary_appends_cost_segments() -> None:
    identified = _identified(
        {
            "状态": "审批中",
            "测算工程工装费用(万元)": "1,000.5",
            "批准工程工装费用（万元）": "800",
            "测算单件成本变化（元）": "-50.5",
        },
        {
            "状态": "审批中",
            "测算工程工装费用(万元)": "999.5",
            "测算单件成本变化（元）": "60",
        },
    )
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="ncr_detail")["note"]
    # 状态计数段完整在前；四指标按定义序追加，无值指标（批准单件成本变化）省略。
    assert note == (
        "共 2 条；审批中 2"
        "；测算工程工装费用合计 2000 万元（有值 2/2 条）"
        "；批准工程工装费用合计 800 万元（有值 1/2 条）"
        "；测算单件成本变化合计 9.5 元（有值 2/2 条）"
    )


def test_ncr_detail_summary_drops_cost_segments_before_status_counts() -> None:
    """超 1000 字：状态计数保持完整，费用段按顺序截除（可整段缺失）。"""
    # 同名长状态合并为一个计数项：head = 995 + 14 = 1009 > 1000——状态段
    # 本身超限也保持完整，费用段全部让位（宁可缺失也不截断状态计数）。
    long_status = "审批中" + "长" * 992
    identified = _identified(
        {
            "状态": long_status,
            "测算工程工装费用(万元)": "2000",
            "批准工程工装费用（万元）": "800",
            "测算单件成本变化（元）": "9.5",
        },
        {"状态": long_status},
        {"状态": "已完成"},
    )
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="ncr_detail")["note"]
    assert note is not None
    assert note.startswith("共 3 条；")
    assert long_status in note and "已完成 1" in note
    assert "合计" not in note

    # 中等长度（head=967）：首个费用段装得下就保留，后续装不下的按顺序截除。
    medium_status = "审批中" + "长" * 950
    identified_medium = _identified(
        {
            "状态": medium_status,
            "测算工程工装费用(万元)": "2000",
            "批准工程工装费用（万元）": "800",
            "测算单件成本变化（元）": "9.5",
        },
        {"状态": medium_status},
        {"状态": "已完成"},
    )
    note_medium = build_aggregate_candidate_values(
        identified_medium, NOTE_MAPPING, report="ncr_detail"
    )["note"]
    assert note_medium is not None
    assert "测算工程工装费用合计 2000 万元（有值 1/3 条）" in note_medium
    assert "批准工程工装费用合计" not in note_medium
    assert "测算单件成本变化合计" not in note_medium


def test_unknown_report_defaults_all_rows_to_unfilled() -> None:
    identified = _identified({"状态": "审批中"}, {"状态": "审批中"})
    note = build_aggregate_candidate_values(identified, NOTE_MAPPING, report="future_form")["note"]
    assert note == "共 2 条；未填写 2"


def test_summary_is_independent_of_input_order() -> None:
    rows = [
        {"processInstanceStatus": "审批中"},
        {"processInstanceStatus": "已完成"},
        {"processInstanceStatus": "审批中"},
    ]
    forward = build_aggregate_candidate_values(_identified(*rows), NOTE_MAPPING, report="sor")
    backward = build_aggregate_candidate_values(
        _identified(*reversed(rows)), NOTE_MAPPING, report="sor"
    )
    assert forward == backward == {"note": "共 3 条；审批中 2、已完成 1"}
