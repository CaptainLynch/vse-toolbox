# -*- coding: utf-8 -*-
"""Phase 0 read-only probe for the FineReport ``TIR数据简表`` export contract.

Usage (Windows, company network)::

    python tools/tir_probe.py --credential-ref <Windows 凭据管理器条目名>
    python tools/tir_probe.py --credential-ref <条目名> --project F610S --department 车体工程 --start 2022-07-11

逐步验证方案 §2 的链路（登录页公钥 → 登录 → 打开报表/sessionID → parameters_d → read_w_content →
check/font → op=export → export_polling），把**脱敏**结论写到 ``.runtime/tir_probe_report.json`` 与
``.runtime/tir_probe.har``。约定同 ``tdc_probe_main.py``：不写库、不落原始数据（不保存 xlsx、不保存
报表内容），只报告魔数、表头是否 50 列一致与行数。凭据只经 Windows 凭据管理器读取，不接受命令行口令。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.credential_provider import CredentialProviderError, WindowsCredentialManagerProvider  # noqa: E402
from plugins.tir_report import protocol as P  # noqa: E402
from plugins.tir_report import service as S  # noqa: E402
from plugins.tir_report.client import FineReportClient, TirError  # noqa: E402
from plugins.tir_report.har import HarLeakError, HarRecorder  # noqa: E402


def probe(args: argparse.Namespace, session=None, provider=None) -> dict:
    from services.windows_http import WinHTTPSession

    filters = P.normalize_filters({"project": args.project, "department": args.department, "section": args.section,
                                   "startDate": args.start, "endDate": args.end}, today=date.today())
    recorder = HarRecorder(session or WinHTTPSession(timeout=60))
    client = FineReportClient(recorder, base_url=args.base_url, on_secret=recorder.register_secret)
    report: dict = {"report": P.REPORT_PATH, "filters": filters.as_payload(), "checks": {}}
    checks = report["checks"]
    provider = provider or WindowsCredentialManagerProvider()
    try:
        with provider.resolve(args.credential_ref) as credential:
            page = client._send("GET", "/login", "login_page", headers={"Accept": "text/html"}, allow_redirects=True)
            checks["R1_public_key_found"] = P.find_public_key(client._text(page)) is not None
            client.login(credential.username, credential.password)
            checks["R1_login"] = "ok"
            checks["R1_encrypted"] = checks["R1_public_key_found"]
            client.open_report()
            checks["R3_session_id_from"] = client.steps[-1]
            client.set_parameters(P.build_parameters(filters))
            checks["R4_parameters_accepted"] = True
            pages = client.read_pages()
            table = P.table_from_pages(pages)
            checks["content_pages"] = len(pages)
            checks["content_rows"] = len(table) - 1
            checks["content_header_ok"] = tuple(table[0]) == P.EXPECTED_HEADERS
            result = client.export_excel(pages)
            checks["R2_export_mode"] = result.mode
            checks["R2_export_is_xlsx"] = P.is_xlsx(result.content)
            checks["R2_header"] = S.header_check(result.content)
    except CredentialProviderError:
        checks["error"] = "credential_unavailable"
    except TirError as exc:
        checks["error"] = exc.code
    report["steps"] = list(client.steps)
    out_dir = REPO_ROOT / ".runtime"
    out_dir.mkdir(exist_ok=True)
    try:
        (out_dir / "tir_probe.har").write_text(recorder.dumps(comment="tir probe redacted"), encoding="utf-8")
        report["har"] = ".runtime/tir_probe.har"
    except HarLeakError:
        report["har"] = "redaction_self_check_failed"
    recorder.clear_secrets()
    (out_dir / "tir_probe_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TIR数据简表 帆软导出契约只读探针（Phase 0）")
    parser.add_argument("--credential-ref", required=True, help="Windows 凭据管理器中的普通凭据条目名")
    parser.add_argument("--base-url", default=P.DEFAULT_BASE_URL)
    parser.add_argument("--project", default=P.DEFAULT_PROJECT)
    parser.add_argument("--department", default=P.DEFAULT_DEPARTMENT)
    parser.add_argument("--section", default="")
    parser.add_argument("--start", default=P.DEFAULT_START_DATE)
    parser.add_argument("--end", default="")
    args = parser.parse_args(argv)
    if not args.base_url.startswith("https://"):
        print("错误：--base-url 必须是 https 地址", file=sys.stderr)
        return 2
    report = probe(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if "error" not in report["checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
