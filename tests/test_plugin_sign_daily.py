# -*- coding: utf-8 -*-
"""sign-daily v2.0 接口：快照与基线、长周期复核、范围（A9）和后台抓取。"""

from __future__ import annotations

import base64
import email
import fnmatch
import json
import os
import sys
import time
from email import policy
from datetime import date, timezone
from pathlib import Path

import pytest

import web.app as web_app
from services.deliverable_form_analysis import build_form_snapshot, form_definition
from tests.test_ewo_official_rows import write_workbook

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADERS = form_definition("tdc_data_model")["headerRows"][0]
API = "/api/p/sign-daily"
SCOPE = {"projects": ["F610M"], "departments": [], "region": "车体区域"}


def _row(serial: str, **values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "流水单号": serial,
        "项目/车型": "F610M",
        "部门": "车身科",
        "申请人": "林锦辉",  # 花名册：车身科
        "申请日期": "2026-09-23 10:00:00",
        "零件号": f"{serial}-P1",
        "零件名称": "前门铰链",
        "应签人数": 2,
        "已签人数": 1,
        "未签人数": 1,
        "签署率": "50.00%",
        "状态": "进行中",
    }
    base.update(values)
    return base


def _rows() -> list[dict[str, object]]:
    return [
        # 会签中：外区域冲压未在册的人是当前待办
        _row("S1", 零件名称="前门内板", 冲压="冲压丁(未签)", 车身="张帅", 待审批人员="冲压丁"),
        _row("S1", 零件号="S1-P2", 零件名称="前门铰链", 冲压="冲压丁(未签)", 车身="张帅", 待审批人员="冲压丁"),
        # 审批中：首席/总监未在册
        _row("S2", 零件名称="前门内板加强板", 车身="张帅", **{"首席/总监": "总监辛(未签)"}, 待审批人员="总监辛"),
        # 已完成
        _row("S3", 零件名称="后侧门外板", 车身="张帅", 应签人数=1, 已签人数=1, 未签人数=0, 签署率="100%", 状态="已完成"),
        # TDC 部门是结构工程科，申请人在册属车体科（A9）
        _row("S4", 部门="结构工程科", 申请人="蒋运飞", 零件名称="顶棚", 冲压="冲压丁(未签)", 待审批人员="冲压丁"),
        # 已废弃
        _row("S5", 状态="已废弃"),
        _row("E1", **{"项目/车型": "E50"}, 零件名称="前门内板", 车身="张帅", 应签人数=1, 已签人数=1, 未签人数=0,
             签署率="100%", 状态="已完成"),
    ]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "sign-daily.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["sign-daily"])
    app.config.update(TESTING=True)
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_DATA_TZ", timezone.utc)
    today = {"value": date(2026, 10, 2)}
    monkeypatch.setattr(backend, "_today", lambda: today["value"])
    return app, app.test_client(), db_cls(tmp_path / "sign-daily.db"), today


def _publish(db, rows, snapshot_at: str) -> None:  # type: ignore[no-untyped-def]
    positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in rows]
    db.publish_deliverable_form_snapshot(
        build_form_snapshot("tdc_data_model", positional, snapshot_at=snapshot_at, source_run_id=1, source="test")
    )


def _ok(response):  # type: ignore[no-untyped-def]
    payload = response.get_json()
    assert payload["ok"] is True, payload
    return payload["data"]


def _confirm_all(http, report, project="F610M"):  # type: ignore[no-untyped-def]
    items = [{"key": i["normalized"], "include": i["checked"]} for i in report["longCycle"]["review"]
             if i["project"] == project]
    _ok(http.post(f"{API}/long-cycle", json={"project": project, "items": items}))


def test_state_lists_applicant_departments_and_data_date(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, today = client
    assert _ok(http.get(f"{API}/state"))["data"] is None
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    state = _ok(http.get(f"{API}/state"))
    assert state["data"]["dataDate"] == "2026-10-02"
    assert state["options"]["projects"] == ["E50", "F610M"]
    assert state["options"]["departments"][:5] == ["车身科", "车体科", "内饰科", "外饰科", "车体架构集成科"]
    assert state["seedVersion"]


def test_first_generation_has_no_delta_and_charts_follow_spec(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, today = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    report = _ok(http.post(f"{API}/generate", json=SCOPE))
    assert report["delta"] is None and report["baseDate"] is None
    assert not any("首次生成" in line for line in report["summaryLines"])  # 验收 14：不再显示该说明行
    assert report["summaryLines"][1].startswith("长周期签单情况：会签签单率")
    assert report["summaryLines"][2].startswith("总签单情况：会签签单率")
    for line in report["summaryLines"][1:3]:  # 汇总行顺序与不再渲染总签单率
        assert "总签单率" not in line
        assert line.index("会签签单率") < line.index("3D单完成") < line.index("已锁定发布") < line.index("T2发布率")
    assert "(" not in "".join(report["summaryLines"][:3])
    total = report["summary"]["total"]
    assert (total["flows"], total["parts"], total["complete"], total["locked"]) == (4, 5, 1, 1)
    external = report["charts"]["external"]
    assert [(g["group"], g["bars"][0]["name"], g["bars"][0]["count"]) for g in external] == [("冲压", "冲压丁", 2)]
    assert [g["group"] for g in report["charts"]["approval"]] == ["首席/总监"]
    assert report["charts"]["approval"][0]["bars"][0]["label"] == "总监辛（未在册）"
    assert [r["serial"] for r in report["flows"]] == ["S1", "S4", "S2"]  # 会签中在前
    assert report["snapshotSaved"] is True


def test_scope_uses_applicant_roster_department(client) -> None:  # type: ignore[no-untyped-def]  # 验收 6
    _, http, db, today = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    report = _ok(http.post(f"{API}/preview", json={**SCOPE, "departments": ["车体科"]}))
    assert [r["serial"] for r in report["flows"]] == ["S4"]
    assert report["flows"][0]["department"] == "车体科"


def test_long_cycle_review_blocks_export_until_confirmed(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, today = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    report = _ok(http.post(f"{API}/preview", json=SCOPE))
    review = {i["normalized"]: i for i in report["longCycle"]["review"]}
    assert review["前门内板"]["checked"] is True and review["前门内板"]["flows"] == 1
    assert review["前门内板加强板"]["checked"] is False  # 验收 12
    assert report["exportBlocked"] is True
    assert report["notices"][0] == {"kind": "longCycleReview", "blocking": True, "text": "3 项长周期初筛待确认"}
    _confirm_all(http, report)
    again = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert again["exportBlocked"] is False and again["longCycle"]["review"] == []
    assert again["summary"]["longCycle"]["flows"] == 2  # S1 前门内板、S3 后侧门外板
    other = _ok(http.post(f"{API}/preview", json={**SCOPE, "projects": ["E50"]}))
    assert other["exportBlocked"] is True  # 验收 13：换项目仍提示


def test_next_day_delta_and_rule_change_does_not_fake_change(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, today = client
    rows = _rows()
    _publish(db, rows, "2026-10-02T08:00:00Z")
    first = _ok(http.post(f"{API}/generate", json=SCOPE))
    _confirm_all(http, first)

    # 第二天：S2 审批完成并关闭；同时把「前门内板加强板」改判为长周期（验收 16）
    for row in rows:
        if row["流水单号"] == "S2":
            row.update({"状态": "已完成", "已签人数": 2, "未签人数": 0, "签署率": "100%", "首席/总监": "总监辛"})
    today["value"] = date(2026, 10, 3)
    _publish(db, rows, "2026-10-03T08:00:00Z")
    _ok(http.post(f"{API}/long-cycle", json={"project": "F610M", "items": [{"key": "前门内板加强板", "include": True}]}))
    second = _ok(http.post(f"{API}/generate", json=SCOPE))
    assert second["baseDate"] == "2026-10-02"
    assert second["delta"]["total"]["complete"] == 1 and second["delta"]["total"]["locked"] == 1
    # 基线按今天的结论重算：S2 在基线里也算长周期，长周期份数不因改判而变
    assert second["delta"]["longCycle"]["flows"] == 0
    assert second["delta"]["longCycle"]["complete"] == 1
    assert "3D单完成2(+1)/4份" in second["summaryLines"][2]
    assert not any("首次生成" in line for line in second["summaryLines"])

    # 同一天重新生成：覆盖当天快照，照常显示括号（D1）
    again = _ok(http.post(f"{API}/generate", json=SCOPE))
    assert again["stale"] is False and again["baseDate"] == "2026-10-02"

    # 第三天抓取失败，用最近一次数据（10-03）生成：不写快照、不显示括号（验收 18）
    today["value"] = date(2026, 10, 4)
    stale = _ok(http.post(f"{API}/generate", json=SCOPE))
    assert stale["stale"] is True and stale["delta"] is None and stale["snapshotSaved"] is False
    assert stale["dataDate"] == "2026-10-03"


def test_validation(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, today = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    assert http.post(f"{API}/preview", json={**SCOPE, "projects": "F610M"}).status_code == 400
    assert http.post(f"{API}/preview", json={**SCOPE, "projects": ["NOPE"]}).status_code == 404
    assert http.post(f"{API}/long-cycle", json={"project": "F610M", "items": []}).status_code == 400
    assert http.post(f"{API}/long-cycle", json={"project": "F610M", "items": [{"key": "x", "include": "yes"}]}).status_code == 400
    assert http.get(f"{API}/refresh/../../etc").status_code == 404
    assert http.get(f"{API}/refresh/not-a-task").status_code == 400
    cleared = _ok(http.post(f"{API}/long-cycle/clear", json={"project": "F610M"}))
    assert cleared["cleared"] == 0


class _FakeArchive:
    def __init__(self, result):  # type: ignore[no-untyped-def]
        self.result, self.calls = result, []

    def sync_now(self, job_key):  # type: ignore[no-untyped-def]
        self.calls.append(job_key)
        return self.result


def _wait(http, task_id, timeout=5.0):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = _ok(http.get(f"{API}/refresh/{task_id}"))
        if view["status"] not in ("queued", "running"):
            return view
        time.sleep(0.05)
    raise AssertionError("refresh task did not finish")


def test_refresh_runs_in_background(client) -> None:  # type: ignore[no-untyped-def]
    app, http, _, _ = client
    app.extensions["scheduled_archive_admin"] = _FakeArchive({"exitCode": 0, "results": [{"outcome": "completed"}]})
    started = _ok(http.post(f"{API}/refresh", json={}))
    view = _wait(http, started["taskId"])
    assert (view["status"], view["percent"]) == ("succeeded", 100)

    app.extensions["scheduled_archive_admin"] = _FakeArchive(
        {"exitCode": 1, "results": [{"outcome": "failed", "errorType": "job_not_ready"}]}
    )
    failed = _wait(http, _ok(http.post(f"{API}/refresh", json={}))["taskId"])
    assert failed["status"] == "failed"
    assert failed["error"].startswith("TDC 抓取未完成：到「自动归档」页检查")

    class _Missing:
        def sync_now(self, job_key):  # type: ignore[no-untyped-def]
            raise KeyError(job_key)

    app.extensions["scheduled_archive_admin"] = _Missing()
    missing = _wait(http, _ok(http.post(f"{API}/refresh", json={}))["taskId"])
    assert missing["error"].startswith("未找到 TDC 数模设计审核流程归档任务")


class _Task:
    def __init__(self) -> None:
        self.progress: list[dict[str, object]] = []
        self.is_cancelled = False

    def update_progress(self, **values: object) -> None:
        self.progress.append(values)


def test_refresh_waits_for_running_scheduler_crawl_instead_of_crawling_twice() -> None:  # R3
    service = sys.modules.get("vse_plugins.sign_daily.service")
    if service is None:  # 单独跑本用例时按文件加载
        import importlib
        web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["sign-daily"])
        service = importlib.import_module("vse_plugins.sign_daily.service")

    class _Db:
        def __init__(self) -> None:
            self.latest = {"id": 1}
            self.reads = 0

        def get_latest_deliverable_form_snapshot(self, _key):  # type: ignore[no-untyped-def]
            self.reads += 1
            if self.reads >= 4:  # 调度器那次抓取落库
                self.latest = {"id": 2}
            return self.latest

    archive = _FakeArchive({"exitCode": 1, "results": [{"outcome": "failed", "errorType": "lease_busy"}]})
    task = _Task()
    run = service.make_refresh_worker(archive, _Db(), lambda result: "x", sleep=lambda _s: None)
    run(task)
    assert archive.calls == ["tdc_data_model"]
    assert task.progress[-1] == {"stage": "抓取完成", "percent": 100}

    never = service.make_refresh_worker(
        archive, type("D", (), {"get_latest_deliverable_form_snapshot": lambda self, k: {"id": 1}})(),
        lambda result: "x", wait_timeout=1, poll_seconds=0.5, sleep=lambda _s: None,
    )
    with pytest.raises(RuntimeError, match="超时"):
        never(_Task())


# ── 关注清单、导出与设置（§9、§7、§10）──────────────────────────────────

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


def _set_job_watchlist(db, scope: str, serials: list[str]) -> None:  # type: ignore[no-untyped-def]
    job = next(j for j in db.list_archive_jobs() if j["job_key"] == "tdc_data_model")
    db.update_archive_job_config("tdc_data_model", enabled=False, filters={"syncScope": scope, "watchlist": serials},
                                 output_subdir="", expected_updated_at=job["updated_at"], actor="cli")


def test_watchlist_only_report(client) -> None:  # type: ignore[no-untyped-def]  # 验收 27
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    _set_job_watchlist(db, "all", ["S1", "S2", "S3", "S4", "S9"])
    report = _ok(http.post(f"{API}/preview", json={**SCOPE, "watchlistOnly": True}))
    assert report["summary"]["total"]["flows"] == 4
    assert "统计范围：关注清单 4 份" in report["summaryLines"]
    missing = next(n for n in report["notices"] if n["kind"] == "watchlistMissing")
    assert missing["names"] == ["S9"]
    assert report["scopeKey"].endswith('"watchlistOnly": true}')


def test_full_report_refuses_watchlist_only_data(client) -> None:  # type: ignore[no-untyped-def]  # S11、验收 24
    _, http, db, _ = client
    positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in _rows()[:2]]
    db.publish_deliverable_form_snapshot(build_form_snapshot(
        "tdc_data_model", positional, snapshot_at="2026-10-02T08:00:00Z", source_run_id=1, source="test",
        coverage={"kind": "watchlist", "serials": ["S1"], "missing": []}))
    response = http.post(f"{API}/preview", json=SCOPE)
    assert response.status_code == 409 and "只同步了关注清单" in response.get_json()["error"]["message"]
    empty = http.post(f"{API}/preview", json={**SCOPE, "watchlistOnly": True})
    assert empty.status_code == 409 and "关注清单为空" in empty.get_json()["error"]["message"]
    _set_job_watchlist(db, "watchlist", ["S1"])
    assert _ok(http.post(f"{API}/preview", json={**SCOPE, "watchlistOnly": True}))["coverage"] == "watchlist"


def test_eml_export_blocked_until_review_and_embeds_png(client) -> None:  # type: ignore[no-untyped-def]  # §7、§10
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    key = _ok(http.post(f"{API}/preview", json=SCOPE))["scopeKey"]
    _ok(http.post(f"{API}/config", json={
        "addressBook": '"冲压丁"<d@x.com>',
        "preferences": {key: {"to": '"领导"<lead@x.com>', "cc": ""}},
    }))
    report = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert report["recipients"]["added"] == [{"name": "冲压丁", "address": "d@x.com"}]
    assert "总监辛" in report["recipients"]["missing"]  # 有未签单情况但通讯录里没有邮箱，导出前列出
    images = {key: PNG for key in report["chartsWithData"]}
    blocked = http.post(f"{API}/eml", json={**SCOPE, "images": images})
    assert blocked.status_code == 409  # 有待复核项时禁止导出（§1 缺陷 8）
    response = http.post(f"{API}/eml", json={**SCOPE, "images": images, "proceedWithSuggestion": True})
    assert response.status_code == 200 and response.mimetype == "message/rfc822"
    message = email.message_from_bytes(response.data, policy=policy.default)
    assert message["Subject"] == "F610M项目3D单签署进展-车体区域-20261002"
    assert [a.addr_spec for a in message["To"].addresses] == ["lead@x.com", "d@x.com"]
    cids = sorted(p["Content-ID"] for p in message.walk() if p.get_content_type() == "image/png")
    assert cids == sorted(f"<sd-{key}>" for key in report["chartsWithData"])
    wrong = http.post(f"{API}/eml", json={**SCOPE, "images": {"external": PNG}, "proceedWithSuggestion": True})
    assert wrong.status_code == 400


def test_settings_routes_drive_attribution(client) -> None:  # type: ignore[no-untyped-def]  # 验收 2、M6
    _, http, db, _ = client
    _publish(db, [_row("S1", 内外饰="梁海峰(未签)", 待审批人员="梁海峰")], "2026-10-02T08:00:00Z")
    first = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert [g["group"] for g in first["charts"]["sections"]] == ["内饰科"]
    _ok(http.post(f"{API}/settings/roster/person", json={"name": "梁海峰", "department": None}))
    second = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert [g["group"] for g in second["charts"]["sections"]] == ["内外饰（未在册）"]
    assert any(n["kind"] == "needsEntry" and "梁海峰" in n["text"] for n in second["notices"])
    view = _ok(http.get(f"{API}/settings/roster"))
    assert next(r for r in view["rows"] if r["name"] == "梁海峰")["source"] == "已删除"

    preview = _ok(http.post(f"{API}/settings/roster/import", json={"csv": "姓名,科室\n梁海峰,外饰科\n", "commit": False}))
    assert preview["plan"]["counts"]["added"] == 1 and preview["committed"] is False
    committed = _ok(http.post(f"{API}/settings/roster/import", json={"csv": "姓名,科室\n梁海峰,外饰科\n", "commit": True}))
    assert committed["committed"] is True and committed["view"]["backups"][0]["reason"] == "导入前"
    assert [g["group"] for g in _ok(http.post(f"{API}/preview", json=SCOPE))["charts"]["sections"]] == ["外饰科"]
    with_errors = http.post(f"{API}/settings/roster/import", json={"csv": "姓名,科室\n甲,结构工程科\n", "commit": True})
    assert with_errors.status_code == 409
    assert http.get(f"{API}/settings/roster.csv").data.decode("utf-8-sig").startswith("姓名,科室")
    assert http.post(f"{API}/settings/roster/person", json={"name": "乙", "department": "结构工程科"}).status_code == 400


def test_config_validation_and_refresh_scope(client) -> None:  # type: ignore[no-untyped-def]
    app, http, db, _ = client
    assert http.post(f"{API}/config", json={"thresholds": {"warnDays": 10, "overdueDays": 5}}).status_code == 400
    assert http.post(f"{API}/config", json={"areaNames": {"车身": "x"}}).status_code == 400
    assert http.post(f"{API}/config", json={"nope": 1}).status_code == 400
    _ok(http.post(f"{API}/config", json={"thresholds": {"warnDays": 5, "overdueDays": 10}, "areaNames": {"冲压": "冲压科"}}))
    state = _ok(http.get(f"{API}/state"))
    assert state["thresholds"]["overdueDays"] == 10 and state["areaNames"]["冲压"] == "冲压科"
    _set_job_watchlist(db, "watchlist", ["S1"])
    app.extensions["scheduled_archive_admin"] = _FakeArchive({"exitCode": 0, "results": [{"outcome": "completed"}]})
    conflict = http.post(f"{API}/refresh", json={"watchlistOnly": False})
    assert conflict.status_code == 409 and "仅关注清单" in conflict.get_json()["error"]["message"]


def _xlsx(rows: list[list[str]]) -> bytes:
    import io
    from xml.sax.saxutils import escape
    from zipfile import ZipFile

    def ref(col: int, row: int) -> str:
        return f"{chr(64 + col)}{row}"

    body = "".join(
        f'<row r="{r}">' + "".join(
            f'<c r="{ref(c, r)}" t="inlineStr"><is><t>{escape(v)}</t></is></c>' for c, v in enumerate(values, 1)
        ) + "</row>"
        for r, values in enumerate(rows, 1)
    )
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            '2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'))
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'))
        archive.writestr("xl/worksheets/sheet1.xml", (
            '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            f'2006/main"><sheetData>{body}</sheetData></worksheet>'))
    return buffer.getvalue()


def test_roster_import_accepts_xlsx(client) -> None:  # type: ignore[no-untyped-def]  # §7：宿主自带 xlsx 读取
    _, http, _, _ = client
    data = _xlsx([["责任工程师名称", "责任工程师专业科室"], ["新人甲(x1)", "车身科"], ["新人甲(x2)", "车身科"]])
    payload = {"xlsx": base64.b64encode(data).decode(), "commit": True}
    result = _ok(http.post(f"{API}/settings/roster/import", json=payload))
    assert result["plan"]["counts"]["added"] == 1 and result["plan"]["merged"] == 1
    assert any(r["name"] == "新人甲" and r["source"] == "本地新增" for r in result["view"]["rows"])
    bad = http.post(f"{API}/settings/roster/import", json={"xlsx": base64.b64encode(b"not a zip").decode()})
    message = bad.get_json()["error"]["message"]
    # 2026-11-11：不再建议「另存为 CSV」。读不了就是读不了——可能不完整/损坏/受终端加密。
    assert bad.status_code == 400
    assert message == _DAMAGED_TEXT
    assert "另存为" not in message and "换浏览器" not in message and "换上传" not in message


def test_watchlist_report_does_not_overwrite_same_day_full_snapshot(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    _ok(http.post(f"{API}/generate", json=SCOPE))  # 当天全量快照
    positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in _rows()[:1]]
    db.publish_deliverable_form_snapshot(build_form_snapshot(
        "tdc_data_model", positional, snapshot_at="2026-10-02T09:00:00Z", source_run_id=2, source="test",
        coverage={"kind": "watchlist", "serials": ["S1"], "missing": []}))
    _set_job_watchlist(db, "watchlist", ["S1"])
    _ok(http.post(f"{API}/generate", json={**SCOPE, "watchlistOnly": True}))
    with db.get_connection() as conn:
        kind = conn.execute("SELECT scope_kind FROM p_sign_daily_snapshot_meta WHERE data_date = '2026-10-02'").fetchone()
    assert kind["scope_kind"] == "all"  # 第二天的全量日报仍有基线


# ── 2026-10-29 生产测试两处口径修复 ────────────────────────────────────

def test_selection_without_data_keeps_subject_and_reports_it(client) -> None:  # type: ignore[no-untyped-def]
    """选择里留着本次数据已不存在的项目时，标题只写实际计入的项目，并显式披露。"""
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    report = _ok(http.post(f"{API}/preview", json={**SCOPE, "projects": ["F610S", "F610M"]}))
    assert report["projectLabel"] == "F610M"
    assert report["subject"] == "F610M项目3D单签署进展-车体区域-20261002"
    assert report["selectedWithoutData"] == ["F610S"]
    notice = next(n for n in report["notices"] if n["kind"] == "selectedWithoutData")
    assert notice["projects"] == ["F610S"] and "F610S" in notice["text"]
    assert report["summary"]["total"]["flows"] == 4  # 与只选 F610M 相同：幻影项目不参与统计
    assert "F610S" not in report["html"] and "F610S" not in report["text"]  # 正文任何位置都不留残留项目

    both = _ok(http.post(f"{API}/preview", json={**SCOPE, "projects": ["E50", "F610M"]}))
    assert both["projectLabel"] == "E50&F610M"  # 按选择顺序，不是字典序
    assert both["selectedWithoutData"] == []
    assert not any(n["kind"] == "selectedWithoutData" for n in both["notices"])


def test_text_status_does_not_block_export(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    gate = _ok(http.post(f"{API}/preview", json=SCOPE))["statusGate"]
    assert gate == {"enabled": True, "blocked": False, "codes": [], "text": ""}


def test_numeric_status_codes_block_export(client) -> None:  # type: ignore[no-untyped-def]
    """状态列是未映射的数字码时：预览照出并列出码值，导出接口拒绝；单开关可回滚。"""
    _, http, db, _ = client
    rows = [
        _row("S1", 零件名称="前门内板", 冲压="冲压丁(未签)", 待审批人员="冲压丁"),
        _row("S2", 状态="6"),
        _row("S3", 状态="3"),
    ]
    _publish(db, rows, "2026-10-02T08:00:00Z")
    report = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert report["exportBlocked"] is True  # 长周期待确认先挡着，先确认再验门禁
    _confirm_all(http, report)
    report = _ok(http.post(f"{API}/preview", json=SCOPE))
    gate = report["statusGate"]
    assert report["exportBlocked"] is False
    assert gate["enabled"] is True and gate["blocked"] is True
    assert gate["codes"] == [{"code": "3", "flows": 1}, {"code": "6", "flows": 1}]
    assert "3：1 份" in gate["text"] and "6：1 份" in gate["text"]
    images = {key: PNG for key in report["chartsWithData"]}
    blocked = http.post(f"{API}/eml", json={**SCOPE, "images": images, "proceedWithSuggestion": True})
    assert blocked.status_code == 409
    assert blocked.get_json()["error"]["type"] == "StatusGateBlocked"
    assert "数字码" in blocked.get_json()["error"]["message"]

    assert http.post(f"{API}/config", json={"statusGateEnabled": "yes"}).status_code == 400
    _ok(http.post(f"{API}/config", json={"statusGateEnabled": False}))
    off = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert off["statusGate"]["blocked"] is False and off["statusGate"]["codes"]  # 关闭后仍披露码值
    allowed = http.post(f"{API}/eml", json={**SCOPE, "images": images, "proceedWithSuggestion": True})
    assert allowed.status_code == 200 and allowed.mimetype == "message/rfc822"


def test_status_gate_recognizes_numeric_forms(client) -> None:  # type: ignore[no-untyped-def]
    """只识别整数形态（含 Excel 浮点转写与前后空白）；中文数字与文本不拦。"""
    _, http, db, _ = client
    rows = [
        _row("S1", 状态="3.0"),
        _row("S2", 状态=" 6 "),
        _row("S3", 状态="三"),
        _row("S4", 状态="已废弃"),
    ]
    _publish(db, rows, "2026-10-02T08:00:00Z")
    report = _ok(http.post(f"{API}/preview", json=SCOPE))
    assert report["statusGate"]["codes"] == [{"code": "3", "flows": 1}, {"code": "6", "flows": 1}]
    assert report["statusGate"]["blocked"] is True
    assert report["summary"]["total"]["flows"] == 3  # 3.0 / 6 / 三 计入，字面已废弃剔除


def test_scope_preference_migration_keeps_other_scopes(client) -> None:  # type: ignore[no-untyped-def]
    """取消孤儿时的迁移载荷只带新 key；后端必须保留其它范围与旧 key（整表替换会静默清空）。"""
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    old_key = json.dumps({"projects": ["F610M", "F610S"], "departments": []}, ensure_ascii=False)
    new_key = json.dumps({"projects": ["F610M"], "departments": []}, ensure_ascii=False)
    other_key = json.dumps({"projects": ["E50"], "departments": []}, ensure_ascii=False)
    old_prefs = {"to": '"甲"<a@x.com>', "cc": "", "region": "车体区域",
                 "greeting": "各位领导、同事：", "planText": "旧范围", "feishuLink": ""}
    other_prefs = {**old_prefs, "to": '"乙"<b@x.com>', "planText": "别的范围"}
    _ok(http.post(f"{API}/config", json={"preferences": {old_key: old_prefs, other_key: other_prefs}}))
    before = _ok(http.get(f"{API}/state"))["preferences"]
    _ok(http.post(f"{API}/config", json={"preferences": {new_key: dict(before[old_key])}}))
    after = _ok(http.get(f"{API}/state"))["preferences"]
    assert after[old_key] == old_prefs and after[other_key] == other_prefs  # 旧 key 与其它范围原样保留
    assert after[new_key]["to"] == '"甲"<a@x.com>' and after[new_key]["planText"] == "旧范围"


# ── 本地报表导入（方案 B：共享表零写入；2026-11-16 起只写自有的手工基线表）──────


def _workbook(tmp_path: Path, rows, *, drift: bool = False, name: str = "import.xlsx") -> Path:
    header = list(HEADERS)
    if drift:
        header[2] = header[2] + "(旧模板)"
    matrix = [[row.get(key) for key in header] for row in rows]
    return write_workbook(tmp_path / name, header, matrix, sheet_name="Sheet1")


def _upload(http, path: Path, **form):
    with path.open("rb") as handle:
        data = {"file": (handle, path.name), **form}
        return http.post(f"{API}/import-form", data=data, content_type="multipart/form-data")


def _snapshot_counts(db) -> dict[str, int]:
    patterns = ("deliverable_form_snapshots", "*snapshot_meta*", "*snapshot_rows*", "*long_cycle_conclusion*",
                "*_config", "*scheduled_reports*", "*_roster_local*", "*_rule_local*")
    with db.get_connection() as conn:
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {}
        for name in names:
            if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return counts


def test_import_form_generates_report_and_writes_nothing(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")  # 库里本来就有一份归档快照
    before = _snapshot_counts(db)

    report = _ok(_upload(http, _workbook(tmp_path, _rows()), dataDate="2026-11-06", projects='["F610M"]'))

    assert report["mode"] == "manual"
    assert report["importMeta"]["rowCount"] == len(_rows())
    assert report["importMeta"]["dataDate"] == "2026-11-06"
    assert report["importMeta"]["verified"] == "structure-only"
    assert report["dataDate"] == "2026-11-06"
    assert report["stale"] is False
    assert report["snapshotSaved"] is False
    assert report["delta"] is None and report["baseDate"] is None
    assert report["charts"]["external"]  # 欠账数据照常算
    assert report["subject"].endswith("20261106")
    assert _snapshot_counts(db) == before  # 共享表零写入（手工基线表不在 _snapshot_counts 的模式里）


def test_import_form_requires_confirmed_date(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    response = _upload(http, _workbook(tmp_path, _rows()), dataDate="")
    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "ValidationError"


def test_import_form_rejects_drifted_header(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    response = _upload(http, _workbook(tmp_path, _rows(), drift=True), dataDate="2026-11-06")
    assert response.status_code == 422
    assert response.get_json()["error"]["type"] == "E_HEADER_MISMATCH"


def test_eml_is_refused_for_manual_reports(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    response = http.post(f"{API}/eml", json={"mode": "manual", "images": {}})
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "EmlUnavailableForManual"


# ── 监控目录：以最后修改时间最晚的为准，不合格转人工 ──────────────────


def _scan(http, directory: Path):
    return http.post(f"{API}/import-scan", json={"dir": str(directory)})


def _aging(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_import_scan_picks_newest(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    old = _workbook(tmp_path, _rows(), name="old.xlsx")
    new = _workbook(tmp_path, _rows(), name="new.xlsx")
    _aging(old, 3600)
    _aging(new, 60)
    (tmp_path / "~$temp.xlsx").write_bytes(b"not a workbook")

    data = _ok(_scan(http, tmp_path))
    assert data["selected"]["name"] == "new.xlsx"
    assert data["reason"] == ""
    assert data["selected"]["token"]
    skipped = {entry["name"]: entry["reason"] for entry in data["entries"]}
    assert skipped["~$temp.xlsx"]  # 临时文件被跳过并给出原因
    assert data["roots"]


def test_import_scan_does_not_fall_back_to_older_file(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    good = _workbook(tmp_path, _rows(), name="good.xlsx")
    bad = _workbook(tmp_path, _rows(), drift=True, name="bad.xlsx")
    _aging(good, 3600)
    _aging(bad, 60)

    data = _ok(_scan(http, tmp_path))
    assert data["selected"] is None
    assert data["reason"] == "E_HEADER_MISMATCH"  # 停在最新那份，不退回 good.xlsx


def test_import_scan_rejects_dir_outside_roots(client) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    response = _scan(http, Path("C:/Windows"))
    assert response.status_code == 422
    assert response.get_json()["error"]["type"] == "E_DIR_NOT_ALLOWED"


def test_import_form_accepts_scan_token(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    before = _snapshot_counts(db)
    _workbook(tmp_path, _rows(), name="newest.xlsx")

    scanned = _ok(_scan(http, tmp_path))
    selected = scanned["selected"]
    response = http.post(
        f"{API}/import-form",
        data={
            "scanDirId": scanned["dirId"],
            "scanName": selected["name"],
            "scanToken": selected["token"],
            "dataDate": "2026-11-06",
            "projects": '["F610M"]',
        },
        content_type="multipart/form-data",
    )
    report = _ok(response)
    assert report["mode"] == "manual"
    assert report["importMeta"]["sourceName"] == "newest.xlsx"
    assert report["dataDate"] == "2026-11-06"
    assert _snapshot_counts(db) == before


def test_import_form_rejects_stale_scan_token(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    target = _workbook(tmp_path, _rows(), name="newest.xlsx")
    scanned = _ok(_scan(http, tmp_path))
    selected = scanned["selected"]

    _aging(target, 600)  # 扫描之后文件被改动 → 令牌失效
    response = http.post(
        f"{API}/import-form",
        data={
            "scanDirId": scanned["dirId"],
            "scanName": selected["name"],
            "scanToken": selected["token"],
            "dataDate": "2026-11-06",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "E_SCAN_STALE"


# ── 顾问复核后新增：字节绑定、父目录校验、句柄表上界、.eml 触发面 ──────


def _importer():
    return sys.modules["vse_plugins.sign_daily.importer"]


def test_read_verified_bytes_rejects_changed_file(tmp_path) -> None:
    importer = _importer()
    target = _workbook(tmp_path, _rows(), name="x.xlsx")
    signature = importer.stat_signature(target)
    assert importer.read_verified_bytes(target, signature)  # 未改动可读

    _aging(target, 600)  # mtime 变了
    with pytest.raises(importer.ManualImportError) as info:
        importer.read_verified_bytes(target, signature)
    assert info.value.code == "E_SCAN_STALE"


def test_ensure_direct_child_blocks_traversal(tmp_path) -> None:
    importer = _importer()
    inside = _workbook(tmp_path, _rows(), name="x.xlsx")
    importer.ensure_direct_child(inside, tmp_path)  # 正常路径不抛
    with pytest.raises(importer.ManualImportError) as info:
        importer.ensure_direct_child(tmp_path / ".." / "x.xlsx", tmp_path)
    assert info.value.code == "E_DIR_NOT_ALLOWED"


def test_import_form_rejects_traversal_scan_name(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    _workbook(tmp_path, _rows(), name="x.xlsx")
    scanned = _ok(_scan(http, tmp_path))
    response = http.post(
        f"{API}/import-form",
        data={
            "scanDirId": scanned["dirId"],
            "scanName": "../x.xlsx",
            "scanToken": scanned["selected"]["token"] if scanned["selected"] else "x",
            "dataDate": "2026-11-06",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code in (409, 422)
    assert response.get_json()["error"]["type"] in {"E_DIR_NOT_ALLOWED", "E_SCAN_STALE"}


def test_scan_dir_cache_is_bounded(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    for index in range(backend._SCAN_DIRS_LIMIT + 6):
        folder = tmp_path / f"d{index:03d}"
        folder.mkdir()
        _workbook(folder, _rows(), name="x.xlsx")
        _ok(_scan(http, folder))
    assert len(backend._SCAN_DIRS) <= backend._SCAN_DIRS_LIMIT


def test_eml_payload_carries_manual_mode() -> None:
    """服务端拒绝必须真的被触发：页面请求要带 mode，不能只靠按钮 disabled。"""
    source = (REPO_ROOT / "plugins" / "sign_daily" / "static" / "report.js").read_text(encoding="utf-8")
    assert 'downloadEml(api.url("eml"), { ...requestBody(), mode: result.mode' in source


# ── 子智能体审计后补的断言 ─────────────────────────────────────────


def test_import_meta_uses_uploaded_filename(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    path = _workbook(tmp_path, _rows(), name="数模审核流程-20261106.xlsx")
    report = _ok(_upload(http, path, dataDate="2026-11-06", projects='["F610M"]'))
    assert report["importMeta"]["sourceName"] == "数模审核流程-20261106.xlsx"


def test_manual_body_carries_source_banner_and_no_fake_time(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    report = _ok(_upload(http, _workbook(tmp_path, _rows()), dataDate="2026-11-06", projects='["F610M"]'))
    assert "手工导入" in report["html"] and "用户确认" in report["html"]
    assert "手工导入" in report["text"]
    assert "00:00" not in report["html"] and "00:00" not in report["text"]
    assert report["snapshotAt"] is None  # 不伪造抓取时间


def test_readonly_store_refuses_config_write() -> None:
    importer = _importer()

    class FakeStore:
        def config(self):
            return {"form": {"projects": []}}

        def save_config(self, patch):  # pragma: no cover - 不应被调用
            raise AssertionError("manual 路径不得写配置")

    store = importer.ReadOnlyStore(FakeStore())
    assert store.config()["form"] == {"projects": []}
    with pytest.raises(RuntimeError):
        store.save_config({"form": {}})


def test_scan_refuses_hidden_newest(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    visible = _workbook(tmp_path, _rows(), name="visible.xlsx")
    hidden = _workbook(tmp_path, _rows(), name=".hidden.xlsx")
    _aging(visible, 3600)
    _aging(hidden, 60)
    data = _ok(_scan(http, tmp_path))
    assert data["selected"] is None
    assert data["reason"] == "E_NEWEST_HIDDEN"


def test_scan_token_binds_content_digest(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    target = _workbook(tmp_path, _rows(), name="scan.xlsx")
    scanned = _ok(_scan(http, tmp_path))
    signature = os.stat(target)
    original = target.read_bytes()
    # 同长度覆盖写：内容变了、size 不变，再把 mtime 复原 → 只有内容摘要能发现
    target.write_bytes(bytes(len(original)))
    os.utime(target, (signature.st_atime, signature.st_mtime))
    response = http.post(
        f"{API}/import-form",
        data={
            "scanDirId": scanned["dirId"],
            "scanName": scanned["selected"]["name"],
            "scanToken": scanned["selected"]["token"],
            "dataDate": "2026-11-06",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "E_SCAN_STALE"


def test_import_scan_accepts_multipart_empty_body(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """页面用的是空 FormData 调 import-scan，契约必须支持这种形态。"""
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    _workbook(tmp_path, _rows(), name="x.xlsx")
    response = http.post(f"{API}/import-scan", data=b"", content_type="multipart/form-data")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

# ── 2026-11-11 终端加密容器：code/文案/diagnostic 白名单 ────────────────

from services.xlsx_preview import ENCRYPTED_CONTAINER_SIGNATURES  # noqa: E402
from services.xlsx_preview import SNIFF_BYTES as _SNIFF_BYTES  # noqa: E402

_CONTAINER_HEAD = ENCRYPTED_CONTAINER_SIGNATURES[0]
_ENCRYPTED_TEXT = "文件受公司终端加密保护，本功能读不到内容，文件本身没有损坏。请改用「一键生成」。"
_DAMAGED_TEXT = "文件无法按 xlsx 打开，可能下载不完整、已损坏或受加密。请重新导出，或改用「一键生成」。"
_SCHEMA_TEXT = "文件可读，但表头与官方 47 列模板不一致。请确认导出的是官方签署明细且未增删改列。"
_DIAGNOSTIC_KEYS = {"reason", "sizeBucket", "colIndex"}


def _container_sample(path: Path) -> Path:
    """合成容器样本：16 字节魔数 + 其余头部 + 正文；不做任何解密。"""
    path.write_bytes(_CONTAINER_HEAD + bytes(1024 - _SNIFF_BYTES) + b"PK\x03\x04 not really")
    return path


def test_import_form_reports_terminal_encryption(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """页面拿到的是「受终端加密」而不是「文件损坏」，且诊断只含白名单键、不含十六进制。"""
    _, http, db, _ = client
    before = _snapshot_counts(db)
    response = _upload(http, _container_sample(tmp_path / "encrypted.xlsx"), dataDate="2026-11-06")

    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["type"] == "E_ENCRYPTED_WORKBOOK"
    assert error["message"] == _ENCRYPTED_TEXT
    assert set(error["diagnostic"]) <= _DIAGNOSTIC_KEYS
    assert error["diagnostic"]["reason"] == "encrypted_container"
    assert "sizeBucket" in error["diagnostic"]
    body = response.get_data(as_text=True)
    assert _CONTAINER_HEAD.hex() not in body.lower()
    assert "17da5fa0" not in body.lower()
    assert _snapshot_counts(db) == before  # 失败路径同样零写库


def test_import_form_keeps_reason_for_unreadable_binary(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(bytes(range(64)) * 4)
    response = _upload(http, junk, dataDate="2026-11-06")

    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["type"] == "E_WORKBOOK_INVALID"
    assert error["message"] == _DAMAGED_TEXT
    assert error["diagnostic"]["reason"] == "unknown_binary"


def test_import_form_header_drift_reports_column_index(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    response = _upload(http, _workbook(tmp_path, _rows(), drift=True), dataDate="2026-11-06")

    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["type"] == "E_HEADER_MISMATCH"
    assert error["message"] == _SCHEMA_TEXT
    assert error["diagnostic"] == {"reason": "schema_mismatch", "colIndex": 2}


def test_import_scan_stops_on_encrypted_newest(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """最新那份是加密容器时停在它上面（不退回更旧的明文文件），并给出加密码。"""
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))
    _, http, _, _ = client
    good = _workbook(tmp_path, _rows(), name="good.xlsx")
    newest = _container_sample(tmp_path / "newest.xlsx")
    _aging(good, 3600)
    _aging(newest, 60)

    data = _ok(_scan(http, tmp_path))

    assert data["selected"] is None
    assert data["reason"] == "E_ENCRYPTED_WORKBOOK"
    assert data["entries"][0]["reason"] == "E_ENCRYPTED_WORKBOOK"


def test_scan_reason_texts_cover_encrypted_code() -> None:
    """前端/CLI 的原因码表都要有这个新码，否则用户只看到裸码。"""
    repo = Path(__file__).resolve().parent.parent
    js = (repo / "plugins" / "sign_daily" / "static" / "report.js").read_text(encoding="utf-8")
    assert "E_ENCRYPTED_WORKBOOK:" in js
    assert "REASON_NOTES" in js


# ── 2026-11-16 本地导入日变化：只写自有的手工基线表 ─────────────────────


def _manual_counts(db) -> dict[str, int]:
    with db.get_connection() as conn:
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in names if fnmatch.fnmatch(name, "*manual_baseline*")
        }


def _signed_s2(rows):  # type: ignore[no-untyped-def]
    """第二天：S2 审批完成（待签 1 → 0，新签完）。"""
    for row in rows:
        if row["流水单号"] == "S2":
            row.update({"状态": "已完成", "已签人数": 2, "未签人数": 0, "签署率": "100%", "首席/总监": "总监辛"})
    return rows


def test_manual_baseline_tables_are_outside_shared_patterns(client) -> None:  # type: ignore[no-untyped-def]
    _, _, db, _ = client
    tables = _manual_counts(db)
    assert sorted(tables) == ["p_sign_daily_manual_baseline_file", "p_sign_daily_manual_baseline_meta",
                              "p_sign_daily_manual_baseline_rows"]
    assert not set(tables) & set(_snapshot_counts(db))  # 共享表断言照旧有效


def test_import_form_next_day_shows_daily_progress(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    shared = _snapshot_counts(db)
    first = _ok(_upload(http, _workbook(tmp_path, _rows(), name="d1.xlsx"), dataDate="2026-11-06",
                        projects='["F610M"]'))
    assert first["delta"] is None and first["progress"] is None
    assert first["importMeta"]["baseline"] is None and first["importMeta"]["baselineSaved"] is True
    assert "首次导入或无可用基线，不显示日变化" in first["importMeta"]["banner"]
    assert "不计算日变化" not in first["html"]
    assert _manual_counts(db)["p_sign_daily_manual_baseline_meta"] == 1

    second = _ok(_upload(http, _workbook(tmp_path, _signed_s2(_rows()), name="d2.xlsx"), dataDate="2026-11-07",
                         projects='["F610M"]'))
    assert second["baseDate"] == "2026-11-06" and second["stale"] is False
    assert second["delta"]["total"]["complete"] == 1
    assert "3D单完成2(+1)/4份" in second["summaryLines"][2]
    meta = second["importMeta"]
    assert meta["baseline"]["date"] == "2026-11-06" and meta["baseline"]["sourceName"] == "d1.xlsx"
    assert len(meta["baseline"]["sha256"]) == 12 and meta["baselineSaved"] is True
    assert "日变化基线（自动）：2026-11-06 的手工导入「d1.xlsx」" in meta["banner"]
    assert meta["baseline"]["mode"] == "auto" and meta["baselineReason"] == ""
    assert "同一套 TDC 筛选条件" in meta["note"]
    progress = second["progress"]
    assert progress["totals"]["newlyCompleted"] == ["S2"]
    assert progress["totals"]["remainingChange"] == -1
    assert {f["serial"]: f["kind"] for f in progress["flows"]}["S2"] == "completed"
    # 每日进展紧跟来源声明，只列有变化的单
    assert second["html"].index("每日进展（较 11-06）") < second["html"].index("各位领导")
    assert second["text"].splitlines()[1] == "每日进展（较 11-06）"
    assert second["text"].splitlines()[2].startswith("较 11-06：总签署率（已签/应签）")
    assert "待签人次减少 1；新签完 1 份；还有 2 份未签完" in second["text"]
    assert "S1" not in second["text"].split("各位领导")[0]
    assert second["snapshotSaved"] is False  # 对外仍只指 TDC 共享快照
    assert _snapshot_counts(db) == shared  # 共享表、配置、长周期结论一概不动
    assert _manual_counts(db)["p_sign_daily_manual_baseline_meta"] == 2


def test_import_form_older_date_after_newer_is_stale(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="new.xlsx"), dataDate="2026-11-07", projects='["F610M"]'))
    before = _manual_counts(db)
    old = _ok(_upload(http, _workbook(tmp_path, _rows(), name="old.xlsx"), dataDate="2026-11-06",
                      projects='["F610M"]'))
    assert old["stale"] is True and old["delta"] is None and old["progress"] is None
    assert old["importMeta"]["baselineSaved"] is False and old["importMeta"]["baseline"] is None
    assert "已有更晚日期的手工导入，本次按旧数据处理：不留基线、不显示日变化" in old["importMeta"]["banner"]
    assert _manual_counts(db) == before


def test_import_form_keep_baseline_off_reads_but_does_not_write(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="d1.xlsx"), dataDate="2026-11-06", projects='["F610M"]'))
    before = _manual_counts(db)
    second = _ok(_upload(http, _workbook(tmp_path, _signed_s2(_rows()), name="d2.xlsx"), dataDate="2026-11-07",
                         projects='["F610M"]', keepBaseline="0"))
    assert second["progress"] is not None and second["importMeta"]["baseline"]["date"] == "2026-11-06"
    assert second["importMeta"]["baselineSaved"] is False
    assert _manual_counts(db) == before
    bad = _upload(http, _workbook(tmp_path, _rows(), name="d3.xlsx"), dataDate="2026-11-08", keepBaseline="maybe")
    assert bad.status_code == 400


def test_import_form_failure_writes_no_baseline(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    before = _manual_counts(db)
    assert _upload(http, _workbook(tmp_path, _rows(), drift=True), dataDate="2026-11-06").status_code == 422
    assert _upload(http, _workbook(tmp_path, _rows(), name="x.xlsx"), dataDate="2026-11-06",
                   projects='["NOPE"]').status_code == 404
    assert _manual_counts(db) == before


def test_import_form_rejects_future_data_date(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """日期手填：填成未来会让保留期清理删掉旧基线、并把之后的正常导入都判成旧数据，所以直接拒绝。"""
    _, http, db, _ = client
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_import_today", lambda: date(2026, 11, 6))
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="a.xlsx"), dataDate="2026-11-06"))  # 当天可以
    before = _manual_counts(db)
    response = _upload(http, _workbook(tmp_path, _rows(), name="b.xlsx"), dataDate="2027-11-06")
    assert response.status_code == 400 and "晚于今天" in response.get_json()["error"]["message"]
    assert _manual_counts(db) == before


def test_import_form_same_date_overwrites_baseline(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="a.xlsx"), dataDate="2026-11-06", projects='["F610M"]'))
    again = _ok(_upload(http, _workbook(tmp_path, _rows()[:2], name="b.xlsx"), dataDate="2026-11-06",
                        projects='["F610M"]'))
    assert again["stale"] is False and again["importMeta"]["baselineSaved"] is True
    with db.get_connection() as conn:
        meta = conn.execute("SELECT source_name, row_count FROM p_sign_daily_manual_baseline_meta").fetchall()
        rows = conn.execute("SELECT COUNT(*) FROM p_sign_daily_manual_baseline_rows").fetchone()[0]
    assert [(m["source_name"], m["row_count"]) for m in meta] == [("b.xlsx", 2)] and rows == 2


def test_report_digest_ignores_baseline(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同一份数据、同一数据日期：有没有基线，正文指纹都相同（日变化不进指纹）。"""
    _, http, _, _ = client
    today = _workbook(tmp_path, _signed_s2(_rows()), name="today.xlsx")
    alone = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0"))
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="base.xlsx"), dataDate="2026-11-06", projects='["F610M"]'))
    compared = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]'))
    assert alone["progress"] is None and compared["progress"] is not None
    assert compared["text"] != alone["text"]
    assert compared["importMeta"]["reportDigest"] == alone["importMeta"]["reportDigest"]


_F610M_ROWS = sum(1 for row in _rows() if row["项目/车型"] == "F610M")  # 基线只存所选项目的行


def _three_days(http, tmp_path):  # type: ignore[no-untyped-def]
    """11-01、11-05、11-06 各导入一次（S2 在 11-06 才签完）。"""
    for day, rows in (("2026-11-01", _rows()), ("2026-11-05", _rows()), ("2026-11-06", _signed_s2(_rows()))):
        _ok(_upload(http, _workbook(tmp_path, rows, name=f"{day}.xlsx"), dataDate=day, projects='["F610M"]'))


def test_explicit_baseline_beats_auto_and_pinned(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    shared = _snapshot_counts(db)
    _three_days(http, tmp_path)
    today = _workbook(tmp_path, _signed_s2(_rows()), name="today.xlsx")
    auto = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0"))
    assert auto["baseDate"] == "2026-11-06" and auto["importMeta"]["baseline"]["mode"] == "auto"
    explicit = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0",
                           baselineDate="2026-11-01"))
    assert explicit["baseDate"] == "2026-11-01" and explicit["importMeta"]["baseline"]["mode"] == "explicit"
    assert "括号内为较 11-01 的变化" in explicit["summaryLines"]
    assert "日变化基线（指定）：2026-11-01" in explicit["importMeta"]["banner"]
    assert explicit["progress"]["totals"]["newlyCompleted"] == ["S2"]
    _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-11-05"}))
    pinned = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0"))
    assert pinned["baseDate"] == "2026-11-05" and pinned["importMeta"]["baseline"]["mode"] == "pinned"
    assert "日变化基线（固定）" in pinned["importMeta"]["banner"]
    both = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0",
                       baselineDate="2026-11-06"))
    assert both["baseDate"] == "2026-11-06" and both["importMeta"]["baseline"]["mode"] == "explicit"
    assert _snapshot_counts(db) == shared


def test_explicit_or_pinned_baseline_ignores_max_gap(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="old.xlsx"), dataDate="2026-09-01", projects='["F610M"]'))
    today = _workbook(tmp_path, _signed_s2(_rows()), name="today.xlsx")
    auto = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0"))
    assert auto["progress"] is None  # 自动挑选受最长间隔限制
    explicit = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0",
                           baselineDate="2026-09-01"))
    assert explicit["baseDate"] == "2026-09-01" and explicit["progress"] is not None
    _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-09-01"}))
    pinned = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0"))
    assert pinned["baseDate"] == "2026-09-01" and pinned["importMeta"]["baseline"]["mode"] == "pinned"


def test_pinned_baseline_survives_retention(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="a.xlsx"), dataDate="2026-06-01", projects='["F610M"]'))
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="b.xlsx"), dataDate="2026-06-02", projects='["F610M"]'))
    _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-06-01"}))
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="c.xlsx"), dataDate="2026-11-07", projects='["F610M"]'))
    listed = _ok(http.get(f"{API}/manual-baselines"))
    assert [item["date"] for item in listed["items"]] == ["2026-11-07", "2026-06-01"]  # 06-02 过期被清，06-01 固定保留
    assert listed["pinned"] == "2026-06-01" and listed["items"][1]["sourceName"] == "a.xlsx"
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM p_sign_daily_manual_baseline_rows WHERE data_date = '2026-06-01'"
                            ).fetchone()[0] == _F610M_ROWS


def test_unusable_requested_baseline_is_reported_not_replaced(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    _three_days(http, tmp_path)
    today = _workbook(tmp_path, _signed_s2(_rows()), name="today.xlsx")
    for requested in ("2026-11-07", "2026-11-08", "2026-11-03"):  # 不早于本次 / 更晚 / 没存过
        report = _ok(_upload(http, today, dataDate="2026-11-07", projects='["F610M"]', keepBaseline="0",
                             baselineDate=requested))
        assert report["progress"] is None and report["delta"] is None, requested
        meta = report["importMeta"]
        assert meta["baseline"] is None
        assert meta["baselineReason"] == f"指定的基线 {requested} 不早于本次数据日期或不含所选项目，未显示日变化"
        assert meta["baselineReason"] in meta["banner"]
    for bad in ("20261101", "2026-11-1", "2026-13-01"):
        response = _upload(http, today, dataDate="2026-11-07", baselineDate=bad)
        assert response.status_code == 400, bad
    _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-11-06"}))
    same_day = _ok(_upload(http, today, dataDate="2026-11-06", projects='["F610M"]', keepBaseline="0"))
    assert same_day["progress"] is None
    assert same_day["importMeta"]["baselineReason"].startswith("固定的基线 2026-11-06")


def test_manual_baseline_routes(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    app, http, db, _ = client
    _three_days(http, tmp_path)
    listed = _ok(http.get(f"{API}/manual-baselines"))
    assert [i["date"] for i in listed["items"]] == ["2026-11-06", "2026-11-05", "2026-11-01"]
    assert listed["pinned"] is None and listed["items"][0]["projects"] == ["F610M"]
    assert listed["items"][0]["rowCount"] == _F610M_ROWS and len(listed["items"][0]["sha256"]) == 12
    assert _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-11-05"}))["pinned"] == "2026-11-05"
    assert _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-11-01"}))["pinned"] == "2026-11-01"
    assert sum(i["pinned"] for i in _ok(http.get(f"{API}/manual-baselines"))["items"]) == 1
    assert _ok(http.post(f"{API}/manual-baselines/unpin", json={}))["pinned"] is None
    after = _ok(http.post(f"{API}/manual-baselines/delete", json={"date": "2026-11-05"}))
    assert [i["date"] for i in after["items"]] == ["2026-11-06", "2026-11-01"]
    for path in ("pin", "delete"):
        assert http.post(f"{API}/manual-baselines/{path}", json={"date": "2026-10-30"}).status_code == 404
        assert http.post(f"{API}/manual-baselines/{path}", json={"date": "11-05"}).status_code == 400
        assert http.post(f"{API}/manual-baselines/{path}", json=["2026-11-06"]).status_code == 400
    # 写路由走 local_guard：非本机来源被拒，基线不变
    before = _manual_counts(db)
    remote = http.post(f"{API}/manual-baselines/delete", json={"date": "2026-11-06"},
                       environ_base={"REMOTE_ADDR": "10.0.0.9"})
    assert remote.status_code in (401, 403)
    assert _manual_counts(db) == before


def test_chart_colors_config(client) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    assert _ok(http.get(f"{API}/state"))["chartColors"] == backend.DEFAULT_CHART_COLORS
    _ok(http.post(f"{API}/config", json={"chartColors": {"sections": {"special": "#ABCDEF"}}}))
    colors = _ok(http.get(f"{API}/state"))["chartColors"]
    assert colors["sections"] == {"bar": "#8f959e", "special": "#abcdef"}
    assert colors["external"] == backend.DEFAULT_CHART_COLORS["external"]
    _ok(http.post(f"{API}/config", json={"chartColors": {"external": {"bar": "#112233"}}}))
    colors = _ok(http.get(f"{API}/state"))["chartColors"]
    assert colors["sections"]["special"] == "#abcdef" and colors["external"]["bar"] == "#112233"
    for bad in ({"sections": {"bar": "red"}}, {"sections": {"bar": "#12345"}}, {"pie": {"bar": "#123456"}},
                {"sections": {"line": "#123456"}}, {"sections": "#123456"}, ["#123456"]):
        assert http.post(f"{API}/config", json={"chartColors": bad}).status_code == 400, bad


def test_chart_colors_survive_corrupt_storage(client) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    with db.get_connection() as conn:
        conn.execute("INSERT INTO p_sign_daily_config (key, value_json) VALUES (?, ?)",
                     ("chartColors", json.dumps({"external": {"bar": "nope"}, "sections": 3, "x": {}})))
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    assert _ok(http.get(f"{API}/state"))["chartColors"] == backend.DEFAULT_CHART_COLORS


def test_chart_color_defaults_match_chart_js() -> None:
    import re

    backend = sys.modules.get("vse_plugins.sign_daily.backend")
    if backend is None:
        pytest.skip("plugin backend not loaded")
    source = (REPO_ROOT / "plugins" / "sign_daily" / "static" / "chart.js").read_text(encoding="utf-8")
    source = source.split("export const PALETTES = {", 1)[1].split("};", 1)[0]
    found = {
        key: {"bar": bar, "special": special}
        for key, bar, special in re.findall(r'(\w+): \{ bar: "(#[0-9a-f]{6})", special: "(#[0-9a-f]{6})" \}', source)
    }
    assert found == backend.DEFAULT_CHART_COLORS


# ── 2026-11-16 基线文件：指定一份本地报表为固定基线，对比只读备份 ──────────────


def _backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "plugins" / "sign-daily" / "baseline-backup"


def _backups(tmp_path: Path) -> list[str]:
    directory = _backup_dir(tmp_path)
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def _set_file_by_path(http, path, day="2026-11-01", **extra):  # type: ignore[no-untyped-def]
    return http.post(f"{API}/manual-baseline-file", data={"path": str(path), "dataDate": day, **extra},
                     content_type="multipart/form-data")


def _set_file_by_upload(http, path: Path, day="2026-11-01"):  # type: ignore[no-untyped-def]
    with path.open("rb") as handle:
        return http.post(f"{API}/manual-baseline-file", data={"file": (handle, path.name), "dataDate": day},
                         content_type="multipart/form-data")


def _today_report(http, tmp_path, **form):  # type: ignore[no-untyped-def]
    """11-07 的导入：S2 已签完（基线文件里 S2 未签完 → 每日进展里 S2 新签完）。"""
    today = _workbook(tmp_path, _signed_s2(_rows()), name="today.xlsx")
    fields = {"dataDate": "2026-11-07", "projects": '["F610M"]', "keepBaseline": "0", **form}
    return _ok(_upload(http, today, **fields))


def test_baseline_file_by_path_compares_against_backup(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    shared = _snapshot_counts(db)
    original = _workbook(tmp_path, _rows(), name="base-1101.xlsx")
    data = _ok(_set_file_by_path(http, original))
    view = data["file"]
    assert view["date"] == "2026-11-01" and view["sourceName"] == "base-1101.xlsx"
    assert view["originalPath"] == str(original.resolve()) and view["originalStatus"] == "ok"
    assert view["backupStatus"] == "ok" and len(view["sha256"]) == 12
    assert data["backupDir"] == str(_backup_dir(tmp_path).resolve())
    assert _backups(tmp_path) == [f"baseline-{view['sha256']}.xlsx"]
    assert Path(view["backupPath"]).read_bytes() == original.read_bytes()
    assert _ok(http.get(f"{API}/manual-baseline-file"))["file"] == view
    assert _ok(http.get(f"{API}/manual-baselines"))["file"] == view  # 页面刷新一次就够

    report = _today_report(http, tmp_path)
    assert report["baseDate"] == "2026-11-01" and report["stale"] is False
    assert report["progress"]["totals"]["newlyCompleted"] == ["S2"]
    meta = report["importMeta"]
    assert meta["baseline"]["mode"] == "file" and meta["baseline"]["sourceName"] == "base-1101.xlsx"
    assert meta["baseline"]["originalStatus"] == "ok" and meta["baseline"]["backupStatus"] == "ok"
    assert meta["baseline"]["originalPath"] == str(original.resolve())
    assert meta["baselineFile"]["date"] == "2026-11-01" and meta["baselineReason"] == ""
    assert "日变化基线（文件）：2026-11-01 的基线文件「base-1101.xlsx」" in meta["banner"]
    assert "原文件未变" in meta["banner"]
    assert _snapshot_counts(db) == shared  # 共享 TDC 表一概不动


def test_baseline_file_by_upload_has_unknown_original(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    view = _ok(_set_file_by_upload(http, _workbook(tmp_path, _rows(), name="picked.xlsx")))["file"]
    assert view["originalPath"] is None and view["originalStatus"] == "unknown"
    assert view["backupStatus"] == "ok" and view["sourceName"] == "picked.xlsx"
    report = _today_report(http, tmp_path)
    assert report["progress"]["totals"]["newlyCompleted"] == ["S2"]
    assert report["importMeta"]["baseline"]["originalStatus"] == "unknown"
    assert "原位置未知，对比用的是指定时的备份" in report["importMeta"]["banner"]


def test_baseline_file_original_missing_uses_backup(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    original = _workbook(tmp_path, _rows(), name="base.xlsx")
    _ok(_set_file_by_path(http, original))
    original.rename(tmp_path / "renamed.xlsx")
    assert _ok(http.get(f"{API}/manual-baseline-file"))["file"]["originalStatus"] == "missing"
    report = _today_report(http, tmp_path)
    assert report["progress"]["totals"]["newlyCompleted"] == ["S2"]  # 照样有每日进展
    meta = report["importMeta"]
    assert meta["baseline"]["originalStatus"] == "missing"
    assert "基线文件不存在（已不在指定时的位置），已改用备份继续对比" in meta["banner"]
    assert str(original.resolve()) not in meta["banner"]  # 正文会发给别人：不带本机路径
    assert meta["baseline"]["originalPath"] == str(original.resolve())  # 路径只给页面
    (tmp_path / "renamed.xlsx").unlink()
    again = _today_report(http, tmp_path)
    assert again["progress"] is not None and again["importMeta"]["baseline"]["originalStatus"] == "missing"


def test_baseline_file_original_modified_compares_backup(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    original = _workbook(tmp_path, _rows(), name="base.xlsx")
    _ok(_set_file_by_path(http, original))
    _workbook(tmp_path, _signed_s2(_rows()), name="base.xlsx")  # 原文件被改成「S2 已签完」
    report = _today_report(http, tmp_path)
    meta = report["importMeta"]
    assert meta["baseline"]["originalStatus"] == "changed"
    assert "基线文件在指定后被修改过，对比用的是指定时的备份" in meta["banner"]
    # 若读的是原文件，S2 就不会是「新签完」：证明对比用的是备份
    assert report["progress"]["totals"]["newlyCompleted"] == ["S2"]
    assert report["delta"]["total"]["complete"] == 1


def test_baseline_file_backup_gone_shows_no_progress(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    # 有一份可以自动挑选的更早导入：证明备份没了也不退回自动
    _ok(_upload(http, _workbook(tmp_path, _rows(), name="d6.xlsx"), dataDate="2026-11-06", projects='["F610M"]'))
    view = _ok(_set_file_by_path(http, _workbook(tmp_path, _rows(), name="base.xlsx")))["file"]
    Path(view["backupPath"]).unlink()
    assert _ok(http.get(f"{API}/manual-baseline-file"))["file"]["backupStatus"] == "missing"
    report = _today_report(http, tmp_path)
    assert report["progress"] is None and report["delta"] is None and report["baseDate"] is None
    meta = report["importMeta"]
    assert meta["baseline"] is None
    assert meta["baselineReason"] == "基线文件和备份都不存在（或无法识别），请重新指定"
    assert meta["baselineReason"] in meta["banner"]
    assert meta["baselineFile"]["backupStatus"] == "missing"
    # 备份被换成认不出的内容（摘要对不上）同样不比
    _ok(_set_file_by_path(http, tmp_path / "base.xlsx"))
    Path(view["backupPath"]).write_bytes(b"garbage")
    assert _today_report(http, tmp_path)["progress"] is None


@pytest.mark.parametrize("case", ["header", "missing", "directory", "suffix", "oversize", "future", "relative",
                                  "nodate", "both", "encrypted"])
def test_baseline_file_rejections_write_nothing(client, tmp_path, monkeypatch, case) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_import_today", lambda: date(2026, 11, 16))
    good = _workbook(tmp_path, _rows(), name="good.xlsx")
    before = _manual_counts(db)
    if case == "header":
        response = _set_file_by_path(http, _workbook(tmp_path, _rows(), drift=True, name="drift.xlsx"))
        assert response.get_json()["error"]["type"] == "E_HEADER_MISMATCH"
    elif case == "missing":
        response = _set_file_by_path(http, tmp_path / "nope.xlsx")
        assert "找不到文件" in response.get_json()["error"]["message"]
    elif case == "directory":
        folder = tmp_path / "folder.xlsx"
        folder.mkdir()
        response = _set_file_by_path(http, folder)
        assert "文件夹" in response.get_json()["error"]["message"]
    elif case == "suffix":
        other = tmp_path / "base.csv"
        other.write_bytes(good.read_bytes())
        response = _set_file_by_path(http, other)
        assert response.get_json()["error"]["type"] == "E_BAD_SUFFIX"
    elif case == "oversize":
        monkeypatch.setattr(backend, "_FORM_FILE_LIMIT", 100)
        response = _set_file_by_path(http, good)
        assert response.get_json()["error"]["type"] == "E_FILE_TOO_LARGE"
        assert _set_file_by_upload(http, good).status_code == 400
    elif case == "future":
        response = _set_file_by_path(http, good, day="2026-11-17")
        assert "晚于今天" in response.get_json()["error"]["message"]
    elif case == "relative":
        response = _set_file_by_path(http, "good.xlsx")
        assert response.get_json()["error"]["type"] == "E_PATH_NOT_ABSOLUTE"
    elif case == "nodate":
        response = _set_file_by_path(http, good, day="")
        assert _set_file_by_path(http, good, day="2026-11-1").status_code == 400
    elif case == "both":
        with good.open("rb") as handle:
            response = http.post(f"{API}/manual-baseline-file",
                                 data={"file": (handle, "good.xlsx"), "path": str(good), "dataDate": "2026-11-01"},
                                 content_type="multipart/form-data")
    else:
        response = _set_file_by_path(http, _container_sample(tmp_path / "locked.xlsx"))
        error = response.get_json()["error"]
        assert error["type"] == "E_ENCRYPTED_WORKBOOK" and "Unicode 文本(*.txt)" in error["message"]
        assert set(error["diagnostic"]) <= _DIAGNOSTIC_KEYS
        assert _CONTAINER_HEAD.hex() not in response.get_data(as_text=True).lower()
    assert response.status_code in (400, 422), case
    assert _manual_counts(db) == before
    assert _ok(http.get(f"{API}/manual-baseline-file"))["file"] is None
    assert _backups(tmp_path) == []


def test_baseline_file_replace_and_clear(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    first = _ok(_set_file_by_path(http, _workbook(tmp_path, _rows(), name="a.xlsx")))["file"]
    assert _ok(_set_file_by_path(http, tmp_path / "a.xlsx"))["file"]["sha256"] == first["sha256"]
    assert _backups(tmp_path) == [f"baseline-{first['sha256']}.xlsx"]  # 同一份重设：备份还在
    second = _ok(_set_file_by_upload(http, _workbook(tmp_path, _rows()[:3], name="b.xlsx"), day="2026-11-02"))["file"]
    assert second["sha256"] != first["sha256"]
    assert _backups(tmp_path) == [f"baseline-{second['sha256']}.xlsx"]  # 旧备份已删，只留一份
    cleared = _ok(http.post(f"{API}/manual-baseline-file/clear", json={}))
    assert cleared["file"] is None and cleared["cleared"] is True
    assert _backups(tmp_path) == []
    assert _ok(http.post(f"{API}/manual-baseline-file/clear", json={}))["cleared"] is False


def test_baseline_file_and_pin_are_mutually_exclusive(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    _three_days(http, tmp_path)
    _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-11-05"}))
    _ok(_set_file_by_path(http, _workbook(tmp_path, _rows(), name="base.xlsx")))
    listed = _ok(http.get(f"{API}/manual-baselines"))
    assert listed["pinned"] is None and listed["file"]["sourceName"] == "base.xlsx"  # 设文件 → 取消固定
    assert http.post(f"{API}/manual-baselines/pin", json={"date": "2026-10-30"}).status_code == 404
    assert _ok(http.get(f"{API}/manual-baseline-file"))["file"] is not None  # 固定失败不动基线文件
    pinned = _ok(http.post(f"{API}/manual-baselines/pin", json={"date": "2026-11-05"}))
    assert pinned["pinned"] == "2026-11-05" and pinned["file"] is None  # 固定 → 取消基线文件
    assert _backups(tmp_path) == []
    report = _today_report(http, tmp_path)
    assert report["importMeta"]["baseline"]["mode"] == "pinned"


def test_explicit_baseline_beats_baseline_file(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    _three_days(http, tmp_path)
    _ok(_set_file_by_path(http, _workbook(tmp_path, _rows(), name="base.xlsx"), day="2026-10-20"))
    by_file = _today_report(http, tmp_path)
    assert by_file["baseDate"] == "2026-10-20" and by_file["importMeta"]["baseline"]["mode"] == "file"
    explicit = _today_report(http, tmp_path, baselineDate="2026-11-05")
    assert explicit["baseDate"] == "2026-11-05" and explicit["importMeta"]["baseline"]["mode"] == "explicit"
    assert explicit["importMeta"]["baselineFile"] is None


def test_baseline_file_not_earlier_or_missing_project(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    _ok(_set_file_by_path(http, _workbook(tmp_path, _rows(), name="same.xlsx"), day="2026-11-07"))
    same_day = _today_report(http, tmp_path)
    assert same_day["progress"] is None and same_day["stale"] is False
    reason = same_day["importMeta"]["baselineReason"]
    assert reason == "基线文件「same.xlsx」（2026-11-07）不早于本次数据日期或不含所选项目，未显示日变化"
    e50_only = [row for row in _rows() if row["项目/车型"] == "E50"]
    _ok(_set_file_by_path(http, _workbook(tmp_path, e50_only, name="e50.xlsx")))
    missing = _today_report(http, tmp_path)
    assert missing["progress"] is None and missing["delta"] is None
    assert missing["importMeta"]["baselineReason"].startswith("基线文件「e50.xlsx」（2026-11-01）")
    # 当天的导入照常留作基线（keepBaseline 打开时）：委托给手工基线库
    kept = _today_report(http, tmp_path, keepBaseline="1")
    assert kept["importMeta"]["baselineSaved"] is True
    assert "2026-11-07" in [i["date"] for i in _ok(http.get(f"{API}/manual-baselines"))["items"]]


def test_baseline_file_report_digest_unchanged(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    alone = _today_report(http, tmp_path)
    _ok(_set_file_by_path(http, _workbook(tmp_path, _rows(), name="base.xlsx")))
    compared = _today_report(http, tmp_path)
    assert compared["progress"] is not None and alone["progress"] is None
    assert compared["importMeta"]["reportDigest"] == alone["importMeta"]["reportDigest"]


def test_baseline_file_name_is_escaped_and_path_stays_out_of_body(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """文件名进正文要转义；本机路径不进正文（正文会发给别人），只在 importMeta 里给页面。"""
    _, http, _, _ = client
    folder = tmp_path / "secret-folder"
    folder.mkdir()
    original = _workbook(folder, _rows(), name="<b>x&y.xlsx")
    _ok(_set_file_by_path(http, original))
    original.unlink()
    report = _today_report(http, tmp_path)
    assert "<b>x&y" not in report["html"] and "&lt;b&gt;x&amp;y" in report["html"]
    assert "<b>x&y" in report["text"]  # 纯文本照原样
    assert "secret-folder" not in report["html"] and "secret-folder" not in report["text"]
    assert "secret-folder" in report["importMeta"]["baseline"]["originalPath"]


def test_baseline_file_routes_are_local_only(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    original = _workbook(tmp_path, _rows(), name="base.xlsx")
    remote = {"REMOTE_ADDR": "10.0.0.9"}
    assert http.get(f"{API}/manual-baseline-file", environ_base=remote).status_code in (401, 403)
    response = http.post(f"{API}/manual-baseline-file", data={"path": str(original), "dataDate": "2026-11-01"},
                         content_type="multipart/form-data", environ_base=remote)
    assert response.status_code in (401, 403) and _backups(tmp_path) == []
    _ok(_set_file_by_path(http, original))
    assert http.post(f"{API}/manual-baseline-file/clear", json={}, environ_base=remote).status_code in (401, 403)
    assert _backups(tmp_path) != []
    # 列表 GET 本身不过插件的 local_guard（宿主对非本机来源整体拒绝）；即便放行，视图里也不带本机路径。
    listed = http.get(f"{API}/manual-baselines", environ_base=remote)
    assert listed.status_code in (401, 403) and str(tmp_path) not in listed.get_data(as_text=True)


def test_backup_name_validator_blocks_traversal(client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mb = sys.modules["vse_plugins.sign_daily.manual_baseline"]
    assert mb.valid_backup_name("baseline-0123456789ab.xlsx")
    assert mb.valid_backup_name("baseline-0123456789ab.txt")
    for bad in ("../baseline-0123456789ab.xlsx", "baseline-0123456789ab.xlsx/..", "a/baseline-0123456789ab.xlsx",
                "..\\baseline-0123456789ab.xlsx", "baseline-0123456789AB.xlsx", "baseline-0123456789ab.csv",
                "baseline-0123456789a.xlsx", "", None, "/etc/passwd", "baseline-0123456789ab.xlsx\x00",
                "baseline-0123456789ab.xlsx\n"):
        assert not mb.valid_backup_name(bad), bad
        assert mb.backup_path(tmp_path, bad) is None
        assert mb.remove_backup(tmp_path, bad) is False
    victim = tmp_path / "keep.xlsx"
    victim.write_bytes(b"x")
    assert mb.remove_backup(tmp_path, "keep.xlsx") is False and victim.exists()
    with pytest.raises(ValueError):
        mb.backup_name_for("../../x", ".xlsx")
    assert mb.backup_name_for("ABCDEF0123456789", ".XLSX") == "baseline-abcdef012345.xlsx"


def test_encrypted_baseline_file_is_read_from_backup_via_excel(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """加密 xlsx：代读开着时由 Excel 读插件数据目录里的备份（不是原文件）；代读失败不留备份、不记录。"""
    _, http, db, _ = client
    xp = sys.modules["vse_plugins.sign_daily.excel_proxy"]
    importer = _importer()
    plain = importer.source_from_file(_workbook(tmp_path, _rows(), name="plain.xlsx"), date(2026, 11, 1))
    seen: list[Path] = []
    monkeypatch.setattr(xp, "ready", lambda config: True)

    def fake_excel(path, day):  # type: ignore[no-untyped-def]
        seen.append(Path(path))
        return importer.S.SourceData(records=plain.records, snapshot_at=None, data_date=day,
                                     coverage={"kind": "all"})

    monkeypatch.setattr(importer, "source_from_excel", fake_excel)
    locked = _container_sample(tmp_path / "locked.xlsx")
    view = _ok(_set_file_by_path(http, locked))["file"]
    assert seen and seen[-1].parent == _backup_dir(tmp_path).resolve() and seen[-1] != locked.resolve()
    assert view["backupStatus"] == "ok"
    report = _today_report(http, tmp_path)
    assert report["progress"]["totals"]["newlyCompleted"] == ["S2"]
    assert seen[-1].name == Path(view["backupPath"]).name

    _ok(http.post(f"{API}/manual-baseline-file/clear", json={}))
    before = _manual_counts(db)

    def failing(path, day):  # type: ignore[no-untyped-def]
        raise importer.ManualImportError("E_ENCRYPTED_WORKBOOK", importer.ENCRYPTED_TEXT,
                                         diagnostic={"reason": "excel_unavailable"})

    monkeypatch.setattr(importer, "source_from_excel", failing)
    response = _set_file_by_path(http, locked)
    assert response.status_code == 422 and response.get_json()["error"]["diagnostic"] == {"reason": "excel_unavailable"}
    assert _backups(tmp_path) == [] and _manual_counts(db) == before
