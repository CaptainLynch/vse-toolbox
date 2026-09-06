# -*- coding: utf-8 -*-
"""Generate realistic preview snapshots for deliverable form views."""

from datetime import datetime, timezone
from core.db_manager import DatabaseManager
from services.deliverable_form_analysis import build_form_snapshot, form_definition


def generate_tdc_rows():
    definition = form_definition("tdc_data_model")
    headers = definition["headerRows"][0]

    items = [
        # (instance_no, flow_name, req_no, attr, applicant, dept, req_date, project, part_no, model_no, part_name, status, signed_pct)
        ("900101", "T2发布-前保险杠骨架", "F999X-3D-001", "T2发布", "张工程", "外饰科", "2026-08-20 09:30:00", "F999X", "27010001", "27010001", "前保险杠骨架", "已完成", "100.00%"),
        ("900102", "T2发布-仪表板下本体", "F999X-3D-002", "T2发布", "李工程", "内饰科", "2026-08-22 14:15:00", "F999X", "27020002", "27020002", "仪表板下本体", "审批中", "85.00%"),
        ("900103", "T2发布-左前门内板", "F999X-3D-003", "T2发布", "王工程", "车身科", "2026-08-25 10:00:00", "F999X", "27030003", "27030003", "左前门内板", "审批中", "70.00%"),
        ("900104", "量产发布-副车架总成", "F888Y-3D-004", "量产发布", "赵工程", "底盘科", "2026-08-15 11:20:00", "F888Y", "27040004", "27040004", "副车架总成", "审批中", "60.00%"), # 超期 > 7天
        ("900105", "试制发布-线束支架", "F888Y-3D-005", "试制发布", "孙工程", "电子电器科", "2026-08-28 16:40:00", "F888Y", "27050005", "27050005", "线束支架", "已完成", "100.00%"),
        ("900106", "方案发布-顶盖外板", "N300-3D-006", "方案发布", "周工程", "车身科", "2026-08-29 09:00:00", "N300", "27060006", "27060006", "顶盖外板", "已废弃", "30.00%"),
        ("900107", "T2发布-中央通道总成", "F999X-3D-007", "T2发布", "吴工程", "内饰科", "2026-08-26 13:30:00", "F999X", "27070007", "27070007", "中央通道总成", "审批中", "50.00%"),
        ("900108", "T2发布-后扭梁总成", "N300-3D-008", "T2发布", "郑工程", "底盘科", "2026-08-12 10:20:00", "N300", "27080008", "27080008", "后扭梁总成", "审批中", "40.00%"), # 超期
        ("900109", "量产发布-进气歧管总成", "E50-3D-009", "量产发布", "陈工程", "动力系统科", "2026-08-18 15:10:00", "E50", "27090009", "27090009", "进气歧管总成", "已完成", "100.00%"),
        ("900110", "T2发布-电池箱托盘", "E50-3D-010", "T2发布", "刘工程", "车身科", "2026-08-27 11:00:00", "E50", "27100010", "27100010", "电池箱托盘", "审批中", "90.00%"),
    ]

    rows = []
    for item in items:
        vals = [None] * len(headers)
        labeled = {
            "实例号": item[0],
            "流程名": item[1],
            "流水单号": item[2],
            "发布属性": item[3],
            "申请人": item[4],
            "部门": item[5],
            "申请日期": item[6],
            "项目/车型": item[7],
            "零件号": item[8],
            "数模号": item[9],
            "零件名称": item[10],
            "数量": 1,
            "重量（单件）": 1.25,
            "零件合计": 1.25,
            "版本号": "001.0001",
            "对应IA号": "IA2026-001",
            "EWO/SOR号": f"EWO-{item[0]}",
            "应签人数": 10,
            "已签人数": int(10 * float(item[12].replace("%", "")) / 100),
            "未签人数": 10 - int(10 * float(item[12].replace("%", "")) / 100),
            "签署率": item[12],
            "状态": item[11],
        }
        for k, v in labeled.items():
            if k in headers:
                vals[headers.index(k)] = v
        rows.append({"values": vals, "sheetName": "Sheet1"})
    return rows


def generate_ncr_progress_rows():
    definition = form_definition("aras_ncr_progress")
    headers = definition["headerRows"][int(definition["dataHeaderRow"])]
    
    ncr_samples = [
        ("NCR-2026-001", "F999X", "车身工程科", "PE科室经理", "2026-08-15", "审批中", "否"),
        ("NCR-2026-002", "F999X", "外饰工程科", "价值工程经理", "2026-08-20", "审批中", "否"),
        ("NCR-2026-003", "F888Y", "内饰工程科", "CLOSE", "2026-08-10", "已完成", "是"),
        ("NCR-2026-004", "F888Y", "底盘工程科", "PE部门总监", "2026-08-25", "审批中", "否"),
        ("NCR-2026-005", "N300", "电子电器科", "财务工程师", "2026-08-28", "审批中", "否"),
        ("NCR-2026-006", "E50", "动力集成科", "平台首席", "2026-08-01", "审批中", "否"),
        ("NCR-2026-007", "E50", "车身工程科", "CLOSE", "2026-08-12", "已完成", "是"),
    ]
    rows = []
    for ncr in ncr_samples:
        vals = [None] * len(headers)
        labeled = {
            "NCR编号": ncr[0],
            "项目": ncr[1],
            "区域": ncr[2],
            "当前节点及通知时间": ncr[3],
            "PE填写": ncr[4],
            "状态": ncr[5],
            "是否审批完成": ncr[6],
        }
        for k, v in labeled.items():
            if k in headers:
                vals[headers.index(k)] = v
        rows.append({"values": vals, "sheetName": "Sheet1"})
    return rows


def main():
    db = DatabaseManager()
    db.init_database()

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. 注入 tdc_data_model 快照
    tdc_snapshot = build_form_snapshot(
        "tdc_data_model",
        generate_tdc_rows(),
        snapshot_at=now_iso,
        source_run_id=101,
        source="TDC 自动化归档任务",
        artifacts=[
            {
                "display_name": "TDC数模设计审核_20260902.xlsx",
                "relative_path": "tdc/data_model/TDC数模设计审核_20260902.xlsx",
                "artifact_type": "official_xlsx",
            }
        ],
    )
    db.publish_deliverable_form_snapshot(tdc_snapshot)
    print("tdc_data_model 快照发布成功！")

    # 2. 注入 aras_ncr_progress 快照
    ncr_snapshot = build_form_snapshot(
        "aras_ncr_progress",
        generate_ncr_progress_rows(),
        snapshot_at=now_iso,
        source_run_id=102,
        source="ARAS 自动化归档任务",
        artifacts=[
            {
                "display_name": "ARAS_NCR进度报表_20260902.xlsx",
                "relative_path": "aras/ncr/ncr_progress_20260902.xlsx",
                "artifact_type": "official_xlsx",
            }
        ],
    )
    db.publish_deliverable_form_snapshot(ncr_snapshot)
    print("aras_ncr_progress 快照发布成功！")


if __name__ == "__main__":
    main()
    publish_sor()


def generate_sor_rows():
    definition = form_definition("tdc_sor")
    headers = definition["headerRows"][0]
    items = [
        ("F999X-SOR-101", "F999X", "定点", "SOR-2026-101", "A版", "前保险杠定点", "27010001", "前保险杠骨架", "张工程", "车身开发部", "车身科", "2026-08-20", "SOR发布", "已完成", ""),
        ("F999X-SOR-102", "F999X", "变更", "SOR-2026-102", "B版", "仪表板变更", "27020002", "仪表板下本体", "李工程", "内饰开发部", "内饰科", "2026-08-01", "SOR评审", "审批中", "王主管"),
        ("F888Y-SOR-103", "F888Y", "定点", "SOR-2026-103", "A版", "副车架定点", "27040004", "副车架总成", "赵工程", "底盘开发部", "底盘科", "2026-07-25", "SOR评审", "审批中", "刘主管"),
        ("E50-SOR-104", "E50", "定点", "SOR-2026-104", "A版", "线束定点", "27050005", "线束支架", "孙工程", "电子电器部", "电子电器科", "2026-08-28", "SOR发布", "已完成", ""),
        ("N300-SOR-105", "N300", "变更", "SOR-2026-105", "C版", "顶盖修改", "27060006", "顶盖外板", "周工程", "车身开发部", "车身科", "2026-08-25", "SOR评审", "审批中", "钱主管"),
    ]
    rows = []
    for item in items:
        vals = [None] * len(headers)
        for label, value in zip(headers, item):
            vals[headers.index(label)] = value
        rows.append({"values": vals, "sheetName": "Sheet1"})
    return rows


def publish_sor():
    from datetime import datetime, timezone
    db = DatabaseManager()
    db.init_database()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = build_form_snapshot(
        "tdc_sor",
        generate_sor_rows(),
        snapshot_at=now_iso,
        source_run_id=103,
        source="TDC 自动化归档任务",
        artifacts=[
            {
                "display_name": "TDC_SOR定点流程_20260906.xlsx",
                "relative_path": "tdc/sor/TDC_SOR定点流程_20260906.xlsx",
                "artifact_type": "official_xlsx",
            }
        ],
    )
    db.publish_deliverable_form_snapshot(snapshot)
    print("tdc_sor 快照发布成功！")
