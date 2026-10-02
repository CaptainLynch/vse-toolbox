import sys
import os
from pathlib import Path

# 添加项目根目录到 Python Path，以允许导入 core.db_manager
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

from core.db_manager import DatabaseManager
import pandas as pd

def import_local_excel(file_path: str):
    print(f"正在读取文件: {file_path}")
    # 第一行为标题，第二行为表头(header=1)
    df = pd.read_excel(file_path, header=1)
    
    def map_status(s: str) -> str:
        s = str(s).strip()
        if "关闭" in s or "完成" in s:
            return "done"
        elif "终止" in s or "作废" in s:
            return "blocked"
        elif not s or s == "nan":
            return "pending"
        return "in_progress"
        
    scraped_items = []
    for index, row in df.iterrows():
        # 如果 NCR 编号是空，可能意味着这不是一条有效数据，不过这里用 .get 容错
        scraped_items.append({
            "name": str(row.get('NCR编号', f'Unknown_{index}')), 
            "project_id": str(row.get('项目', '1')),
            "owner": str(row.get('当前审批人', '未知')),
            "status": map_status(row.get('状态', ''))
        })
        
    print(f"成功解析 {len(scraped_items)} 条数据。正在写入数据库...")
    
    db = DatabaseManager()
    db.init_database()
    
    try:
        with db.get_connection() as conn:
            # 建立 project_name -> project_id 的映射
            project_map = {}
            for item in scraped_items:
                proj_name = item.get("project_id")
                if proj_name not in project_map:
                    # 先尝试查找
                    cursor = conn.execute("SELECT id FROM projects WHERE name = ?", (proj_name,))
                    res = cursor.fetchone()
                    if res:
                        project_map[proj_name] = res[0]
                    else:
                        # 不存在则插入
                        cursor = conn.execute("INSERT INTO projects (name, manager) VALUES (?, ?)", (proj_name, "Crawler"))
                        project_map[proj_name] = cursor.lastrowid
                
                # 插入 deliverable
                conn.execute(
                    """
                    INSERT INTO deliverables (project_id, name, owner, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        project_map[proj_name],
                        item.get("name"),
                        item.get("owner"),
                        item.get("status"),
                    ),
                )
            conn.commit()
        print(f"入库成功！共插入 {len(scraped_items)} 条 NCR 数据。")
    except Exception as e:
        print(f"入库失败: {e}")

if __name__ == "__main__":
    file_path = r"E:\project\vse-toolbox\crawl source\NCR审批进度查询表 20260620 003852.775.xlsx"
    import_local_excel(file_path)
