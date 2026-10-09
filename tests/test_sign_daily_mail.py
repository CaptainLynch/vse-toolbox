# -*- coding: utf-8 -*-
"""sign-daily v2.0 邮件正文、收件人与 .eml（规格 §6、§8、§10）。"""

from __future__ import annotations

import base64
import email
import importlib.util
import sys
import time
from email import policy
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins" / "sign_daily"


def _load():
    spec = importlib.util.spec_from_file_location("sign_daily_mail_under_test", PLUGIN_DIR / "mail.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _load()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
THRESHOLDS = {"warnDays": 7, "overdueDays": 14}
TEXTS = {"greeting": "各位领导、同事：", "planText": "计划10-10发布", "feishuLink": "反馈：https://x.feishu.cn/base/abc"}


def _report(**overrides):
    report = {
        "summaryLines": ["F610M-车体区域-3D单流程共4份", "长周期签单情况：…", "总签单情况：…"],
        "snapshotAt": "2026-10-03T08:00:00Z",
        "charts": {
            "external": [{"group": "冲压", "personTimes": 2, "flows": 2, "people": 1,
                          "bars": [{"name": "冲压丁", "label": "冲压丁", "count": 2, "serials": ["S1", "S4"]}]}],
            "sections": [],
            "approval": [{"group": "首席/总监", "personTimes": 1, "flows": 1, "people": 1,
                          "bars": [{"name": "总监辛", "label": "总监辛（未在册）", "count": 1, "serials": ["S2"]}]}],
        },
        "flows": [
            {"serial": "S1", "partLabel": "【长周期】前门内板等2件", "department": "车身科", "applicant": "林锦辉",
             "stage": "会签中",
             "todo": [{"name": "冲压丁", "area": "冲压", "external": True, "addSign": False},
                      {"name": "加签壬", "area": "", "external": False, "addSign": True},
                      {"name": "起草甲", "area": "车身科", "external": False, "addSign": False, "returned": True}],
             "notCurrent": 1, "countersign": (1, 2), "total": (1, 2), "days": 15},
            {"serial": "S2", "partLabel": "顶棚", "department": "车体科", "applicant": "蒋运飞", "stage": "审批中",
             "todo": [], "notCurrent": 0, "countersign": (2, 2), "total": (2, 3), "days": 8},
            {"serial": "S3", "partLabel": "<b>x</b>", "department": "车身科", "applicant": "A", "stage": "待锁定",
             "todo": [], "notCurrent": 0, "countersign": (1, 1), "total": (1, 1), "days": 2},
        ],
    }
    report.update(overrides)
    return report


def test_html_order_images_and_table():
    body = M.render_html(_report(), TEXTS, THRESHOLDS)
    order = [body.index(marker) for marker in ("F610M-车体区域", "计划10-10发布", "图1 外区域会签未签单情况", "图2 内部科室会签未签单情况",
                                               "图3 审批未签单情况", "在途流程签署明细")]
    assert order == sorted(order)  # 汇总、文案、图1、图2、图3、明细表（§6）
    assert 'src="cid:sd-external"' in body and 'src="cid:sd-approval"' in body
    assert "cid:sd-sections" not in body and "本阶段无未签" in body  # G6
    assert "柱高 = 当前待办的在途 3D单份数" in body  # G7
    assert '<a href="https://x.feishu.cn/base/abc">' in body
    assert "<b>冲压丁（冲压）</b>" in body and "加签壬（加签）" in body and "起草甲（退回修改）" in body and "另 1 人未签、非当前待办" in body
    assert 'bgcolor="#ffd6d6"' in body and "font-weight:bold;\">15<" in body  # 超期：浅红底红色粗体
    assert 'bgcolor="#fff3c4"' in body  # 预警：浅黄底
    assert "&lt;b&gt;x&lt;/b&gt;" in body  # 转义
    assert body.count("未填写原因") == 3
    assert "class=" not in body and "flex" not in body  # 只用行内样式（§10）
    assert M.chart_keys_with_data(_report()) == ["external", "approval"]


def test_empty_report_and_plain_text():
    empty = _report(charts={"external": [], "sections": [], "approval": []}, flows=[])
    body = M.render_html(empty, TEXTS, THRESHOLDS)
    assert body.count("本阶段无未签") == 3 and "无在途流程" in body
    text = M.render_text(_report(), TEXTS)
    assert "冲压（2 人次 / 2 份 / 1 人）：冲压丁2" in text
    lines = text.splitlines()
    header = lines.index("\t".join(M._TABLE_HEADERS))
    assert lines[header + 1].split("\t")[:3] == ["1", "S1", "【长周期】前门内板等2件"]
    assert "冲压丁（冲压）、加签壬（加签）、起草甲（退回修改），另 1 人未签、非当前待办" in lines[header + 1]


def test_recipients_add_owed_people_and_list_gaps():
    book = '"冲压丁"<d@x.com>; "总监辛"<a@x.com>; "总监辛"<b@x.com>'
    result = M.recipients('"领导"<lead@x.com>', "", book, M.owed_names(_report()))
    assert [a for _, a in result["to"]] == ["lead@x.com", "d@x.com"]
    assert result["missing"] == []
    assert result["ambiguous"] == [{"name": "总监辛", "addresses": ["a@x.com", "b@x.com"]}]
    gaps = M.recipients("", "", "", ["某人"])
    assert gaps["missing"] == ["某人"] and gaps["to"] == []


def test_eml_is_related_draft_with_inline_png():
    data = M.build_eml(subject="F610M项目3D单签署进展-车体区域-20261003", to=[("张三", "z@x.com")], cc=[],
                       text_body="汇总\n", html_body='<img src="cid:sd-external">', images={"external": PNG})
    assert b"\n" not in data.replace(b"\r\n", b"")  # CRLF
    message = email.message_from_bytes(data, policy=policy.default)
    assert message["X-Unsent"] == "1"
    assert message["Subject"] == "F610M项目3D单签署进展-车体区域-20261003"
    assert [p.get_content_type() for p in message.walk()] == [
        "multipart/related", "multipart/alternative", "text/plain", "text/html", "image/png"]
    image = [p for p in message.walk() if p.get_content_type() == "image/png"][0]
    assert image["Content-ID"] == "<sd-external>" and image.get_content_disposition() == "inline"
    body_lines = data.split(b"\r\n\r\n", 1)[1].split(b"\r\n")
    assert max(len(line) for line in body_lines) <= 76  # 正文 base64 行宽


def test_png_validation():
    assert M.decode_png("data:image/png;base64," + base64.b64encode(PNG).decode()) == PNG
    for bad in ("", "not base64!", base64.b64encode(b"GIF89a").decode(), 3):
        with pytest.raises(M.ImageError):
            M.decode_png(bad)


def test_links_keep_all_query_parameters():  # 审计
    body = M.render_html(_report(), {**TEXTS, "feishuLink": "反馈 https://x.feishu.cn/wiki/a?from=a&sheet=b 谢谢"},
                         THRESHOLDS)
    assert '<a href="https://x.feishu.cn/wiki/a?from=a&amp;sheet=b">' in body


def test_data_time_falls_back_to_data_date():
    assert M.format_data_time({"snapshotAt": "", "dataDate": "2026-10-03"}) == "2026-10-03"


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset only exists on POSIX; Windows uses the system zone")
def test_data_time_is_local(monkeypatch):  # 审计
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        assert M.format_data_time({"snapshotAt": "2026-10-03T01:23:45.123456Z"}) == "2026-10-03 09:23"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_no_total_rate_owed_or_first_generation_text_and_column_count():
    report = _report()
    html_body = M.render_html(report, TEXTS, THRESHOLDS)
    text_body = M.render_text(report, TEXTS)
    for forbidden in ("总签单率", "欠账", "首次生成"):
        assert forbidden not in html_body and forbidden not in text_body
    assert "总签单率" not in M._TABLE_HEADERS
    assert len(M._TABLE_HEADERS) == 10
    lines = text_body.splitlines()
    start = lines.index("\t".join(M._TABLE_HEADERS))
    for row_line in lines[start + 1:start + 1 + len(report["flows"])]:
        assert len(row_line.split("\t")) == len(M._TABLE_HEADERS)
    first_row = html_body.split("<tr>")[2]
    assert first_row.count("<td") == len(M._TABLE_HEADERS)
