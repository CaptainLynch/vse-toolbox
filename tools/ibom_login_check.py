"""用真实域账号验证 iBOM 登录与只读接口（双源方案阶段 1 验收）。

在有 Python 的内网电脑、仓库根目录运行::

    python tools/ibom_login_check.py

按提示输入域账号与密码（密码不回显、不写盘、不进日志）。脚本只登录**一次**：
任何一步失败都直接结束，**不会重试密码**（统一身份认证错 3 次锁号）。

验证内容：统一身份认证登录 iBOM → ``checkToken`` → DMM 单据总数 → 导出 DMM 报表（只在内存里，
不落盘）。输出只有各步骤结论、计数与字节数，不含 token、Cookie 或密码；可整段复制交回。
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.ibom_auth import IBOMAuthError, IBOMPasswordAuthClient  # noqa: E402
from services.ibom_client import IBOMClient, IBOMClientError, IBOMToken  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    print("iBOM 登录验证（只尝试一次，失败不重试）")
    username = input("域账号：").strip()
    password = getpass.getpass("密码（不回显）：")
    auth = IBOMPasswordAuthClient()
    try:
        result = auth.login(username, password)
    except IBOMAuthError as exc:
        print(f"[失败] 登录阶段 {exc.stage}，HTTP {exc.status_code}，密码已发送={exc.credentials_sent}")
        print("请勿立即重试；先在浏览器确认账号能正常登录 iBOM。")
        return 1
    finally:
        password = ""
    print(f"[通过] 登录：loginType={result.login_type}，token 长度={len(result.user_token)}")
    client = IBOMClient(result.session, IBOMToken(result.user_token, result.user_login_name, result.login_type))
    try:
        total = client.dmm_total_count()
        print(f"[通过] DMM 单据总数：{total}")
        export = client.export_dmm_report()
        print(f"[通过] 报表导出：{export.byte_count} 字节，文件名 {export.file_name}，类型 {export.content_type}")
    except IBOMClientError as exc:
        print(f"[失败] 接口阶段 {exc.stage}，HTTP {exc.status_code}")
        return 2
    finally:
        close = getattr(result.session, "close", None)
        if callable(close):
            close()
    print("全部通过。请把以上输出整段交回。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
