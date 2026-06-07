import hashlib
import logging
import re
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("VSE_TOOLBOX.feishu")

BASE_DIR = Path(__file__).parent.parent

# 演示模式：为 True 时，飞书抓取失败自动回退到演示数据。
# 部署到公司电脑后设为 False，仅从真实飞书抓取。
DEMO_MODE = True

# 待办提取关键词
TODO_PATTERNS = [
    (re.compile(r"请处理[：:]\s*(.+)"), "action_request"),
    (re.compile(r"请于(\d{4}-\d{2}-\d{2}|\d+月\d+日|\d+\.\d+)前\s*(.+)"), "deadline"),
    (re.compile(r"截止[：:]\s*(.+)"), "deadline"),
    (re.compile(r"[Dd]eadline[：:]\s*(.+)"), "deadline"),
    (re.compile(r"请确认[：:]\s*(.+)"), "confirm"),
    (re.compile(r"需(?:要|求).{0,10}完成[：:]\s*(.+)"), "requirement"),
    (re.compile(r"待办[：:]\s*(.+)"), "todo_marker"),
]

# 演示邮件数据（开发环境使用）
DEMO_MAILS = [
    {
        "id": "demo-mail-001",
        "sender": "李明 - 车身工程部",
        "subject": "【交付物】车身钣金 DV 试验报告",
        "preview": "附件为车身钣金 DV 试验报告，请于2026-06-15前审核完成并反馈意见。",
        "content": "各位同事，\n\n附件为车身钣金 DV 试验报告，请于2026-06-15前审核完成并反馈意见。\n\n如有问题请及时沟通。\n\n谢谢，\n李明",
        "category": "交付物",
        "is_read": False,
        "is_starred": True,
        "has_attachment": True,
    },
    {
        "id": "demo-mail-002",
        "sender": "王芳 - 底盘工程部",
        "subject": "【问题跟踪】制动盘磨损传感器误报",
        "preview": "针对上周发现的制动盘磨损传感器误报问题，请处理：更新传感器校准参数并验证。",
        "content": "针对上周发现的制动盘磨损传感器误报问题，\n\n请处理：更新传感器校准参数并在本周五前完成验证。\n\n当前状态：P1，正在分析中。\n\n王芳",
        "category": "问题跟踪",
        "is_read": False,
        "is_starred": False,
        "has_attachment": False,
    },
    {
        "id": "demo-mail-003",
        "sender": "张伟 - 动力总成部",
        "subject": "【同步】发动机台架试验进展",
        "preview": "发动机台架试验已完成 75%，预计下周三完成全部测试。",
        "content": "各位，\n\n同步一下发动机台架试验进展：\n- 已完成 75% 测试项\n- 预计下周三完成全部测试\n- 目前无重大异常\n\n张伟",
        "category": "进度同步",
        "is_read": True,
        "is_starred": False,
        "has_attachment": False,
    },
    {
        "id": "demo-mail-004",
        "sender": "赵宇 - 车身工程部",
        "subject": "【紧急】车门密封条漏水问题",
        "preview": "请确认：洗车测试中左后门密封条漏水，需立即更换密封条并重新测试。",
        "content": "请确认：洗车测试中左后门密封条漏水，需立即更换密封条并重新测试。\n\n截止：本周五下班前。\n\n赵宇",
        "category": "问题跟踪",
        "is_read": False,
        "is_starred": True,
        "has_attachment": True,
    },
    {
        "id": "demo-mail-005",
        "sender": "刘洋 - EE 部门",
        "subject": "【通知】INFOTAINMENT 软件版本更新",
        "preview": "INFOTAINMENT 系统已更新至 v3.2.1，请各相关人员更新测试环境。",
        "content": "INFOTAINMENT 系统已更新至 v3.2.1，请各相关人员更新测试环境。\n\nRelease Notes 详见附件。\n\n刘洋",
        "category": "通知",
        "is_read": True,
        "is_starred": False,
        "has_attachment": True,
    },
]


class FeishuService:
    """飞书集成服务。使用 Edge WebDriver 访问飞书，抓取邮件并提取待办事项。"""

    @staticmethod
    def sync_mails() -> dict:
        """同步飞书邮件到本地 SQLite 缓存。

        尝试通过 Edge WebDriver 抓取飞书邮件。
        如果 WebDriver 不可用且 DEMO_MODE=True，使用演示数据。
        """
        from services.db import DBManager

        mails = []
        is_demo = False
        try:
            mails = FeishuService._scrape_mails()
            logger.info("Scraped %d mails from Feishu", len(mails))
        except Exception as e:
            if DEMO_MODE:
                logger.warning("Feishu scrape failed, falling back to demo data: %s", e)
                mails = FeishuService._demo_mails()
                is_demo = True
            else:
                logger.error("Feishu scrape failed and DEMO_MODE is off: %s", e)
                return {"synced_count": 0, "new_count": 0, "demo": False}

        if not mails:
            return {"synced_count": 0, "new_count": 0, "demo": is_demo}

        total, new_count = DBManager.save_mails(mails)
        logger.info("Mail sync done: total=%d, new=%d", total, new_count)

        # 从新邮件中提取待办
        todos = FeishuService.extract_todos(mails)
        if todos:
            DBManager.save_todos(todos)
            logger.info("Extracted %d todos from mails", len(todos))

        return {"synced_count": total, "new_count": new_count, "demo": is_demo}

    @staticmethod
    def extract_todos(mails: list[dict]) -> list[dict]:
        """从邮件内容中提取待办事项。"""
        todos = []
        now = datetime.now().isoformat()

        for mail in mails:
            text = " ".join(filter(None, [
                mail.get("subject", ""),
                mail.get("preview", ""),
                mail.get("content", ""),
            ]))

            for pattern, todo_type in TODO_PATTERNS:
                matches = pattern.findall(text)
                for match in matches:
                    if isinstance(match, tuple):
                        content = " ".join(filter(None, match))
                    else:
                        content = match

                    content = content.strip()
                    if len(content) < 5:
                        continue

                    todo_id = hashlib.md5(
                        f"{mail['id']}:{content}".encode()
                    ).hexdigest()[:12]
                    todo_id = f"TODO-{todo_id}"

                    deadline = FeishuService._extract_deadline(content)

                    todos.append({
                        "id": todo_id,
                        "content": content[:200],
                        "source": f"{mail.get('sender', 'Unknown')} - {mail.get('subject', '')}",
                        "deadline": deadline,
                        "completed": False,
                        "created_at": now,
                    })
                    break  # 每封邮件只提取最匹配的一条待办

        return todos

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _scrape_mails() -> list[dict]:
        """通过 Edge WebDriver 抓取飞书邮件列表。"""
        from services.crawler_service import get_driver_manager

        driver_manager = get_driver_manager()
        driver = driver_manager.get("https://feishu.cn/mail")

        try:
            driver.get("https://feishu.cn/mail")
            time.sleep(3)

            from selenium.webdriver.common.by import By

            mails = []
            mail_items = driver.find_elements(By.CSS_SELECTOR, "[data-mail-id], .mail-item, .email-item")

            for item in mail_items[:50]:
                try:
                    mail_id = item.get_attribute("data-mail-id") or hashlib.md5(
                        item.text.encode()
                    ).hexdigest()[:16]

                    sender_el = item.find_elements(By.CSS_SELECTOR, ".sender, .from, [class*='sender']")
                    subject_el = item.find_elements(By.CSS_SELECTOR, ".subject, .title, [class*='subject']")
                    preview_el = item.find_elements(By.CSS_SELECTOR, ".preview, .summary, [class*='preview']")

                    mail = {
                        "id": mail_id,
                        "sender": sender_el[0].text.strip() if sender_el else "Unknown",
                        "subject": subject_el[0].text.strip() if subject_el else "(No Subject)",
                        "preview": preview_el[0].text.strip() if preview_el else "",
                        "content": "",
                        "category": None,
                        "is_read": False,
                        "is_starred": False,
                        "has_attachment": False,
                        "received_at": datetime.now().isoformat(),
                    }
                    mails.append(mail)
                except Exception:
                    continue

            return mails
        finally:
            pass

    @staticmethod
    def _demo_mails() -> list[dict]:
        """生成带时间戳的演示邮件数据。"""
        now = datetime.now()
        mails = []
        for i, mail in enumerate(DEMO_MAILS):
            m = dict(mail)
            m["received_at"] = now.replace(
                hour=max(0, 9 + i), minute=(i * 17) % 60
            ).isoformat()
            mails.append(m)
        return mails

    @staticmethod
    def _extract_deadline(text: str) -> str | None:
        """从文本中提取截止日期。"""
        date_patterns = [
            (re.compile(r"(\d{4}-\d{2}-\d{2})"), "%Y-%m-%d"),
            (re.compile(r"(\d+)月(\d+)日"), None),  # 中文日期
            (re.compile(r"(\d+)\.(\d+)"), None),
        ]

        for pattern, fmt in date_patterns:
            match = pattern.search(text)
            if match:
                if fmt == "%Y-%m-%d":
                    return match.group(1)
                elif len(match.groups()) == 2:
                    now = datetime.now()
                    month = int(match.group(1))
                    day = int(match.group(2))
                    try:
                        return datetime(now.year, month, day).strftime("%Y-%m-%d")
                    except ValueError:
                        continue

        # 中文相对日期
        if re.search(r"今天|今日", text):
            return datetime.now().strftime("%Y-%m-%d")
        if re.search(r"明天|明日", text):
            from datetime import timedelta
            return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if re.search(r"本周[五六日]|这周[五六日]", text):
            return datetime.now().strftime("%Y-%m-%d")

        return None
