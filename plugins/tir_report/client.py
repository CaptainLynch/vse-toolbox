# -*- coding: utf-8 -*-
"""FineReport client for the TIR数据简表 export (transport-agnostic, no credential storage).

``session`` 是 requests 风格对象（生产是 ``services.windows_http.WinHTTPSession`` 外包
``HarRecorder``；测试是假会话）。客户端不保存账号口令：``login`` 拿到的明文只在调用栈里使用，
token 与 sessionID 只存在本对象内存，任务结束即丢弃（方案 R1/R3：每次任务重新登录，不做续期）。

已证实的协议（HAR）与待 Phase 0 证实的假设（公钥位置、sessionID 模式、``op=export`` 下载端点）
见 ``docs/TIR_REPORT_PLUGIN_DESIGN_20261009.md``；假设不成立时以闭集错误码失败或走 ``rebuilt`` 退路，
不静默猜测。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from . import protocol as P

_XHR = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"}
_FORM = "application/x-www-form-urlencoded; charset=UTF-8"
_RETRY_DELAYS = (2.0, 4.0)
_MAX_PAGES = 200

#: 闭集错误码 -> 中文处理指引（页面与任务错误信息只用这里的文字，不回显服务器原文）。
REMEDIES = {
    "credential_missing": "请先在本页填写帆软账号在 Windows 凭据管理器中的条目名（credential_ref）",
    "credential_unavailable": "凭据管理器里找不到该条目或条目不完整，请在「Windows 凭据管理器 → 普通凭据」中添加",
    "login_failed": "帆软登录失败：请确认凭据管理器中的账号口令仍然有效",
    "login_unsupported": "帆软登录页的加密方式无法识别（可能启用了滑块或 SM4），请运行 tools/tir_probe.py 取证后反馈",
    "session_not_found": "打开 TIR数据简表 报表失败（找不到报表会话），请确认账号有该报表权限",
    "parameters_rejected": "报表不接受这组查询参数，请检查项目/部门/日期",
    "export_failed": "帆软导出失败，且报表内容无法解析",
    "network_error": "连接帆软报表平台失败，请确认处于公司内网后重试",
    "cancelled": "任务已取消",
}


class TirError(RuntimeError):
    """Closed-set failure; ``str()`` is safe to show and to store in the task row."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code if code in REMEDIES else "export_failed"
        text = REMEDIES[self.code]
        super().__init__(f"{text}（{self.code}{'：' + detail if detail else ''}）")


@dataclass
class ExportResult:
    content: bytes
    mode: str  # "original"（帆软原样导出）或 "rebuilt"（解析 read_w_content 自建）
    rows: int
    headers: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


class FineReportClient:
    def __init__(
        self,
        session: Any,
        *,
        base_url: str = P.DEFAULT_BASE_URL,
        entry_id: str = P.ENTRY_ID,
        sleep: Callable[[float], None] = time.sleep,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        on_secret: Callable[..., None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._entry_id = entry_id
        self._sleep = sleep
        self._clock_ms = clock_ms
        self._on_secret = on_secret or (lambda *values: None)
        self._cancelled = cancelled
        self._session_id: str | None = None
        self.steps: list[str] = []

    # ── 传输 ──────────────────────────────────────────────────────

    def _send(self, method: str, path: str, step: str, *, query=None, data=None, headers=None,
              allow_redirects: bool = False) -> Any:
        if self._cancelled():
            raise TirError("cancelled")
        target = P.url(self._base, path, query)
        merged = {**_XHR, **(headers or {})}
        if self._session_id is not None and path.startswith("/view/report"):
            merged["sessionID"] = self._session_id
        last: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                kwargs: dict[str, Any] = {"headers": merged, "allow_redirects": allow_redirects}
                if data is not None:
                    kwargs["data"] = data
                response = getattr(self._session, method.lower())(target, **kwargs)
                self.steps.append(step)
                return response
            except TirError:
                raise
            except Exception as exc:  # 传输错误：WinHTTPError 等，不带请求数据
                last = exc
                if attempt < len(_RETRY_DELAYS):
                    self._sleep(_RETRY_DELAYS[attempt])
        raise TirError("network_error", type(last).__name__ if last else "")

    @staticmethod
    def _text(response: Any) -> str:
        try:
            return response.text
        except Exception:
            return ""

    # ── 步骤 ──────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> None:
        page = self._send("GET", "/login", "login_page", headers={"Accept": "text/html"}, allow_redirects=True)
        key = P.find_public_key(self._text(page))
        if key is not None:
            try:
                secret = P.encrypt_password(password, key)
            except Exception as exc:
                raise TirError("login_unsupported", "公钥无法使用") from exc
            body = P.login_body(username, secret, encrypted=True)
        else:
            secret = password
            body = P.login_body(username, password, encrypted=False)
        self._on_secret(username, password, secret)
        response = self._send("POST", "/login", "login", data=body.encode("utf-8"),
                              headers={"Content-Type": "application/json;charset=UTF-8"})
        try:
            payload = json.loads(self._text(response) or "null")
        except ValueError:
            payload = None
        if response.status_code != 200 or not isinstance(payload, Mapping):
            raise TirError("login_failed", f"HTTP {response.status_code}")
        try:
            token = P.parse_access_token(payload)
        except P.ProtocolError:
            raise TirError("login_failed", f"错误码 {P.login_error_code(payload)}") from None
        self._on_secret(token)
        # FineReport 前端把 token 写进 fine_auth_token cookie，XHR 另带 Bearer 头；两者都设置。
        self._session.headers["Authorization"] = f"Bearer {token}"
        self._session.set_cookies({"fine_auth_token": token}, self._base + "/")

    def open_report(self) -> str:
        self._session_id = None
        page = self._send("GET", P.entry_access_path(self._entry_id), "entry_access",
                          headers={"Accept": "text/html"}, allow_redirects=True)
        text = self._text(page)
        if P.looks_like_login_page(page.status_code, text):
            raise TirError("session_not_found", "登录态无效")
        try:
            session_id = P.parse_session_id(text)
        except P.ProtocolError:
            viewlet = self._send("GET", "/view/report", "viewlet", query=[("viewlet", P.REPORT_PATH)],
                                 headers={"Accept": "text/html"}, allow_redirects=True)
            try:
                session_id = P.parse_session_id(self._text(viewlet))
            except P.ProtocolError:
                raise TirError("session_not_found") from None
        self._on_secret(session_id)
        self._session_id = session_id
        return session_id

    def set_parameters(self, params: Mapping[str, Any]) -> None:
        response = self._send("POST", "/view/report", "parameters_d", query=P.parameters_query(),
                              data=P.parameters_form(params, self._clock_ms()), headers={"Content-Type": _FORM})
        if not P.parameters_accepted(self._text(response)):
            if P.looks_like_login_page(response.status_code, self._text(response)):
                raise TirError("session_not_found", "登录态无效")
            raise TirError("parameters_rejected", f"HTTP {response.status_code}")

    def read_pages(self) -> list[list[list[str]]]:
        pages = []
        page_no, total = 0, 0
        while True:
            response = self._send("GET", "/view/report", "read_w_content",
                                  query=P.read_content_query(page_no, self._clock_ms()))
            try:
                rows, total = P.parse_content_page(json.loads(self._text(response)))
            except (ValueError, P.ProtocolError):
                raise TirError("export_failed", "报表内容不是预期格式") from None
            pages.append(rows)
            page_no += 1
            # reportTotalPage=0 表示未分页；>1 时按 pn 继续取（Phase 0 需复核分页起点）。
            if total <= 1 or page_no >= min(total, _MAX_PAGES):
                return pages

    def export_excel(self, pages: list[list[list[str]]]) -> ExportResult:
        from .xlsx_writer import build_xlsx

        self._send("POST", "/export/check/font", "check_font", data=P.form_body([("format", "excel")]),
                   headers={"Content-Type": _FORM})
        response = self._send("GET", "/view/report", "export", query=P.export_query(self._session_id or ""),
                              headers={"Accept": "*/*"}, allow_redirects=True)
        content = bytes(getattr(response, "content", b"") or b"")
        self._send("POST", "/view/report", "export_polling", data=P.export_polling_form(self._clock_ms()),
                   headers={"Content-Type": _FORM})
        try:
            table = P.table_from_pages(pages)
        except P.ProtocolError:
            table = []
        if response.status_code == 200 and P.is_xlsx(content):
            return ExportResult(content=content, mode="original", rows=max(len(table) - 1, 0),
                                headers=table[0] if table else [], steps=list(self.steps))
        if not table:
            raise TirError("export_failed", f"HTTP {response.status_code}")
        return ExportResult(content=build_xlsx(table), mode="rebuilt", rows=len(table) - 1,
                            headers=table[0], steps=list(self.steps))

    def run(self, username: str, password: str, params: Mapping[str, Any]) -> ExportResult:
        """login → entry/access → parameters_d → read_w_content → check/font → export → export_polling.

        打开报表或提交参数时发现登录态失效，重登一次再继续（方案 R3）。
        """
        self.login(username, password)
        for attempt in range(2):
            try:
                self.open_report()
                self.set_parameters(params)
                break
            except TirError as exc:
                if exc.code != "session_not_found" or attempt == 1:
                    raise
                self.login(username, password)
        pages = self.read_pages()
        return self.export_excel(pages)
