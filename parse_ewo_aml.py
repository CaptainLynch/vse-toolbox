import xml.etree.ElementTree as ET
import json

def parse_ewo_aml(file_path):
    print(f"正在解析 Aras AML 响应: {file_path}")
    tree = ET.parse(file_path)
    root = tree.getroot()
    
    # 查找所有的 Item 节点
    items = root.findall(".//Item[@type='EWO_O']")
    
    parsed_data = []
    for item in items:
        ewo_no_elem = item.find("_no") # 有时叫 _no，有时叫 _ewo_no
        if ewo_no_elem is None:
            ewo_no_elem = item.find("keyed_name") # EWO 的 keyed_name 通常就是编号
            
        ewo_no = ewo_no_elem.text if ewo_no_elem is not None else "未知"
        
        state_elem = item.find("state")
        state = state_elem.text if state_elem is not None else ""
        
        subject_elem = item.find("_subject")
        subject = subject_elem.text if subject_elem is not None else ""
        
        created_on_elem = item.find("created_on")
        created_on = created_on_elem.text if created_on_elem is not None else ""
        
        model_elem = item.find("_modelinfo")
        model = model_elem.text if model_elem is not None else ""
        
        parsed_data.append({
            "ewo_no": ewo_no,
            "state": state,
            "subject": subject,
            "created_on": created_on,
            "model": model
        })
        
    print(f"成功解析了 {len(parsed_data)} 条 EWO 数据！")
    print("前 3 条数据预览:")
    print(json.dumps(parsed_data[:3], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    parse_ewo_aml("ewo_response.xml")
