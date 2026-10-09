# -*- coding: utf-8 -*-
"""One scheduled TIR数据简表 export pass (for Windows Task Scheduler).

Usage::

    python tools/tir_export_cli.py --once

参照「自动归档」（``main.py scheduled-archive --once`` + ``tools/install_scheduled_archive_task.ps1``）：
计划任务以当前 Windows 用户每小时调用一次；是否导出由插件页面的「自动导出」开关与时间决定
（``plugins.tir_report.service.auto_decision``），当天已有结果就跳过，登录类失败当天不再重试。
账号是统一域账号（``data/domain-credential.dpapi``，DPAPI，仅当前 Windows 用户可解密）。
不启动 Flask；只读数据库里的归档根目录设置（``archiveDirectory``），产物与页面导出、与「自动归档」的
其他交付物写在同一归档根目录、同一格式（``<根>/finereport/tir_brief/<日期>/<运行号>/TIR数据简表.xlsx``）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.db_common import DEFAULT_DB_PATH  # noqa: E402
from core.domain_identity import DPAPICredentialProvider, WindowsDPAPICredentialVault  # noqa: E402
from core.runtime_paths import app_root  # noqa: E402
from plugins.tir_report import service as S  # noqa: E402

PLUGIN_ID = "tir-report"

EXIT_OK = 0
EXIT_FAILED = 1


def plugin_data_dir() -> Path:
    # 与 HostContext.plugin_data_dir 一致：<数据库目录>/plugins/<插件 id>
    path = Path(DEFAULT_DB_PATH).parent / "plugins" / PLUGIN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def domain_provider() -> DPAPICredentialProvider:
    # 与 web/app.py 创建的宿主域账号库同一文件
    return DPAPICredentialProvider(WindowsDPAPICredentialVault(app_root() / "data" / "domain-credential.dpapi"))


def archive_store():  # type: ignore[no-untyped-def]
    from core.db_manager import DatabaseManager

    settings = DatabaseManager().get_app_settings()
    return S.archive_store(settings.get("archiveDirectory") if isinstance(settings, dict) else None)


def session_factory():  # type: ignore[no-untyped-def]
    from services.windows_http import WinHTTPSession

    return WinHTTPSession(timeout=60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/tir_export_cli.py",
                                     description="执行一次 TIR数据简表 自动导出（适合 Windows Task Scheduler）。")
    parser.add_argument("--once", action="store_true", required=True)
    parser.parse_args(argv)
    result = S.run_auto(plugin_data_dir(), now=datetime.now(), store=archive_store(), credential_provider=domain_provider(),
                        session_factory=session_factory)
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_FAILED if result.get("status") == "failed" else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
