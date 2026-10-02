# -*- coding: utf-8 -*-
"""sign-daily plugin: 3D单签署日报的口径、渲染和接口。"""

from __future__ import annotations

import email
import importlib.util
import sys
from datetime import date
from email import policy
from pathlib import Path

import pytest

import web.app as web_app
from services.deliverable_form_analysis import build_form_snapshot, form_definition

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "sign_daily"


def _load_report():
    spec = importlib.util.spec_from_file_location("sign_daily_report_under_test", PLUGIN_DIR / "report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R = _load_report()
HEADERS = form_definition("tdc_data_model")["headerRows"][0]


def _row(**values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "项目/车型": "F999X",
        "部门": "车身科",
        "申请人": "起草甲",
        "申请日期": "2026-09-01 10:00:00",
        "发布属性": "T2发布",
        "状态": "审批中",
    }
    base.update(values)
    return base


def _flow_rows() -> list[dict[str, object]]:
    """5 份单：完成 1、签满待锁定 1、会签中 1（含加签）、审批中 1、已废弃 1。"""
    return [
        # 已完成（签署率 < 100% 也算完成，不进欠账）
        *[
            _row(流水单号="F999X-3D-0001", 零件名称=name, 车身="会签乙(未签)", 设计工程师="起草甲",
                 应签人数=2, 已签人数=1, 未签人数=1, 签署率="50.00%", 状态="已完成")
            for name in ("前门内板左", "前门内板右")
        ],
        # 签满但未关闭 -> 待锁定
        _row(流水单号="F999X-3D-0002", 零件名称="后盖外板", 车身="会签乙", 总装="会签丙",
             设计工程师="起草甲", 应签人数=3, 已签人数=3, 未签人数=0, 签署率="100.00%"),
        # 会签中：两个会签未签 + 一个审批未签，待审批里有加签人
        *[
            _row(流水单号="F999X-3D-0003", 零件名称=name, 部门="内饰科", 申请人="起草丁", 申请日期="2026-08-02",
                 车身="会签乙(未签)、会签戊", 空调电子="会签己(未签)", 加签人员="加签庚",
                 设计工程师="起草丁", **{"首席/总监": "总监辛(未签)"},
                 应签人数=5, 已签人数=2, 未签人数=3, 签署率="40.00%", 待审批人员="加签壬")
            for name in ("顶棚总成", "遮阳板", "拉手")
        ],
        # 审批中：会签全签，审批未签
        _row(流水单号="F999X-3D-0004", 零件名称="仪表板骨架", 部门="内饰科", 申请人="起草丁",
             车身="会签乙", 设计工程师="起草丁", **{"专家/经理": "经理癸(未签)"},
             应签人数=2, 已签人数=1, 未签人数=1, 签署率="50.00%"),
        # 已废弃：不计入任何统计
        _row(流水单号="F999X-3D-0005", 零件名称="废弃件", 车身="会签乙(未签)", 应签人数=1, 已签人数=0,
             未签人数=1, 签署率="0.00%", 状态="已废弃"),
        # 其他项目
        _row(流水单号="E50-3D-0001", **{"项目/车型": "E50"}, 零件名称="其他件", 应签人数=1, 已签人数=1, 签署率="100%",
             状态="已完成"),
    ]


# ── 口径 ────────────────────────────────────────────────────────────


def test_parse_people_marks_unsigned_and_dedupes() -> None:
    assert R.parse_people("甲、乙(未签)、甲、丙（未签）") == [("甲", True), ("乙", False), ("丙", False)]
    assert R.parse_people(None) == []
    assert R.parse_people("None") == []


def test_build_flows_merges_parts_and_drops_discarded() -> None:
    flows = {f.serial: f for f in R.build_flows(_flow_rows())}
    assert "F999X-3D-0005" not in flows
    assert flows["F999X-3D-0003"].parts == ["顶棚总成", "遮阳板", "拉手"]
    assert flows["F999X-3D-0003"].stage == R.STAGE_COUNTERSIGN
    assert flows["F999X-3D-0003"].add_sign_pending == ["加签壬"]
    assert flows["F999X-3D-0002"].stage == R.STAGE_LOCK
    assert flows["F999X-3D-0004"].stage == R.STAGE_APPROVAL
    assert flows["F999X-3D-0001"].is_complete


def test_metrics_follow_spec() -> None:
    flows = R.filter_scope(R.build_flows(_flow_rows()), ["F999X"], [])
    total = R.metrics(flows)
    assert total["flows"] == 4
    assert total["parts"] == 7
    # 会签已签/应签：0001 0/1；0002 2/2；0003 1/3；0004 1/1
    assert total["countersignRate"] == round(4 * 100 / 7, 1)
    assert total["totalRate"] == round(7 * 100 / 12, 1)
    assert total["countersignDone"] == 2  # 0002、0004
    assert total["complete"] == 2  # 0001 已完成、0002 签署率 100%
    assert total["locked"] == 2  # 只有 0001 的两个零件已锁定
    assert total["t2Rate"] == round(2 * 100 / 7, 1)


def test_long_cycle_counts_only_confirmed_parts() -> None:
    flows = R.filter_scope(R.build_flows(_flow_rows()), ["F999X"], [])
    hits = R.long_cycle_hits({p for f in flows for p in f.parts}, ["前门内板", "顶 棚(总成)"])
    assert hits == {"前门内板左": "前门内板", "前门内板右": "前门内板", "顶棚总成": "顶 棚(总成)"}
    R.mark_long_cycle(flows, {"前门内板左": True, "前门内板右": True, "顶棚总成": False})
    long = R.metrics(flows, long_cycle=True)
    assert (long["flows"], long["parts"], long["locked"], long["t2Rate"]) == (1, 2, 2, 100.0)


def test_owed_groups_by_department_with_override() -> None:
    flows = R.filter_scope(R.build_flows(_flow_rows()), ["F999X"], [])
    owed = R.owed_by_department(flows, R.PHASE_COUNTERSIGN, R.DEFAULT_ROLE_DEPARTMENTS, {})
    # 已完成的 0001 不进欠账，所以会签乙只欠 0003 一份
    assert owed == [
        {"department": "电子电器", "total": 1, "people": [{"name": "会签己", "count": 1, "serials": ["F999X-3D-0003"]}]},
        {"department": "车身", "total": 1, "people": [{"name": "会签乙", "count": 1, "serials": ["F999X-3D-0003"]}]},
    ]
    approval = R.owed_by_department(flows, R.PHASE_APPROVAL, R.DEFAULT_ROLE_DEPARTMENTS, {"经理癸": "车身科"})
    assert [(g["department"], [p["name"] for p in g["people"]]) for g in approval] == [
        ("内饰科", ["总监辛"]),
        ("车身科", ["经理癸"]),
    ]
    unmapped = R.owed_by_department(flows, R.PHASE_COUNTERSIGN, {}, {})
    assert unmapped[-1]["department"] == R.UNASSIGNED


def test_flow_table_lists_open_flows_by_stage_then_age() -> None:
    flows = R.filter_scope(R.build_flows(_flow_rows()), ["F999X"], [])
    rows = R.flow_table(flows, date(2026, 10, 2), R.DEFAULT_ROLE_DEPARTMENTS, {})
    assert [r["serial"] for r in rows] == ["F999X-3D-0003", "F999X-3D-0004", "F999X-3D-0002"]
    first = rows[0]
    assert first["part"] == "顶棚总成 等3件"
    assert first["days"] == 61
    assert first["stallReason"] == "未填写原因"
    assert [u["name"] for u in first["unsigned"]] == ["会签乙", "会签己", "总监辛", "加签壬"]


def test_report_renders_summary_deltas_and_escapes() -> None:
    flows = R.filter_scope(R.build_flows(_flow_rows()), ["F999X"], [])
    previous = R.summary(flows)
    previous["total"]["complete"] = 1
    previous["total"]["totalRate"] = 50.0
    report = R.build_report(
        flows, projects=["F999X"], today=date(2026, 10, 5), region="车体区域", plan_text="计划<10-10>发布",
        feishu_link="https://example.feishu.cn/base/x", role_departments=R.DEFAULT_ROLE_DEPARTMENTS,
        person_departments={}, previous=previous, previous_date=date(2026, 10, 2),
    )
    assert report["subject"] == "F999X项目3D单签署进展-车体区域-20261005"
    assert report["summaryLines"][0] == "F999X-车体区域-3D单流程共4份，涉及零件7个，其中长周期件流程共0份，涉及零件0个。"
    assert "3D单完成2(+1)/4份" in report["summaryLines"][2]
    assert "总签单率58.3%(+8.3%)" in report["summaryLines"][2]
    assert report["deltaNote"] == "注：括号内为较10-02的变化。"
    assert "计划&lt;10-10&gt;发布" in report["html"]
    assert '<a href="https://example.feishu.cn/base/x">' in report["html"]
    assert "未填写原因" in report["text"]


def test_missing_columns_are_reported() -> None:
    with pytest.raises(R.MissingColumnsError) as info:
        R.check_columns([h for h in HEADERS if h not in ("流水单号", "NVH")])
    assert info.value.missing == ["流水单号", "NVH"]


def test_recipients_add_owed_people_from_address_book() -> None:
    book = R.parse_recipients('"会签乙"<b@example.com>; 会签己 <j@example.com>\n"领导"<lead@example.com>')
    result = R.recipients_for('"领导"<lead@example.com>', "", book, ["会签乙", "领导", "无邮箱"])
    assert result["to"] == [("领导", "lead@example.com"), ("会签乙", "b@example.com")]
    assert result["added"] == [("会签乙", "b@example.com")]


def test_eml_is_unsent_draft_with_html() -> None:
    raw = R.build_eml(subject="主题", to=[("甲", "a@example.com")], cc=[], text_body="正文", html_body="<p>正文</p>")
    message = email.message_from_bytes(raw, policy=policy.default)
    assert message["Subject"] == "主题"
    assert message["X-Unsent"] == "1"
    assert message.get_body(("html",)).get_content().count("<p>正文</p>") == 1


# ── 接口 ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "sign-daily.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["sign-daily"])
    app.config.update(TESTING=True)
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    today = {"value": date(2026, 10, 2)}
    monkeypatch.setattr(backend, "_today", lambda: today["value"])
    return app, app.test_client(), db_cls(tmp_path / "sign-daily.db"), today


def _publish(db, rows, snapshot_at="2026-10-02T08:00:00Z") -> None:  # type: ignore[no-untyped-def]
    positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in rows]
    db.publish_deliverable_form_snapshot(
        build_form_snapshot("tdc_data_model", positional, snapshot_at=snapshot_at, source_run_id=1, source="test")
    )


FORM = {"projects": ["F999X"], "departments": [], "region": "车体区域", "planText": "", "feishuLink": ""}


def test_plugin_loads_with_nav(client) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    data = http.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "sign-daily")
    assert record["status"] == "loaded", record.get("error")
    assert http.get("/plugins/sign-daily/static/report.js").status_code == 200


def test_state_without_data_explains_next_step(client) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    data = http.get("/api/p/sign-daily/state").get_json()["data"]
    assert data["data"] is None
    assert "一键生成" in data["dataError"]
    assert data["config"]["roleDepartments"]["空调电子"] == "电子电器"
    response = http.post("/api/p/sign-daily/generate", json=FORM)
    assert response.status_code == 409


def test_generate_twice_shows_day_over_day_delta(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, today = client
    rows = _flow_rows()
    _publish(db, rows)
    state = http.get("/api/p/sign-daily/state").get_json()["data"]
    assert state["options"] == {"projects": ["E50", "F999X"], "departments": ["内饰科", "车身科"]}

    first = http.post("/api/p/sign-daily/generate", json=FORM).get_json()
    assert first["ok"] is True, first
    report = first["data"]
    assert report["delta"] is None
    assert report["summary"]["total"]["flows"] == 4
    assert [n["kind"] for n in report["notices"]] == ["longCycleMissing"]
    assert http.get("/api/p/sign-daily/state").get_json()["data"]["config"]["form"]["projects"] == ["F999X"]

    # 第二天 0004 关闭
    today["value"] = date(2026, 10, 3)
    for row in rows:
        if row["流水单号"] == "F999X-3D-0004":
            row.update({"状态": "已完成", "已签人数": 2, "签署率": "100.00%", "专家/经理": "经理癸"})
    _publish(db, rows, snapshot_at="2026-10-03T08:00:00Z")
    second = http.post("/api/p/sign-daily/generate", json=FORM).get_json()["data"]
    assert second["delta"]["total"]["complete"] == 1
    assert second["delta"]["total"]["locked"] == 1
    assert second["previousDate"] == "2026-10-02"
    assert "3D单完成3(+1)/4份" in second["summaryLines"][2]


def test_empty_scope_and_validation(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _flow_rows())
    empty = http.post("/api/p/sign-daily/generate", json={**FORM, "projects": ["NOPE"]})
    assert empty.status_code == 404
    assert empty.get_json()["error"]["message"] == "范围内没有 3D单"
    bad = http.post("/api/p/sign-daily/generate", json={**FORM, "projects": "F999X"})
    assert bad.status_code == 400
    unknown = http.post("/api/p/sign-daily/config", json={"nope": 1})
    assert unknown.status_code == 400


def test_long_cycle_confirmation_and_recipients_flow(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _flow_rows())
    http.post("/api/p/sign-daily/config", json={
        "longCycleNames": ["前门内板"],
        "addressBook": '"会签乙"<b@example.com>',
    })
    report = http.post("/api/p/sign-daily/generate", json=FORM).get_json()["data"]
    assert [h["part"] for h in report["longCycleHits"]] == ["前门内板右", "前门内板左"]
    assert report["summary"]["longCycle"]["flows"] == 0  # 未确认前不计入

    http.post("/api/p/sign-daily/config", json={
        "longCycleConfirmed": {"F999X": {"前门内板右": True, "前门内板左": True}},
        "recipients": {report["scopeKey"]: {"to": '"领导"<lead@example.com>', "cc": ""}},
    })
    report = http.post("/api/p/sign-daily/generate", json=FORM).get_json()["data"]
    assert report["longCycleHits"] == []
    assert report["summary"]["longCycle"]["flows"] == 1
    assert [r["address"] for r in report["recipients"]["to"]] == ["lead@example.com", "b@example.com"]

    response = http.post("/api/p/sign-daily/eml", json=FORM)
    assert response.status_code == 200
    assert response.mimetype == "message/rfc822"
    message = email.message_from_bytes(response.data, policy=policy.default)
    assert message["Subject"] == "F999X项目3D单签署进展-车体区域-20261002"
    assert "b@example.com" in message["To"]


class _FakeArchive:
    def __init__(self, result=None, error=None):  # type: ignore[no-untyped-def]
        self.result, self.error, self.calls = result, error, []

    def sync_now(self, job_key):  # type: ignore[no-untyped-def]
        self.calls.append(job_key)
        if self.error:
            raise self.error
        return self.result


def test_refresh_runs_tdc_archive_job_and_reports_failure(client) -> None:  # type: ignore[no-untyped-def]
    app, http, _, _ = client
    ok = _FakeArchive({"exitCode": 0, "results": [{"outcome": "completed"}]})
    app.extensions["scheduled_archive_admin"] = ok
    assert http.post("/api/p/sign-daily/refresh", json={}).get_json()["ok"] is True
    assert ok.calls == ["tdc_data_model"]

    app.extensions["scheduled_archive_admin"] = _FakeArchive(
        {"exitCode": 1, "results": [{"outcome": "failed", "errorMessage": "登录已过期"}]}
    )
    failed = http.post("/api/p/sign-daily/refresh", json={})
    assert failed.status_code == 502
    assert "登录已过期" in failed.get_json()["error"]["message"]

    app.extensions["scheduled_archive_admin"] = _FakeArchive(
        {"exitCode": 1, "results": [{"outcome": "failed", "errorType": "job_not_ready"}]}
    )
    message = http.post("/api/p/sign-daily/refresh", json={}).get_json()["error"]["message"]
    assert message.startswith("TDC 抓取未完成：到「自动归档」页检查数模设计审核报表任务的配置")
