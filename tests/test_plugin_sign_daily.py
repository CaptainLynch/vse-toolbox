# -*- coding: utf-8 -*-
"""sign-daily v2.0 接口：快照与基线、长周期复核、范围（A9）和后台抓取。"""

from __future__ import annotations

import base64
import email
import sys
import time
from email import policy
from datetime import date, timezone
from pathlib import Path

import pytest

import web.app as web_app
from services.deliverable_form_analysis import build_form_snapshot, form_definition

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
    assert report["summaryLines"][-1] == "首次生成，无日变化"  # 验收 14
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
    assert second["summaryLines"][-1] != "首次生成，无日变化"

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
    assert "总监辛" in report["recipients"]["missing"]  # 有欠账但通讯录里没有邮箱，导出前列出
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
    assert bad.status_code == 400 and "另存为 CSV" in bad.get_json()["error"]["message"]
