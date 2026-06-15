import imaplib
import email
from email.header import decode_header
import sys

# 【请在这里填入飞书邮箱的 IMAP 凭证】
IMAP_SERVER = "imap.feishu.cn"  # 飞书通常是 imap.feishu.cn
EMAIL_ACCOUNT = "your_email@company.com" # 您的飞书邮箱账号
EMAIL_PASSWORD = "your_app_password" # 飞书邮箱的 IMAP 客户端授权码 (不是登录密码)

def test_imap_connection():
    print(f"正在尝试连接飞书 IMAP 服务器: {IMAP_SERVER} ...")
    try:
        # 连接到服务器
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        print("连接成功！尝试登录...")
        
        # 登录
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        print("登录成功！")

        # 选择收件箱
        mail.select("inbox")
        
        # 搜索最新的一封邮件
        status, messages = mail.search(None, "ALL")
        if status == "OK":
            email_ids = messages[0].split()
            if email_ids:
                latest_email_id = email_ids[-1]
                print(f"找到邮件，正在读取最新一封邮件 (ID: {latest_email_id.decode()})...")
                
                status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        # 解码邮件主题
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding if encoding else "utf-8")
                        
                        # 解码发件人
                        from_ = msg.get("From")
                        
                        print("-" * 30)
                        print(f"最新邮件主题: {subject}")
                        print(f"发件人: {from_}")
                        print("-" * 30)
            else:
                print("收件箱为空。")
                
        mail.logout()
        print("测试完成并成功登出。这意味着您可以自动读取飞书邮件来提取任务和交付物状态了。")

    except imaplib.IMAP4.error as e:
        print(f"IMAP 登录失败，请检查账号密码或授权码。错误信息: {e}")
    except Exception as e:
        print(f"发生其他错误: {e}")

if __name__ == "__main__":
    if EMAIL_ACCOUNT == "your_email@company.com":
        print("请先用文本编辑器打开本文件，填入您的真实飞书邮箱账号和授权码再运行测试！")
        sys.exit(1)
    
    test_imap_connection()
    input("按回车键退出...")
