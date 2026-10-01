from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

import web.app as web_app
from services.tdc_auth import TDCAuthError, TDCLoginResult
from services.tdc_crawler import TDCCrawlerError, TDCExportResult, TDCPagedResult


ALLOWED_IMPLEMENTATION_STATUSES = {
    "已完整实现",
    "后端已实现、前端缺失",
    "部分实现",
    "仅占位",
    "仅文档规划",
    "未发现实现证据",
}
ALLOWED_AVAILABILITY = {"available", "cli_only", "partial", "disabled"}


class FakeTDCWebClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None
    export_outside = False

    def __init__(
        self,
        base_url,
        session=None,
        headers=None,
        timeout=30.0,
        diagnostic_hook=None,
        output_dir=None,
    ):  # type: ignore[no-untyped-def]
        self.base_url = base_url
        self.session = session
        self.headers = headers or {}
        self.timeout = timeout
        self.diagnostic_hook = diagnostic_hook
        self.output_dir = output_dir
        self.__class__.calls.append(
            {
                "method": "init",
                "base_url": base_url,
                "session": session,
                "headers": self.headers,
                "timeout": timeout,
                "output_dir": output_dir,
            }
        )

    def _before(self, method: str, **kwargs):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append({"method": method, **kwargs})

    def _query_result(self, report_type: str, filters, page: int, page_size: int):  # type: ignore[no-untyped-def]
        self._before(f"{report_type}_query", filters=filters, page=page, page_size=page_size)
        rows = (
            [{"incident": "WF-1", "note": "Cookie: sid=abc123 Authorization: Bearer xyz789", "password": "hidden"}]
            if report_type == "data_model"
            else [{
                "processNo": "SOR-WF-1",
                "carTypeProject": {
                    "id": "project-id-1",
                    "projectNo": "P100",
                    "projectName": "P100",
                },
                "processType": "Release",
                "sorNo": "SOR-9",
                "version": "V2",
                "title": "Seat SOR",
                "sorPartNo": "PART-2",
                "sorPartName": "Seat",
                "startUserName": "Bob",
                "deptName": "Engineering",
                "sectionName": "Interior",
                "startTime": "2026-02-01 10:00:00",
                "latestCompletedNode": "Review",
                "processInstanceStatus": "Completed",
                "currentAssigneeNameList": ["Alice", "Bob"],
                "note": "Cookie: sid=abc123 Authorization: Bearer xyz789",
                "password": "hidden",
            }]
        )
        return TDCPagedResult(
            report_type=report_type,
            rows=rows,
            page=page,
            page_size=page_size,
            total=5,
            pages=3,
            fetched_pages=1,
            unique_count=1,
            duplicate_count=0,
            stop_reason="single_page",
            record_granularity="part_detail",
        )

    def _crawl_result(  # type: ignore[no-untyped-def]
        self,
        report_type: str,
        filters,
        page_size: int,
        max_pages: int,
        max_records: int,
    ):
        self._before(
            f"{report_type}_crawl",
            filters=filters,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
        )
        rows = [{"incident": "WF-1"}] if report_type == "data_model" else [{"processNo": "SOR-WF-1"}]
        return TDCPagedResult(
            report_type=report_type,
            rows=rows,
            page=2,
            page_size=page_size,
            total=5,
            pages=3,
            fetched_pages=2,
            unique_count=1,
            duplicate_count=1,
            stop_reason="reported_pages",
            record_granularity="part_detail",
        )

    def query_data_model_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
        return self._query_result("data_model", filters, page=page, page_size=page_size)

    def crawl_data_model_all(self, filters, page_size=50, max_pages=100, max_records=10000, should_stop=None, on_page=None):  # type: ignore[no-untyped-def]
        return self._crawl_result("data_model", filters, page_size, max_pages, max_records)

    def query_sor_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
        return self._query_result("sor", filters, page=page, page_size=page_size)

    def crawl_sor_all(self, filters, page_size=50, max_pages=100, max_records=10000, should_stop=None, on_page=None):  # type: ignore[no-untyped-def]
        return self._crawl_result("sor", filters, page_size, max_pages, max_records)

    def list_car_type_projects(self):  # type: ignore[no-untyped-def]
        self._before("list_car_type_projects")
        return [
            {"id": "project-id-1", "projectNo": "P100", "projectName": "P100"},
            {"id": "project-id-2", "projectNo": "P200", "projectName": "Project 200"},
        ]

    def _export_result(self, report_type: str, filters, file_name):  # type: ignore[no-untyped-def]
        self._before(f"{report_type}_export", filters=filters, file_name=file_name)
        if self.export_outside:
            path = Path("C:/fictional/outside.xlsx")
            return TDCExportResult(
                report_type=report_type,
                file_name="outside.xlsx",
                path=path,
                byte_count=12,
                content_type="application/octet-stream",
                signature_valid=True,
                elapsed_ms=1.5,
                record_granularity="part_detail",
            )
        name = file_name or ("tdc_data_model.xlsx" if report_type == "data_model" else "tdc_sor_part_details.xlsx")
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / name
        path.write_bytes(b"PK\x03\x04fake-xlsx")
        return TDCExportResult(
            report_type=report_type,
            file_name=name,
            path=path,
            byte_count=path.stat().st_size,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            signature_valid=True,
            elapsed_ms=1.5,
            record_granularity="part_detail",
        )

    def export_data_model(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        return self._export_result("data_model", filters, file_name)

    def export_sor(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        return self._export_result("sor", filters, file_name)


class FakeTDCWebAuthClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None
    session = object()

    def __init__(self, base_url, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.__class__.calls.append(
            {"method": "init", "base_url": base_url, "timeout": timeout, "diagnostic_hook": diagnostic_hook}
        )

    def login(self, username, password):  # type: ignore[no-untyped-def]
        self.__class__.calls.append({"method": "login", "username": username, "password": password})
        if self.fail:
            raise self.fail
        return TDCLoginResult(session=self.session)


_TDC_DATA_MODEL_HEADERS = [
    "实例号", "流程名", "流水单号", "发布属性", "申请人", "部门", "申请日期", "项目/车型",
    "零件号", "数模号", "零件名称", "数量", "重量（单件）", "零件合计", "版本号", "对应IA号",
    "EWO/SOR号", "最新审批记录", "造型", "总体工程", "CAE", "整车性能", "车身", "内外饰",
    "底盘", "动力", "空调电子", "尺寸工程", "冲压", "车身制造", "涂装", "总装", "新能源",
    "感知质量", "造型专家审核", "NVH", "加签人员", "设计工程师", "主任工程师", "专家/经理", "首席/总监",
    "应签人数", "已签人数", "未签人数", "签署率", "待审批人员", "状态",
]

_TDC_SOR_HEADERS = [
    "流水单号",
    "车型项目",
    "类型",
    "SOR号",
    "版本号",
    "标题",
    "零件号",
    "零件名称",
    "申请人",
    "部门",
    "科室",
    "申请日期",
    "最新完成节点",
    "审批状态",
    "当前待办人",
]


def _write_tdc_data_model_xlsx(path: Path) -> None:
    def cell_ref(column: int, row: int) -> str:
        result = ""
        while column:
            column, remainder = divmod(column - 1, 26)
            result = chr(65 + remainder) + result
        return f"{result}{row}"

    headers = "".join(
        f'<c r="{cell_ref(index, 1)}" t="inlineStr"><is><t>{escape(label)}</t></is></c>'
        for index, label in enumerate(_TDC_DATA_MODEL_HEADERS, 1)
    )
    values = [
        "INC-1", "流程", "DOC-1", "T2发布", "申请人", "外饰科", "2026-01-01 10:00:00", "F610M",
        "P-1", "M-1", "零件", "1", "0.1", "0.1", "001", "IA-1", "N/A", "审批完成",
    ] + ["" for _ in range(len(_TDC_DATA_MODEL_HEADERS) - 18)]
    values[-1] = "已完成"
    row = "".join(
        f'<c r="{cell_ref(index, 2)}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        for index, value in enumerate(values, 1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f'<row r="1">{headers}</row><row r="2">{row}</row>'
        '</sheetData></worksheet>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _write_tdc_sor_xlsx(path: Path) -> None:
    def cell_ref(column: int, row: int) -> str:
        result = ""
        while column:
            column, remainder = divmod(column - 1, 26)
            result = chr(65 + remainder) + result
        return f"{result}{row}"

    headers = "".join(
        f'<c r="{cell_ref(index, 1)}" t="inlineStr"><is><t>{escape(label)}</t></is></c>'
        for index, label in enumerate(_TDC_SOR_HEADERS, 1)
    )
    values = [
        "SOR-WF-1", "E262S", "发布流程", "SOR-9", "A", "座椅 SOR", "PART-1", "座椅",
        "申请人", "车体工程", "内饰科", "2026-08-26 10:00:00", "审核", "审批中", "张三、李四",
    ]
    row = "".join(
        f'<c r="{cell_ref(index, 2)}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        for index, value in enumerate(values, 1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f'<row r="1">{headers}</row><row r="2">{row}</row>'
        '</sheetData></worksheet>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    FakeTDCWebClient.calls = []
    FakeTDCWebClient.fail = None
    FakeTDCWebClient.export_outside = False
    FakeTDCWebAuthClient.calls = []
    FakeTDCWebAuthClient.fail = None
    monkeypatch.setattr(web_app, "TDCCrawlerClient", FakeTDCWebClient)
    monkeypatch.setattr(web_app, "TDCPasswordAuthClient", FakeTDCWebAuthClient)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "deliverables-test.db"))
    monkeypatch.setattr(web_app, "DIAGNOSTIC_DIR", tmp_path / "diagnostics")
    app = web_app.create_app(tdc_allowed_hosts=["tdc.example"])
    app.config.update(TESTING=True)
    # 后台异步路径需要已建立的统一域会话
    registry = app.extensions.get("domain_sessions")
    if isinstance(registry, web_app.DomainSessionRegistry):
        registry.mark_authenticated("tdc", object())
    return app.test_client()


def test_catalog_is_truthful_and_contains_no_secrets(client) -> None:
    resp = client.get("/api/deliverables/catalog")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["categories"]
    ids = [item["id"] for item in data["deliverables"]]
    assert ids == [
        "aras-ewo",
        "aras-paa",
        "aras-ncr-progress",
        "aras-ncr-detail",
        "tdc-data-model",
        "tdc-sor",
    ]
    # 2026-09-06：不可用条目（仅 CLI/已禁用/占位）已从目录全部移除。
    for removed_id in (
        "tdc-a-face",
        "dm-change-form",
        "deliverables-register",
        "excel-toolbox",
        "weekly-ppt",
        "feishu-tasks",
        "office-deliverables-excel",
        "vertical-ewo-form",
        "vertical-ncr-form",
        "vertical-styling-review-form",
        "intranet-ncr-scraper",
    ):
        assert removed_id not in ids
    text = resp.get_data(as_text=True)
    for marker in ("password", "Bearer ", "api_key", "C:\\", "\\\\server", "/Users/"):
        assert marker not in text


def test_catalog_statuses_availability_and_schema(client) -> None:
    items = client.get("/api/deliverables/catalog").get_json()["data"]["deliverables"]
    required_keys = {
        "id",
        "name",
        "category",
        "source",
        "availability",
        "implementation_status",
        "description",
        "output_formats",
        "operations",
        "fields",
        "links",
    }
    by_id = {item["id"]: item for item in items}
    for item in items:
        assert required_keys <= set(item)
        assert item["implementation_status"] in ALLOWED_IMPLEMENTATION_STATUSES
        assert item["availability"] in ALLOWED_AVAILABILITY
        assert isinstance(item["fields"], list)
        assert isinstance(item["operations"], list)
        assert all(isinstance(value, str) and value == value.upper() for value in item["output_formats"])

    assert by_id["tdc-data-model"]["availability"] == "available"
    assert by_id["tdc-data-model"]["implementation_status"] == "已完整实现"
    assert by_id["tdc-data-model"]["operations"] == ["query", "crawl_all", "export"]
    assert by_id["tdc-data-model"]["output_formats"] == ["JSON", "XLSX"]
    assert by_id["tdc-sor"]["implementation_status"] == "已完整实现"
    assert by_id["tdc-sor"]["output_formats"] == ["JSON", "XLSX"]


def test_catalog_links_follow_deliverable_registry(client) -> None:
    """目录条目 links 字段与单一关联注册表一致（只追加，向后兼容）。"""
    items = client.get("/api/deliverables/catalog").get_json()["data"]["deliverables"]
    by_id = {item["id"]: item for item in items}
    expected = {
        "aras-ewo": {
            "archiveJobKey": "aras_ewo",
            "projectStatusDeliverableId": "VPI-T2-D3",
            "displayCode": "DEL-003",
            "formKey": "VPI-T2-D3",
        },
        "aras-paa": {
            "archiveJobKey": "aras_paa",
            "projectStatusDeliverableId": "VPI-T2-D6",
            "displayCode": "DEL-006",
            "formKey": "aras_paa",
        },
        "aras-ncr-progress": {
            "archiveJobKey": "aras_ncr_progress",
            "projectStatusDeliverableId": "VPI-T2-D7",
            "displayCode": "DEL-007",
            "formKey": "aras_ncr_progress",
        },
        "aras-ncr-detail": {
            "archiveJobKey": "aras_ncr_detail",
            "projectStatusDeliverableId": "VPI-T2-D8",
            "displayCode": "DEL-008",
            "formKey": "aras_ncr_detail",
        },
        "tdc-data-model": {
            "archiveJobKey": "tdc_data_model",
            "projectStatusDeliverableId": "VPI-T2-D5",
            "displayCode": "DEL-005",
            "formKey": "tdc_data_model",
        },
        "tdc-sor": {
            "archiveJobKey": "tdc_sor",
            "projectStatusDeliverableId": "VPI-T2-D2",
            "displayCode": "DEL-002",
            "formKey": "tdc_sor",
        },
    }
    assert set(expected) == set(by_id)
    for catalog_id, links in expected.items():
        assert by_id[catalog_id]["links"] == links
    assert [field["name"] for field in by_id["tdc-data-model"]["fields"]] == [
        "serial_number",
        "applicant",
        "department",
        "section",
        "application_start",
        "application_end",
        "project_model",
        "part_number",
        "model_number",
        "status",
    ]
    assert [field["name"] for field in by_id["tdc-sor"]["fields"]] == [
        "serial_number",
        "process_type",
        "car_type_project",
        "applicant",
        "title",
        "department",
        "section",
        "application_start",
        "application_end",
        "part_number",
        "part_name",
        "version",
        "sor_number",
        "latest_completed_node",
        "approval_status",
    ]

    for aras_id in ("aras-ewo", "aras-paa", "aras-ncr-progress", "aras-ncr-detail"):
        assert by_id[aras_id]["availability"] == "available"
        assert by_id[aras_id]["implementation_status"] == "已完整实现"
        assert by_id[aras_id]["fields"] == []
        assert by_id[aras_id]["target"]["panel"] == "aras-panel"

    assert "TDC 数模设计审核流程报表" in by_id["tdc-data-model"]["name"]


def test_catalog_display_code_prefers_stored_display_code(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """顺延场景（display_code 冲突后重建）：catalog 与项目状态页展示码一致。

    注册表常量只是种子值；存量库顺延重建后实际展示码可能不同（此处模拟
    D6 顺延为 DEL-009）。catalog links.displayCode 必须优先取
    project_status_deliverables 表的实际值，与 /api/project-status 的
    displayCode 一致；表中查不到时回退注册表常量。
    """
    db = web_app.DatabaseManager(tmp_path / "catalog-display-code.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_deliverables SET display_code = 'DEL-009' "
            "WHERE id = 'VPI-T2-D6'"
        )
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app()
    app.config.update(TESTING=True)
    flask_client = app.test_client()

    catalog = flask_client.get("/api/deliverables/catalog").get_json()["data"]["deliverables"]
    links_by_id = {item["id"]: item["links"] for item in catalog}
    # 顺延后实际展示码优先于注册表常量 DEL-006。
    assert links_by_id["aras-paa"]["displayCode"] == "DEL-009"

    status = flask_client.get("/api/project-status").get_json()["data"]
    status_by_id = {row["id"]: row for row in status["deliverables"]}
    assert status_by_id["VPI-T2-D6"]["displayCode"] == "DEL-009"
    assert links_by_id["aras-paa"]["displayCode"] == status_by_id["VPI-T2-D6"]["displayCode"]

    # 回退：表中无对应行时回退注册表常量。
    with db.get_connection() as conn:
        conn.execute("DELETE FROM project_status_deliverables WHERE id = 'VPI-T2-D2'")
    catalog_after = flask_client.get("/api/deliverables/catalog").get_json()["data"]["deliverables"]
    links_after = {item["id"]: item["links"] for item in catalog_after}
    assert links_after["tdc-sor"]["displayCode"] == "DEL-002"


def test_tdc_sor_car_type_project_endpoint_returns_safe_options(client) -> None:
    response = client.post(
        "/api/tdc/sor/car-type-projects",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "cookie": "sid=secret-cookie",
            "filters": {},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["projects"] == [
        {"id": "project-id-1", "projectNo": "P100", "projectName": "P100", "label": "P100"},
        {"id": "project-id-2", "projectNo": "P200", "projectName": "Project 200", "label": "P200 — Project 200"},
    ]
    assert "secret-cookie" not in response.get_data(as_text=True)


def test_tdc_ui_exposes_fast_and_exact_preview_modes() -> None:
    """Both TDC report forms expose fast list and exact official-export modes."""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "快速查询" in js_text
    assert "官方 Excel 精确预览（较慢）" in js_text
    assert 'fieldValue(form, "preview_source")' in js_text
    assert 'if (item.id === "tdc-data-model" || item.id === "tdc-sor")' in js_text
    assert 'payload.preview_source = "official_export"' not in js_text


def test_tdc_sor_ui_uses_manual_vehicle_project_input() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    assert "/api/tdc/sor/car-type-projects" in js_text
    assert "loadTdcSorProjectOptions" in js_text
    assert "tdc-car-type-project-options" in js_text
    assert "重新加载车型项目" in js_text
    assert "car_type_project_id" in js_text
    assert "input.dataset.deliverableField = field.name;" in js_text


def test_tdc_preview_source_rejects_unknown_values_before_upstream_access(client) -> None:
    before = len(FakeTDCWebClient.calls)
    response = client.post(
        "/api/tdc/data-model/query",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "cookie": "sid=secret-cookie",
            "preview_source": "unexpected-mode",
            "filters": {},
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "ValidationError"
    assert len(FakeTDCWebClient.calls) == before


def test_result_table_body_cells_wrap_long_text() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    body_rules = re.findall(r"\.result-table tbody tr td\s*\{([^}]*)\}", css_text)

    assert body_rules
    assert "white-space: normal" in body_rules[-1]
    assert "overflow-wrap: anywhere" in body_rules[-1]


def test_tdc_export_cache_module_is_part_of_the_runtime_contract() -> None:
    """The WebUI must include a bounded official-export cache implementation."""
    cache_module = Path("services/tdc_export_cache.py")
    assert cache_module.is_file()
    assert "TDCExportCache" in cache_module.read_text(encoding="utf-8-sig")


def test_tdc_data_model_query_password_mode(client) -> None:
    resp = client.post(
        "/api/tdc/data-model/query",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "headers": {"X-Test": "yes"},
            "filters": {
                "serial_number": "WF-1",
                "applicant": "Alice",
                "department": "Engineering",
                "section": "Body",
                "application_start": "2026-01-01",
                "application_end": "2026-01-31",
                "project_model": "P100",
                "part_number": "PART-1",
                "model_number": "DM-1",
            },
            "page": 2,
            "page_size": 25,
            "max_records": 100,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["report_type"] == "data_model"
    assert len(data["rows"]) == 1
    assert len(data["rows"][0]) == 47
    assert data["rows"][0][0] == "WF-1"
    assert data["rows"][0][1:] == [None] * 46
    assert data["data_source"] == "list_endpoint"
    assert data["mappingComplete"] is False
    assert data["page"] == 2
    assert data["page_size"] == 25
    assert data["total"] == 5
    assert data["pages"] == 3
    assert data["fetched_pages"] == 1
    assert data["unique_count"] == 1
    assert data["duplicate_count"] == 0
    assert data["stop_reason"] == "single_page"
    assert data["record_granularity"] == "part_detail"
    body_text = resp.get_data(as_text=True)
    assert "fictional-user" not in body_text
    assert "fictional-password-secret" not in body_text
    assert "abc123" not in body_text
    assert "xyz789" not in body_text
    assert "password" not in body_text

    login_call = next(call for call in FakeTDCWebAuthClient.calls if call["method"] == "login")
    assert login_call["username"] == "fictional-user"
    assert login_call["password"] == "fictional-password-secret"
    init_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "init")
    assert init_call["session"] is FakeTDCWebAuthClient.session
    assert init_call["headers"] == {"X-Test": "yes"}
    query_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "data_model_query")
    filters = query_call["filters"]
    assert filters.serial_number == "WF-1"
    assert filters.applicant == "Alice"
    assert filters.department == "Engineering"
    assert filters.section == "Body"
    assert filters.application_start == "2026-01-01"
    assert filters.application_end == "2026-01-31"
    assert filters.project_model == "P100"
    assert filters.part_number == "PART-1"
    assert filters.model_number == "DM-1"
    assert query_call["page"] == 2
    assert query_call["page_size"] == 25


def test_tdc_data_model_query_uses_official_export_preview_when_requested(client, monkeypatch) -> None:
    def export_preview(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        self._before("data_model_export", filters=filters, file_name=file_name)
        assert self.output_dir is not None
        path = self.output_dir / (file_name or "tdc_data_model_preview.xlsx")
        _write_tdc_data_model_xlsx(path)
        return TDCExportResult(
            report_type="data_model",
            file_name=path.name,
            path=path,
            byte_count=path.stat().st_size,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            signature_valid=True,
            elapsed_ms=1.0,
            record_granularity="part_detail",
        )

    monkeypatch.setattr(FakeTDCWebClient, "export_data_model", export_preview)
    response = client.post(
        "/api/tdc/data-model/query",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "cookie": "sid=secret-cookie",
            "preview_source": "official_export",
            "filters": {"project_model": "F610M"},
            "page": 1,
            "page_size": 50,
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["data_source"] == "official_export"
    assert data["headerRows"][0][:3] == ["实例号", "流程名", "流水单号"]
    assert data["rows"][0][:3] == ["INC-1", "流程", "DOC-1"]
    assert data["rows"][0][-1] == "已完成"
    assert data["mappingComplete"] is True
    assert data["total"] == 1
    assert data["record_granularity"] == "part_detail"


def test_tdc_sor_query_uses_official_export_preview_contract(client, monkeypatch) -> None:
    def export_preview(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        self._before("sor_export", filters=filters, file_name=file_name)
        assert self.output_dir is not None
        path = self.output_dir / (file_name or "tdc_sor_preview.xlsx")
        _write_tdc_sor_xlsx(path)
        return TDCExportResult(
            report_type="sor",
            file_name=path.name,
            path=path,
            byte_count=path.stat().st_size,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            signature_valid=True,
            elapsed_ms=1.0,
            record_granularity="part_detail",
        )

    monkeypatch.setattr(FakeTDCWebClient, "export_sor", export_preview)
    response = client.post(
        "/api/tdc/sor/query",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "cookie": "sid=secret-cookie",
            "preview_source": "official_export",
            "filters": {"car_type_project": "E262S", "department": "车体工程"},
            "page": 1,
            "page_size": 50,
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["data_source"] == "official_export"
    assert data["headerRows"] == [_TDC_SOR_HEADERS]
    assert data["rows"] == [[
        "SOR-WF-1", "E262S", "发布流程", "SOR-9", "A", "座椅 SOR", "PART-1", "座椅",
        "申请人", "车体工程", "内饰科", "2026-08-26 10:00:00", "审核", "审批中", "张三、李四",
    ]]
    assert data["mappingComplete"] is True
    assert any(call["method"] == "sor_export" for call in FakeTDCWebClient.calls)
    assert not any(call["method"] == "sor_query" for call in FakeTDCWebClient.calls)


def test_tdc_official_preview_reuses_password_mode_cache(client, monkeypatch) -> None:
    """Identical exact previews reuse one official export for the same local user."""
    export_calls = [0]

    def export_preview(self, filters, file_name=None):  # type: ignore[no-untyped-def]
        export_calls[0] += 1
        assert self.output_dir is not None
        path = self.output_dir / (file_name or "tdc_data_model_preview.xlsx")
        _write_tdc_data_model_xlsx(path)
        return TDCExportResult(
            report_type="data_model",
            file_name=path.name,
            path=path,
            byte_count=path.stat().st_size,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            signature_valid=True,
            elapsed_ms=1.0,
            record_granularity="part_detail",
        )

    monkeypatch.setattr(FakeTDCWebClient, "export_data_model", export_preview)
    payload = {
        "base_url": "https://tdc.example",
        "auth_mode": "password",
        "username": "fictional-user",
        "password": "fictional-password-secret",
        "preview_source": "official_export",
        "filters": {"project_model": "F610M"},
        "page": 1,
        "page_size": 50,
    }
    first = client.post("/api/tdc/data-model/query", json=payload)
    second = client.post("/api/tdc/data-model/query", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.get_json()["data"]["cache"]["hit"] is False
    assert second.get_json()["data"]["cache"]["hit"] is True
    assert export_calls == [1]


def test_tdc_sor_query_browser_cookie_mode(client) -> None:
    resp = client.post(
        "/api/tdc/sor/query",
        json={
            "base_url": "http://tdc.example",
            "auth_mode": "browser",
            "cookie": "sid=secret-cookie",
            "headers": {"X-Test": "yes"},
            "filters": {
                "serial_number": "SOR-WF-1",
                "process_type": "Release",
                "car_type_project": "P100",
                "car_type_project_id": "project-id-1",
                "applicant": "Bob",
                "title": "Seat SOR",
                "department": "Engineering",
                "section": "Interior",
                "application_start": "2026-02-01",
                "application_end": "2026-02-28",
                "part_number": "PART-2",
                "part_name": "Seat",
                "version": "V2",
                "sor_number": "SOR-9",
                "latest_completed_node": "Review",
                "approval_status": "Completed",
            },
            "page": 1,
            "page_size": 50,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["report_type"] == "sor"
    assert data["record_granularity"] == "part_detail"
    assert data["headerRows"] == [_TDC_SOR_HEADERS]
    assert data["rows"] == [[
        "SOR-WF-1", "P100", "Release", "SOR-9", "V2", "Seat SOR", "PART-2", "Seat",
        "Bob", "Engineering", "Interior", "2026-02-01 10:00:00", "Review", "Completed", "Alice、Bob",
    ]]
    assert data["mappingComplete"] is True
    body_text = resp.get_data(as_text=True)
    assert "secret-cookie" not in body_text
    init_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "init")
    assert init_call["session"] is None
    assert init_call["headers"]["Cookie"] == "sid=secret-cookie"
    assert init_call["headers"]["X-Test"] == "yes"
    query_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "sor_query")
    filters = query_call["filters"]
    assert filters.serial_number == "SOR-WF-1"
    assert filters.process_type == "Release"
    assert filters.car_type_project == "P100"
    assert filters.car_type_project_id == "project-id-1"
    assert filters.applicant == "Bob"
    assert filters.title == "Seat SOR"
    assert filters.department == "Engineering"
    assert filters.section == "Interior"
    assert filters.application_start == "2026-02-01"
    assert filters.application_end == "2026-02-28"
    assert filters.part_number == "PART-2"
    assert filters.part_name == "Seat"
    assert filters.version == "V2"
    assert filters.sor_number == "SOR-9"
    assert filters.latest_completed_node == "Review"
    assert filters.approval_status == "Completed"


def _wait_for_tdc_background_task(client, task_id: str, timeout: float = 10.0) -> dict:
    import time as _time

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        task = resp.get_json()["data"]
        if not task["is_active"]:
            return task
        _time.sleep(0.05)
    raise AssertionError("background task did not finish in time")


def test_tdc_crawl_all_contract(client) -> None:
    resp = client.post(
        "/api/tdc/data-model/crawl-all",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "filters": {"part_number": "PART-1"},
            "page_size": 40,
            "max_pages": 6,
            "max_records": 120,
        },
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["source"] == "tdc"
    task_id = body["data"]["taskId"]

    task = _wait_for_tdc_background_task(client, task_id)
    assert task["status"] == "succeeded"
    assert task["task_type"] == "tdc_data_model_crawl"

    crawl_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "data_model_crawl")
    assert crawl_call["page_size"] == 40
    assert crawl_call["max_pages"] == 6
    assert crawl_call["max_records"] == 120
    assert crawl_call["filters"].part_number == "PART-1"

    result = client.get(f"/api/tasks/{task_id}/result")
    assert result.status_code == 200
    data = result.get_json()["data"]
    assert data["fetched_pages"] == 2
    assert data["duplicate_count"] == 1
    assert data["stop_reason"] == "reported_pages"


def test_tdc_export_creates_async_xlsx_artifact(client) -> None:
    resp = client.post(
        "/api/tdc/data-model/export",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "filters": {"part_number": "PART-1"},
            "file_name": "data-model-2026.xlsx",
        },
    )
    assert resp.status_code == 202
    body = resp.get_json()
    task_id = body["data"]["taskId"]

    task = _wait_for_tdc_background_task(client, task_id)
    assert task["status"] == "succeeded"
    assert task["can_download"] is True

    export_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "data_model_export")
    # 工件按任务唯一化命名，避免并发导出互相覆盖
    assert export_call["file_name"].startswith("data-model-2026_")
    assert export_call["file_name"].endswith(".xlsx")

    init_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "init")
    assert init_call["output_dir"] is not None

    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["Content-Disposition"]
    assert download.get_data().startswith(b"PK")


def test_tdc_export_rejects_unsafe_file_names_without_client(client) -> None:
    for bad_name in ("../evil.xlsx", "sub/evil.xlsx", "..\\evil.xlsx", "C:\\evil.xlsx", "evil.csv", "evil"):
        resp = client.post(
            "/api/tdc/data-model/export",
            json={
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "cookie": "sid=secret-cookie",
                "filters": {},
                "file_name": bad_name,
            },
        )
        assert resp.status_code == 400, bad_name
        assert resp.get_json()["error"]["type"] == "ValidationError"
        assert "file_name" in resp.get_json()["error"]["message"]
    assert FakeTDCWebClient.calls == []


def test_tdc_export_failure_is_sanitized_in_task_record(client) -> None:
    FakeTDCWebClient.export_outside = True
    resp = client.post(
        "/api/tdc/data-model/export",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "browser",
            "filters": {},
        },
    )
    assert resp.status_code == 202
    task_id = resp.get_json()["data"]["taskId"]

    task = _wait_for_tdc_background_task(client, task_id)
    assert task["status"] == "failed"
    error_text = task.get("error_message") or ""
    assert "outside the download directory" in error_text
    # 失败消息必须脱敏：本机/虚构路径不得回显到任务记录
    assert "C:" not in error_text
    assert "fictional" not in error_text
    init_call = next(call for call in FakeTDCWebClient.calls if call["method"] == "init")
    assert init_call["output_dir"] is not None


def test_tdc_validation_host_auth_types_and_bounds(client) -> None:
    cases = [
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "http://evil.example",
                "auth_mode": "browser",
                "cookie": "sid=secret",
                "filters": {},
            },
            "HostNotAllowed",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "http://tdc.example",
                "auth_mode": "password",
                "username": "u",
                "password": "p",
                "filters": {},
            },
            "HostNotAllowed",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "password",
                "username": "",
                "password": "p",
                "filters": {},
            },
            "ValidationError",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "password",
                "username": "u",
                "password": "p",
                "cookie": "sid=secret",
                "filters": {},
            },
            "AuthenticationModeConflict",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "username": "u",
                "password": "p",
                "cookie": "sid=secret",
                "filters": {},
            },
            "AuthenticationModeConflict",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "cookie": "sid=secret",
                "filters": [],
            },
            "ValidationError",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "cookie": "sid=secret",
                "filters": {"unsupported": "x"},
            },
            "ValidationError",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "cookie": "sid=secret",
                "filters": {},
                "page": 0,
            },
            "ValidationError",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "cookie": "sid=secret",
                "filters": {},
                "page_size": 1001,
            },
            "ValidationError",
        ),
        (
            "/api/tdc/data-model/query",
            {
                "base_url": "https://tdc.example",
                "auth_mode": "browser",
                "cookie": "sid=secret",
                "filters": {},
                "page_size": True,
            },
            "ValidationError",
        ),
    ]
    for endpoint, payload, error_type in cases:
        resp = client.post(endpoint, json=payload)
        assert resp.status_code == 400, payload
        assert resp.get_json()["error"]["type"] == error_type
        assert "secret" not in resp.get_data(as_text=True)
    assert all(call["method"] == "init" for call in FakeTDCWebClient.calls)


def test_tdc_error_mapping_auth_crawler_value_unknown(client) -> None:
    FakeTDCWebAuthClient.fail = TDCAuthError("login failed Cookie: sid=abc123")
    auth_failed = client.post(
        "/api/tdc/data-model/query",
        json={
            "base_url": "https://tdc.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "filters": {},
        },
    )
    assert auth_failed.status_code == 401
    assert auth_failed.get_json()["error"]["type"] == "AuthenticationError"
    assert "abc123" not in auth_failed.get_data(as_text=True)
    # 认证失败生成诊断报告，前端路径透传为 .md 且文件真实落盘，不含 secret
    diag_path = auth_failed.get_json()["error"].get("diagnosticPath")
    assert isinstance(diag_path, str) and diag_path.endswith(".md")
    assert Path(diag_path).is_file()
    report_text = Path(diag_path).read_text(encoding="utf-8")
    assert "fictional-password-secret" not in report_text
    assert "abc123" not in report_text
    FakeTDCWebAuthClient.fail = None
    FakeTDCWebClient.calls = []

    FakeTDCWebClient.fail = TDCCrawlerError("contract blocked", stage="contract-validation")
    contract = client.post(
        "/api/tdc/sor/query",
        json={"base_url": "https://tdc.example", "auth_mode": "browser", "cookie": "sid=abc", "filters": {}},
    )
    assert contract.status_code == 400
    assert contract.get_json()["error"]["type"] == "TDCCrawlerError"

    FakeTDCWebClient.fail = TDCCrawlerError(
        "upstream Cookie: sid=abc123 Authorization: Bearer xyz789", stage="status-validation"
    )
    upstream = client.post(
        "/api/tdc/sor/query",
        json={"base_url": "https://tdc.example", "auth_mode": "browser", "cookie": "sid=abc", "filters": {}},
    )
    assert upstream.status_code == 502
    text = upstream.get_data(as_text=True)
    assert "abc123" not in text
    assert "xyz789" not in text

    FakeTDCWebClient.fail = ValueError("application date start must not be after end")
    invalid = client.post(
        "/api/tdc/sor/query",
        json={"base_url": "https://tdc.example", "auth_mode": "browser", "cookie": "sid=abc", "filters": {}},
    )
    assert invalid.status_code == 400
    assert invalid.get_json()["error"]["type"] == "ValidationError"

    FakeTDCWebClient.fail = RuntimeError("boom C:\\secret\\path.txt")
    unknown = client.post(
        "/api/tdc/sor/query",
        json={"base_url": "https://tdc.example", "auth_mode": "browser", "cookie": "sid=abc", "filters": {}},
    )
    assert unknown.status_code == 500
    assert unknown.get_json()["error"]["message"] == "Unexpected server error"
    assert "C:\\secret" not in unknown.get_data(as_text=True)


def test_tdc_missing_blank_or_non_string_base_url_returns_400(client) -> None:
    endpoints = (
        "/api/tdc/data-model/query",
        "/api/tdc/data-model/crawl-all",
        "/api/tdc/data-model/export",
        "/api/tdc/sor/query",
        "/api/tdc/sor/crawl-all",
        "/api/tdc/sor/export",
    )
    bad_payloads = (
        {"auth_mode": "browser", "filters": {}},
        {"base_url": "", "auth_mode": "browser", "filters": {}},
        {"base_url": "   ", "auth_mode": "browser", "filters": {}},
        {"base_url": ["https://tdc.example"], "auth_mode": "browser", "filters": {}},
        {"base_url": {"url": "https://tdc.example"}, "auth_mode": "browser", "filters": {}},
        {"base_url": 123, "auth_mode": "browser", "filters": {}},
    )
    for endpoint in endpoints:
        for payload in bad_payloads:
            resp = client.post(endpoint, json=payload)
            assert resp.status_code == 400, (endpoint, payload)
            error = resp.get_json()["error"]
            assert error["type"] in {"ValidationError", "HostNotAllowed"}, (endpoint, payload)
            assert "base_url" in error["message"]
            assert "secret" not in resp.get_data(as_text=True)
    assert FakeTDCWebClient.calls == []
    assert FakeTDCWebAuthClient.calls == []


def test_tdc_disabled_a_face_routes_are_contract_blocked(client) -> None:
    for endpoint in ("/api/tdc/a-face/query", "/api/tdc/a-face/crawl-all", "/api/tdc/a-face/export"):
        resp = client.post(endpoint, json={"base_url": "https://evil.example", "filters": {}})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"]["type"] == "ContractBlocker"
        assert "HAR" in body["error"]["message"]
        assert "ots2" in body["error"]["message"]
    assert FakeTDCWebClient.calls == []

    missing = client.post("/api/tdc/dm-change-form/query", json={"base_url": "https://tdc.example", "filters": {}})
    assert missing.status_code == 404


def test_static_deliverables_guards() -> None:
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    assert 'data-panel-link="deliverables"' in html_text
    assert 'id="deliverables"' in html_text
    assert "/api/deliverables/catalog" in js_text
    for endpoint in (
        "/api/tdc/data-model/query",
        "/api/tdc/data-model/crawl-all",
        "/api/tdc/data-model/export",
        "/api/tdc/sor/query",
        "/api/tdc/sor/crawl-all",
        "/api/tdc/sor/export",
    ):
        assert endpoint in js_text

    assert "RECENT_RUN_LIMIT" in js_text
    assert "recentRuns" in js_text
    assert "sessionStorage" not in js_text
    assert "sessionStorage" not in html_text
    storage_lines = [line for line in js_text.splitlines() if "localStorage" in line]
    assert storage_lines
    assert all("THEME_KEY" in line or "GRID_COLUMN_PREF_KEY" in line for line in storage_lines)
    assert not re.search(
        r"(?:cookie|token|authorization|sessionid|csrf|password).{0,80}localStorage",
        html_text + js_text,
        re.IGNORECASE,
    )

    assert "item.availability === \"available\"" in js_text
    assert "item.availability !== \"available\"" in js_text
    assert "Number(" in js_text
    assert "redactSensitiveText(err.message)" in js_text
    assert "clearDeliverablePayloadSecrets" in js_text
    # 统一域账号登录后，交付物表单不再保留账号密码输入，凭据清理只剩 payload 侧。
    assert "clearDeliverableFormSecrets" not in js_text
    assert 'name="auth_mode"' not in js_text
    assert "payload.headers = {}" in js_text
    assert "tdc-headers" in js_text
    assert 'name="output_format"' in js_text
    assert 'value="XLSX"' in js_text
    assert "checkValidity" in js_text
    assert "reportValidity" in js_text
    assert "DELIVERABLE_STATUS_TONE_CLASS" in js_text
    assert "status-${item.implementation_status}" not in js_text
    assert "当前请求仍在处理中，请等待完成" in js_text
    assert 'name="operation_mode"' in js_text
    assert '<option value="query" selected>查询预览</option>' in js_text
    assert '<option value="crawl_all">全量抓取</option>' in js_text
    assert '<option value="export">导出 XLSX</option>' in js_text
    assert 'id="deliverable-operation-mode"' in js_text
    assert 'operationMode.addEventListener("change"' in js_text
    assert 'id="deliverable-run-button"' in js_text
    assert 'id="deliverable-download-button"' in js_text
    assert 'data-deliverable-download' in js_text
    assert 'runDeliverableOperation(item, "export")' in js_text
    assert 'preview_source' in js_text
    assert 'mode.disabled = Boolean(isRunning)' in js_text
    assert 'runButton.disabled = Boolean(isRunning)' in js_text
    assert js_text.count('runDeliverableOperation(item, operation);') == 1
    assert 'data-deliverable-operation' not in js_text
    assert 'name="page" type="number" min="1" value="1" required' in js_text
    assert 'name="page_size" type="number" min="1" value="50" required' in js_text
    assert 'name="max_pages" type="number" min="1" value="100" required' in js_text
    assert 'name="max_records" type="number" min="1" value="10000" required' in js_text
    assert 'name="output_format" required' in js_text
    assert 'name="file_name" type="text" value="${escapeHtml(config.defaultExportName)}" required' in js_text
    assert js_text.index('operationMode.addEventListener("change"') < js_text.index('form.addEventListener("submit"')
    assert ".deliverables-layout" in css_text
    assert ".deliverable-item" in css_text
    mobile_list_rule = re.search(
        r"@media \(max-width: 560px\)[\s\S]*?\.deliverable-list\s*\{([^}]*)\}",
        css_text,
    )
    assert mobile_list_rule is not None
    assert "width: 100%" in mobile_list_rule.group(1)
    assert "max-height: 42vh" in mobile_list_rule.group(1)
    assert "overflow-y: auto" in mobile_list_rule.group(1)
    assert "overflow-x: hidden" in mobile_list_rule.group(1)
    assert ".recent-item" in css_text
    assert ".status-chip.is-fully-implemented" in css_text
    assert ".status-chip.is-backend-no-frontend" in css_text
    assert ".status-chip.is-partial" in css_text
    assert ".status-chip.is-placeholder" in css_text
    assert "overflow-x: hidden" in css_text
    assert "border-radius: 16px" not in css_text
    assert css_text.count("border-radius: 12px") == 1
