# -*- coding: utf-8 -*-
"""
services/feishu_imap.py — IMAP 邮件解析器（飞书待办提取）

职责:
    1. 通过 IMAP 协议连接邮箱，拉取飞书发出的待办通知邮件
    2. 解析邮件正文 / HTML 内容，提取任务标题、指派人、截止时间等字段
    3. 将解析结果存入 SQLite 的 feishu_tasks 表

设计要点:
    - 完全离线运行 — 仅需 IMAP 端口连通，无需飞书开放平台 API
    - 使用 Python 标准库 imaplib + email，零额外依赖
    - 邮箱凭据通过终端交互式输入，不硬编码在代码中
    - 解析逻辑基于正则匹配飞书邮件模板，可按需扩展

依赖:
    - Python 标准库 (imaplib, email, re)
    - rich (终端交互)
    - core.db_manager (数据持久化)
"""

import re
import imaplib
import email
import email.header
import logging
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt

from core.db_manager import DatabaseManager

logger = logging.getLogger("vse_toolbox.feishu_imap")
console = Console()

# ── 默认 IMAP 配置 ─────────────────────────────────────────────
# 使用者需根据实际邮箱服务商修改
DEFAULT_IMAP_HOST = "imap.example.com"
DEFAULT_IMAP_PORT = 993
DEFAULT_MAILBOX = "INBOX"

# ── 飞书邮件特征 ───────────────────────────────────────────────
# 用于识别飞书发出的待办通知邮件
FEISHU_SENDER_PATTERN = re.compile(
    r"feishu|飞书|lark", re.IGNORECASE
)

# 飞书待办邮件正文中的字段提取正则
# 注意: 以下正则需根据实际飞书邮件模板调整
TASK_TITLE_PATTERN = re.compile(
    r"(?:任务标题|待办事项)[：:]\s*(.+?)(?:\n|$)", re.MULTILINE
)
TASK_ASSIGNEE_PATTERN = re.compile(
    r"(?:指派给|负责人)[：:]\s*(.+?)(?:\n|$)", re.MULTILINE
)
TASK_DEADLINE_PATTERN = re.compile(
    r"(?:截止时间|截止日期|deadline)[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2})?)",
    re.IGNORECASE,
)


class FeishuImapParser:
    """
    飞书 IMAP 邮件解析器

    工作流程:
        1. 交互式获取邮箱凭据
        2. IMAP SSL 连接 → 选择收件箱
        3. 搜索来自飞书的未读邮件
        4. 逐封解析邮件正文，提取待办字段
        5. 写入 SQLite 并标记邮件为已读

    用法:
        parser = FeishuImapParser(db_manager)
        count = parser.scan_and_parse()
    """

    def __init__(
        self,
        db: DatabaseManager,
        imap_host: str = DEFAULT_IMAP_HOST,
        imap_port: int = DEFAULT_IMAP_PORT,
    ) -> None:
        """
        初始化 IMAP 解析器。

        Args:
            db: 数据库管理器实例
            imap_host: IMAP 服务器地址
            imap_port: IMAP SSL 端口
        """
        self._db = db
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    def _get_credentials(self) -> tuple[str, str]:
        """
        通过终端交互获取邮箱地址和密码 / 应用专用密码。

        Returns:
            (邮箱地址, 密码) 元组
        """
        console.print("\n[bold cyan]邮箱登录[/]")
        console.print(f"[dim]IMAP 服务器: {self._imap_host}:{self._imap_port}[/]")

        username = Prompt.ask("[bold]请输入邮箱地址[/]")
        # 使用普通 Prompt 而非 Password，因为部分终端不支持隐藏输入
        # 生产环境建议替换为 getpass.getpass()
        password = Prompt.ask("[bold]请输入邮箱密码 / 应用专用密码[/]")

        return username, password

    def _connect(self, username: str, password: str) -> None:
        """
        建立 IMAP SSL 连接并登录。

        Args:
            username: 邮箱地址
            password: 密码

        Raises:
            ConnectionError: 连接或认证失败
        """
        try:
            console.print("[dim]正在连接 IMAP 服务器...[/]")
            self._conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            self._conn.login(username, password)
            console.print("[green]✓ IMAP 连接成功[/]")
            logger.info("IMAP 连接成功: %s@%s", username, self._imap_host)

        except imaplib.IMAP4.error as e:
            error_msg = f"IMAP 认证失败: {e}"
            console.print(f"[red]错误: {error_msg}[/]")
            logger.error(error_msg)
            raise ConnectionError(error_msg) from e

        except OSError as e:
            error_msg = f"IMAP 网络连接失败: {e}"
            console.print(f"[red]错误: {error_msg}[/]")
            logger.error(error_msg)
            raise ConnectionError(error_msg) from e

    def _disconnect(self) -> None:
        """安全断开 IMAP 连接"""
        if self._conn:
            try:
                self._conn.logout()
                logger.info("IMAP 连接已断开")
            except Exception:
                # logout 可能因连接已断开而失败，忽略
                pass
            finally:
                self._conn = None

    def _decode_header(self, raw_header: str) -> str:
        """
        解码邮件头部字段（支持 RFC 2047 编码）。

        Args:
            raw_header: 原始邮件头部值

        Returns:
            解码后的 Unicode 字符串
        """
        if not raw_header:
            return ""
        try:
            decoded_parts = email.header.decode_header(raw_header)
            result_parts: list[str] = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    result_parts.append(part.decode(charset or "utf-8", errors="replace"))
                else:
                    result_parts.append(str(part))
            return "".join(result_parts)
        except Exception as e:
            logger.warning("邮件头部解码失败: %s", e)
            return str(raw_header)

    def _get_email_body(self, msg: email.message.Message) -> str:
        """
        提取邮件正文（优先纯文本，其次 HTML 去标签）。

        Args:
            msg: email.message.Message 对象

        Returns:
            邮件正文纯文本
        """
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                elif content_type == "text/html" and not body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        # 简单去除 HTML 标签
                        body = re.sub(r"<[^>]+>", "", html)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")

        return body.strip()

    def _is_feishu_email(self, msg: email.message.Message) -> bool:
        """
        判断邮件是否来自飞书。

        Args:
            msg: 邮件消息对象

        Returns:
            True 如果是飞书发出的邮件
        """
        sender = self._decode_header(msg.get("From", ""))
        subject = self._decode_header(msg.get("Subject", ""))
        return bool(FEISHU_SENDER_PATTERN.search(sender) or FEISHU_SENDER_PATTERN.search(subject))

    def _parse_task_from_body(self, body: str, email_id: str) -> Optional[dict]:
        """
        从邮件正文解析出待办任务字段。

        Args:
            body: 邮件正文纯文本
            email_id: 邮件 Message-ID

        Returns:
            解析到的任务 dict，解析失败返回 None
        """
        title_match = TASK_TITLE_PATTERN.search(body)
        if not title_match:
            logger.debug("邮件 %s 中未找到任务标题，跳过", email_id)
            return None

        title = title_match.group(1).strip()
        assignee_match = TASK_ASSIGNEE_PATTERN.search(body)
        deadline_match = TASK_DEADLINE_PATTERN.search(body)

        return {
            "title": title,
            "assignee": assignee_match.group(1).strip() if assignee_match else "",
            "deadline": deadline_match.group(1).strip() if deadline_match else "",
            "source_email_id": email_id,
        }

    def _save_tasks(self, tasks: list[dict]) -> int:
        """
        将解析到的任务批量写入 SQLite。

        Args:
            tasks: 任务字典列表

        Returns:
            成功写入的记录数
        """
        if not tasks:
            return 0

        saved_count = 0
        try:
            with self._db.get_connection() as conn:
                for task in tasks:
                    # 检查是否已存在（基于 source_email_id 去重）
                    existing = conn.execute(
                        "SELECT id FROM feishu_tasks WHERE source_email_id=?",
                        (task["source_email_id"],),
                    ).fetchone()

                    if existing:
                        logger.debug("邮件 %s 已解析过，跳过", task["source_email_id"])
                        continue

                    conn.execute(
                        """
                        INSERT INTO feishu_tasks (title, assignee, deadline, source_email_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            task["title"],
                            task["assignee"],
                            task["deadline"],
                            task["source_email_id"],
                        ),
                    )
                    saved_count += 1

                conn.commit()

            logger.info("飞书待办入库 %d 条", saved_count)

        except Exception as e:
            console.print(f"[red]错误: 任务入库失败 — {e}[/]")
            logger.exception("飞书待办入库失败")
            raise

        return saved_count

    def scan_and_parse(self) -> int:
        """
        执行完整的邮件扫描与解析流程。

        Returns:
            成功解析并入库的任务数量
        """
        console.print("\n[bold cyan]═══ 扫描飞书待办邮件 ═══[/]\n")

        # 步骤 1: 获取凭据
        username, password = self._get_credentials()

        try:
            # 步骤 2: 连接
            self._connect(username, password)

            # 步骤 3: 选择收件箱
            self._conn.select(DEFAULT_MAILBOX, readonly=False)

            # 步骤 4: 搜索未读邮件
            console.print("[dim]搜索未读邮件...[/]")
            status, message_ids = self._conn.search(None, "UNSEEN")

            if status != "OK" or not message_ids[0]:
                console.print("[yellow]未找到未读邮件[/]")
                return 0

            ids = message_ids[0].split()
            console.print(f"[dim]找到 {len(ids)} 封未读邮件[/]")

            # 步骤 5: 逐封解析
            tasks: list[dict] = []
            for mid in ids:
                try:
                    status, data = self._conn.fetch(mid, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # 仅处理飞书邮件
                    if not self._is_feishu_email(msg):
                        continue

                    email_id = msg.get("Message-ID", str(mid))
                    body = self._get_email_body(msg)

                    task = self._parse_task_from_body(body, email_id)
                    if task:
                        tasks.append(task)
                        console.print(f"  [green]✓[/] {task['title']}")

                except Exception as e:
                    logger.warning("解析邮件 %s 时出错: %s", mid, e)
                    continue

            # 步骤 6: 写入数据库
            saved_count = self._save_tasks(tasks)
            console.print(f"\n[green]✓ 本次解析 {len(tasks)} 条，入库 {saved_count} 条新任务[/]")

            return saved_count

        except ConnectionError:
            # 已在 _connect 中处理过错误提示
            return 0

        except Exception as e:
            console.print(f"[red]错误: 邮件扫描异常 — {e}[/]")
            logger.exception("邮件扫描异常")
            return 0

        finally:
            self._disconnect()


# ── 独立运行测试入口 ────────────────────────────────────────────
if __name__ == "__main__":
    console.print("[bold cyan]FeishuImapParser 独立测试[/]\n")

    test_db = DatabaseManager()
    test_db.init_database()

    parser = FeishuImapParser(test_db)
    count = parser.scan_and_parse()
    console.print(f"\n解析结果: {count} 条任务入库")
