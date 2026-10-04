# -*- coding: utf-8 -*-
"""签署日报 v2.0 邮件正文：三图一表的 HTML、纯文本、收件人与 .eml 草稿（纯函数）。

- 正文顺序固定：汇总数字、图1 外区域会签欠账、图2 内部科室会签欠账、图3 审批欠账、
  在途流程明细表（§6）。图片位用 ``cid:sd-<图>``：.eml 里按 Content-ID 内嵌，
  预览和「复制正文」时前端把它换成同一张 PNG 的 data URI，三处必然一致。
- 表格只用 ``<table>``、行内样式和 bgcolor，固定像素宽度（§10 复制富文本）。
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
from datetime import datetime
from email.utils import getaddresses
from typing import Any, Mapping, Sequence

CHARTS = (
    ("external", "图1 外区域会签欠账"),
    ("sections", "图2 内部科室会签欠账"),
    ("approval", "图3 审批欠账"),
)
CHART_WIDTH = 720
CHART_CAPTION = "柱高 = 当前待办的在途 3D单份数"
EMPTY_CHART = "本阶段无未签"
NO_FLOWS = "无在途流程"
STALL_PLACEHOLDER = "未填写原因"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_FONT = "font-family:'Microsoft YaHei','PingFang SC','Source Han Sans SC',sans-serif;font-size:14px;color:#1f2329;"
_TH = "border:1px solid #c9cdd4;padding:4px 6px;text-align:left;white-space:nowrap;font-weight:bold;"
_TD = "border:1px solid #c9cdd4;padding:4px 6px;vertical-align:top;"
_TH_BG = "#f2f3f5"
_WARN_BG = "#fff3c4"
_OVERDUE_BG = "#ffd6d6"
_RED = "#d83931"
_TABLE_HEADERS = (
    "序号", "流水单号", "零件名称", "归属科室", "申请人", "当前阶段", "当前待办人",
    "会签签单率", "总签单率", "已申请天数", "停滞原因",
)


def chart_cid(key: str) -> str:
    return f"sd-{key}"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _paragraphs(text: Any) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


_URL = re.compile(r"https?://[^\s<>\"']+")


def _link_html(text: str) -> str:
    """在原文上识别链接（含多个查询参数的 &），再逐段转义。"""
    out, last = [], 0
    for match in _URL.finditer(text):
        url = match.group(0)
        out.append(_e(text[last:match.start()]))
        out.append(f'<a href="{html.escape(url, quote=True)}">{_e(url)}</a>')
        last = match.end()
    out.append(_e(text[last:]))
    return "".join(out)


def day_level(days: Any, thresholds: Mapping[str, Any]) -> str:
    """已申请天数着色：overdue（浅红底红色粗体）、warn（浅黄底）、空串。"""
    if not isinstance(days, int):
        return ""
    if days >= int(thresholds.get("overdueDays") or 14):
        return "overdue"
    if days >= int(thresholds.get("warnDays") or 7):
        return "warn"
    return ""


def todo_html(row: Mapping[str, Any]) -> str:
    """当前待办人：外区域的人加粗；加签人标「加签」；末尾「另 n 人未流转到」。"""
    items = []
    for item in row.get("todo") or []:
        if item.get("addSign"):
            area = f"·{item['area']}" if item.get("area") else ""
            items.append(f"{_e(item['name'])}（加签{_e(area)}）")
        else:
            text = f"{_e(item['name'])}（{_e(item.get('area'))}）"
            items.append(f"<b>{text}</b>" if item.get("external") else text)
    out = "、".join(items) or "—"
    if row.get("notRouted"):
        out += f"，另 {int(row['notRouted'])} 人未流转到"
    return out


def _ratio(pair: Sequence[int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def _table_html(rows: Sequence[Mapping[str, Any]], thresholds: Mapping[str, Any]) -> str:
    if not rows:
        return f"<p>{NO_FLOWS}</p>"
    head = "".join(f'<th bgcolor="{_TH_BG}" style="{_TH}background:{_TH_BG};">{_e(h)}</th>' for h in _TABLE_HEADERS)
    body = []
    for index, row in enumerate(rows, start=1):
        level = day_level(row.get("days"), thresholds)
        days = "—" if row.get("days") is None else str(row["days"])
        if level == "overdue":
            days_cell = (f'<td bgcolor="{_OVERDUE_BG}" style="{_TD}background:{_OVERDUE_BG};color:{_RED};'
                         f'font-weight:bold;">{_e(days)}</td>')
        elif level == "warn":
            days_cell = f'<td bgcolor="{_WARN_BG}" style="{_TD}background:{_WARN_BG};">{_e(days)}</td>'
        else:
            days_cell = f'<td style="{_TD}">{_e(days)}</td>'
        cells = [
            f'<td style="{_TD}">{index}</td>',
            f'<td style="{_TD}white-space:nowrap;">{_e(row["serial"])}</td>',
            f'<td style="{_TD}">{_e(row["partLabel"])}</td>',
            f'<td style="{_TD}white-space:nowrap;">{_e(row["department"])}</td>',
            f'<td style="{_TD}white-space:nowrap;">{_e(row["applicant"])}</td>',
            f'<td style="{_TD}white-space:nowrap;">{_e(row["stage"])}</td>',
            f'<td style="{_TD}">{todo_html(row)}</td>',
            f'<td style="{_TD}white-space:nowrap;">{_ratio(row["countersign"])}</td>',
            f'<td style="{_TD}white-space:nowrap;">{_ratio(row["total"])}</td>',
            days_cell,
            f'<td style="{_TD}color:{_RED};">{STALL_PLACEHOLDER}</td>',
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<table cellpadding="0" cellspacing="0" border="1" width="1100" '
        f'style="border-collapse:collapse;width:1100px;{_FONT}"><tr>{head}</tr>' + "".join(body) + "</table>"
    )


def _chart_html(key: str, title: str, groups: Sequence[Any], data_time: str) -> str:
    out = [f"<p><b>{_e(title)}</b></p>"]
    if not groups:
        out.append(f"<p>{EMPTY_CHART}</p>")
        return "".join(out)
    out.append(
        f'<p><img src="cid:{chart_cid(key)}" width="{CHART_WIDTH}" alt="{_e(title)}" '
        f'style="display:block;border:0;width:{CHART_WIDTH}px;max-width:100%;"></p>'
    )
    out.append(f'<p style="color:#646a73;font-size:12px;">数据时间：{_e(data_time)}；{CHART_CAPTION}</p>')
    return "".join(out)


def chart_keys_with_data(report: Mapping[str, Any]) -> list[str]:
    return [key for key, _ in CHARTS if report["charts"].get(key)]


def render_html(report: Mapping[str, Any], texts: Mapping[str, Any], thresholds: Mapping[str, Any]) -> str:
    data_time = format_data_time(report)
    parts = [f'<div style="{_FONT}line-height:1.7;">', f"<p>{_e(texts.get('greeting') or '各位领导、同事：')}</p>"]
    parts.append("<p>" + "<br>".join(_e(line) for line in report["summaryLines"]) + "</p>")
    for line in _paragraphs(texts.get("planText")):
        parts.append(f"<p>{_e(line)}</p>")
    for line in _paragraphs(texts.get("feishuLink")):
        parts.append(f"<p>{_link_html(line)}</p>")
    for key, title in CHARTS:
        parts.append(_chart_html(key, title, report["charts"].get(key) or [], data_time))
    parts.append("<p><b>在途流程签署明细</b></p>")
    parts.append(_table_html(report["flows"], thresholds))
    parts.append("</div>")
    return "".join(parts)


def render_text(report: Mapping[str, Any], texts: Mapping[str, Any]) -> str:
    """纯文本：汇总数字和制表符分隔的明细表，供不认富文本的输入框使用。"""
    out = [str(texts.get("greeting") or "各位领导、同事："), *report["summaryLines"]]
    out += _paragraphs(texts.get("planText")) + _paragraphs(texts.get("feishuLink"))
    for key, title in CHARTS:
        groups = report["charts"].get(key) or []
        if not groups:
            out.append(f"{title}：{EMPTY_CHART}")
            continue
        out.append(f"{title}：")
        for group in groups:
            people = "、".join(f"{bar['label']}{bar['count']}" for bar in group["bars"])
            out.append(f"  {group['group']}（{group['personTimes']} 人次 / {group['flows']} 份 / {group['people']} 人）：{people}")
    out.append("在途流程签署明细：")
    if not report["flows"]:
        out.append(NO_FLOWS)
    else:
        out.append("\t".join(_TABLE_HEADERS))
        for index, row in enumerate(report["flows"], start=1):
            todo = re.sub(r"</?b>", "", todo_html(row))
            out.append("\t".join([
                str(index), row["serial"], row["partLabel"], row["department"], row["applicant"], row["stage"],
                html.unescape(todo), _ratio(row["countersign"]), _ratio(row["total"]),
                "—" if row.get("days") is None else str(row["days"]), STALL_PLACEHOLDER,
            ]))
    return "\n".join(out) + "\n"


def format_data_time(report: Mapping[str, Any]) -> str:
    """抓取时间按本机时区显示到分钟（与数据日期同一时区）；解析不了就显示数据日期。"""
    text = str(report.get("snapshotAt") or "")
    try:
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return str(report.get("dataDate") or "")
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


# ── 收件人（§8）──────────────────────────────────────────────────────


def parse_addresses(text: Any) -> list[tuple[str, str]]:
    """'"张三"<a@x.com>; 李四 <b@x.com>' -> [(姓名, 邮箱)]，按邮箱去重。"""
    raw = re.sub(r"[;；\n\r]+", ",", str(text or ""))
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, address in getaddresses([raw]):
        address = address.strip()
        if "@" not in address or address.lower() in seen:
            continue
        seen.add(address.lower())
        result.append((name.strip().strip('"'), address))
    return result


def owed_names(report: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for key, _ in CHARTS:
        for group in report["charts"].get(key) or []:
            for bar in group["bars"]:
                if bar["name"] not in names:
                    names.append(bar["name"])
    return names


def recipients(to_text: Any, cc_text: Any, address_book: Any, owed: Sequence[str]) -> dict[str, Any]:
    """收件人 = 固定名单 + 当天有欠账且在通讯录里的人。通讯录同名多个邮箱不自动加，列为待选；
    有欠账但通讯录里没有的人在导出前列出。"""
    to = parse_addresses(to_text)
    cc = parse_addresses(cc_text)
    listed = {address.lower() for _, address in to + cc}
    book: dict[str, list[str]] = {}
    for name, address in parse_addresses(address_book):
        if name:
            book.setdefault(name, [])
            if address.lower() not in {a.lower() for a in book[name]}:
                book[name].append(address)
    added, missing, ambiguous = [], [], []
    for name in owed:
        addresses = book.get(name) or []
        if not addresses:
            missing.append(name)
        elif len(addresses) > 1:
            ambiguous.append({"name": name, "addresses": addresses})
        elif addresses[0].lower() not in listed:
            listed.add(addresses[0].lower())
            added.append((name, addresses[0]))
    return {"to": to + added, "cc": cc, "added": added, "missing": missing, "ambiguous": ambiguous}


# ── .eml 草稿（§10）──────────────────────────────────────────────────


class ImageError(ValueError):
    pass


def decode_png(value: Any) -> bytes:
    """前端传来的 base64 PNG（可带 data URI 前缀）-> 字节；只接受真 PNG，限制大小。"""
    if not isinstance(value, str):
        raise ImageError("图片必须是 base64 文本")
    text = value.split(",", 1)[1] if value.startswith("data:") else value
    if len(text) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        raise ImageError("图片过大")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("图片不是有效的 base64") from None
    if not data.startswith(_PNG_SIGNATURE):
        raise ImageError("图片必须是 PNG")
    return data


def _address(name: str, address: str) -> Address:
    local, _, domain = address.rpartition("@")
    return Address(display_name=name or "", username=local, domain=domain)


def build_eml(
    *,
    subject: str,
    to: Sequence[tuple[str, str]],
    cc: Sequence[tuple[str, str]],
    text_body: str,
    html_body: str,
    images: Mapping[str, bytes],
) -> bytes:
    """multipart/related 里放 multipart/alternative（纯文本、HTML）和 PNG（Content-ID、inline）。

    主题和地址里的中文按 RFC 2047 编码；正文 base64、CRLF 换行；X-Unsent: 1 让经典版 Outlook 当草稿打开。
    """
    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    if to:
        message["To"] = [_address(name, address) for name, address in to]
    if cc:
        message["Cc"] = [_address(name, address) for name, address in cc]
    message["X-Unsent"] = "1"
    body = message if not images else EmailMessage(policy=SMTP)
    body.set_content(text_body, cte="base64")
    body.add_alternative(f"<html><body>{html_body}</body></html>", subtype="html", cte="base64")
    if images:
        message.make_related()
        del body["MIME-Version"]
        message.attach(body)
        for key, data in images.items():
            message.add_related(
                data, maintype="image", subtype="png", cid=f"<{chart_cid(key)}>",
                disposition="inline", filename=f"{chart_cid(key)}.png",
            )
    return message.as_bytes()
