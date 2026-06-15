import win32com.client
import os

def test_excel_com(file_path):
    print(f"正在测试 COM 接口访问 Excel...")
    print(f"目标文件: {file_path}")
    
    excel = None
    wb = None
    try:
        # 启动 Excel 应用程序 (后台静默运行)
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False # 设置为 True 可以看到 Excel 打开的过程，测试时建议设为 True 方便观察
        excel.DisplayAlerts = False

        # 如果文件不存在，先创建一个测试文件
        if not os.path.exists(file_path):
            print("文件不存在，正在创建一个新的测试文件...")
            wb = excel.Workbooks.Add()
            ws = wb.Worksheets(1)
            ws.Cells(1, 1).Value = "项目状态"
            ws.Cells(1, 2).Value = "更新时间"
            ws.Cells(2, 1).Value = "进行中"
            ws.Cells(2, 2).Value = "2024-05-20"
            wb.SaveAs(file_path)
            print("测试文件创建并保存成功。")
            wb.Close(False)
            wb = None
            
        # 打开已存在（或刚创建）的文件
        print("正在打开文件进行读取和修改...")
        wb = excel.Workbooks.Open(file_path)
        ws = wb.Worksheets(1)
        
        # 读取内容
        val1 = ws.Cells(1, 1).Value
        val2 = ws.Cells(2, 1).Value
        print(f"读取到数据: A1='{val1}', A2='{val2}'")
        
        # 修改内容
        ws.Cells(3, 1).Value = "自动化写入测试"
        ws.Cells(3, 2).Value = "成功!"
        
        # 保存并关闭
        wb.Save()
        print("文件修改并保存成功！如果在公司电脑上运行，这证明 COM 接口可以完美绕过透明加密读取和写入文件。")

    except Exception as e:
        print(f"测试失败，出现异常: {e}")
    finally:
        # 清理资源，关闭 Excel 进程
        if wb:
            try:
                wb.Close(False)
            except:
                pass
        if excel:
            try:
                excel.Quit()
            except:
                pass

if __name__ == "__main__":
    # 获取当前目录的绝对路径，确保 COM 能找到文件
    current_dir = os.path.abspath(os.path.dirname(__file__))
    test_file = os.path.join(current_dir, "test_encrypted_excel.xlsx")
    test_excel_com(test_file)
    input("按回车键退出...")
