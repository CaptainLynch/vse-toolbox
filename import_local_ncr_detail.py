import sys
import os
from pathlib import Path
import math

project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

from core.db_manager import DatabaseManager
import pandas as pd

def safe_str(val):
    if pd.isna(val):
        return ""
    return str(val).strip()

def import_detail_excel(file_path: str):
    print(f"正在读取明细文件: {file_path}")
    # 标题行在第一行(header=0)
    df = pd.read_excel(file_path, header=0)
    
    scraped_items = []
    for index, row in df.iterrows():
        ncr_no = safe_str(row.get('NCR编号', ''))
        # 过滤掉表头的冗余行（如车型配置行），真实的 NCR 编号应该包含 "NCR-"
        if not ncr_no or "NCR-" not in ncr_no:
            continue
            
        # 兼容全角半角括号
        cost_change = safe_str(row.get('测算单件成本变化（元）'))
        if not cost_change:
            cost_change = safe_str(row.get('测算单件成本变化(元)'))
            
        scraped_items.append({
            "ncr_name": ncr_no, 
            "project_name": safe_str(row.get('项目')),
            "part_number": safe_str(row.get('零件号')),
            "part_name": safe_str(row.get('零件名称')),
            "change_type": safe_str(row.get('零件更改类型')),
            "quantity": safe_str(row.get('数量')),
            "cost_change": cost_change,
            "pr_number": safe_str(row.get('PR号')),
            "po_number": safe_str(row.get('PO号')),
        })
        
    print(f"成功解析 {len(scraped_items)} 条真实明细数据。正在写入数据库...")
    
    db = DatabaseManager()
    db.init_database()
    
    try:
        with db.get_connection() as conn:
            for item in scraped_items:
                conn.execute(
                    """
                    INSERT INTO ncr_details 
                    (ncr_name, project_name, part_number, part_name, change_type, quantity, cost_change, pr_number, po_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.get("ncr_name"),
                        item.get("project_name"),
                        item.get("part_number"),
                        item.get("part_name"),
                        item.get("change_type"),
                        item.get("quantity"),
                        item.get("cost_change"),
                        item.get("pr_number"),
                        item.get("po_number"),
                    ),
                )
            conn.commit()
        print(f"入库成功！共插入 {len(scraped_items)} 条 NCR 明细数据。")
    except Exception as e:
        print(f"入库失败: {e}")

if __name__ == "__main__":
    file_path = r"E:\project\vse-toolbox\crawl source\NCR审批明细查询表_4a4828eb-6986-43fb-9e7d-027a58747805.xlsx"
    import_detail_excel(file_path)
