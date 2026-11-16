# -*- coding: utf-8 -*-
"""签署日报 v2.0 邮件正文：三图一表的 HTML、纯文本、收件人与 .eml 草稿（纯函数）。

- 正文顺序固定：汇总数字、图1 外区域会签未签单情况、图2 内部科室会签未签单情况、图3 审批未签单情况、
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
from decimal import Decimal, InvalidOperation
from email.utils import getaddresses
from typing import Any, Mapping, Sequence

CHARTS = (
    ("external", "图1 外区域会签未签单情况"),
    ("sections", "图2 内部科室会签未签单情况"),
    ("approval", "图3 审批未签单情况"),
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
    "会签签单率", "已申请天数", "停滞原因",
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


def add_sign_text(area: str) -> str:
    """加签人的标注：区域未知时「加签（区域未知）」本身已含「加签」。"""
    if not area:
        return "加签"
    return area if area.startswith("加签") else f"加签·{area}"


def todo_html(row: Mapping[str, Any]) -> str:
    """当前待办人：外区域的人加粗；加签、退回修改另加标注；末尾「另 n 人未签、非当前待办」。"""
    items = []
    for item in row.get("todo") or []:
        if item.get("addSign"):
            text = f"{_e(item['name'])}（{_e(add_sign_text(item.get('area') or ''))}）"
        elif item.get("returned"):
            text = f"{_e(item['name'])}（退回修改）"
        else:
            text = f"{_e(item['name'])}（{_e(item.get('area'))}）"
        items.append(f"<b>{text}</b>" if item.get("external") else text)
    out = "、".join(items) or "—"
    if row.get("noPending"):
        out += "（无待审批人）"
    if row.get("notCurrent"):
        out += f"，另 {int(row['notCurrent'])} 人未签、非当前待办"
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
            days_cell,
            f'<td style="{_TD}color:{_RED};">{STALL_PLACEHOLDER}</td>',
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<table cellpadding="0" cellspacing="0" border="1" width="1000" '
        f'style="border-collapse:collapse;width:1000px;{_FONT}"><tr>{head}</tr>' + "".join(body) + "</table>"
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
                html.unescape(todo), _ratio(row["countersign"]),
                "—" if row.get("days") is None else str(row["days"]), STALL_PLACEHOLDER,
            ]))
    return "\n".join(out) + "\n"


# ── 每日进展（手工导入模式渲染；口径在 rules.daily_progress）──────────────
#
# 先一句经理一眼能读懂的话（签署率前后、待签人次增减、新签完、还剩几份），再一句明细数，
# 再只列有变化的单（新签完 → 减少最多 → 变多 → 新增；消失的单另列一行）。增减用 ↓/↑ 文字表达，
# 颜色只是辅助（绿 = 待签变少，红 = 变多），纯文本里照样读得通。

PROGRESS_KIND_TEXT = {
    "progress": "有人签了",
    "regress": "待签变多（加签或退回）",
    "new": "新增（上次没有）",
    "completed": "新签完",
    "unchanged": "无变化",
}
_PROGRESS_HEADERS = ("流水单号", "项目", "待签人数 前→后", "变化", "说明")
_GREEN = "#2e7d32"
_KIND_ORDER = {"completed": 0, "progress": 1, "regress": 2, "new": 3, "unchanged": 4}


def _arrow(value: Any, unit: str = "") -> str:
    """变化量：↓3 / ↑2 / 不变；没有可比的值写 —。"""
    if value is None:
        return "—"
    if value == 0:
        return "不变"
    return f"{'↓' if value < 0 else '↑'}{abs(int(value))}{unit}"


def _mmdd(base_date: Any) -> str:
    text = str(base_date or "")
    return text[5:10] if len(text) >= 10 else text


def _progress_heading(base_date: Any) -> str:
    day = _mmdd(base_date)
    return f"每日进展（较 {day}）" if day else "每日进展"


def _rate_change(before: Any, now: Any) -> str:
    try:
        diff = Decimal(str(now)) - Decimal(str(before))
    except (InvalidOperation, ValueError):
        return ""
    sign = "−" if diff < 0 else "+"
    return f"（{sign}{abs(diff)}%）"


def progress_headline(progress: Mapping[str, Any], base_date: Any = None) -> str:
    """一句话结论：较 MM-DD：签署率 a% → b%（±x%）；待签人次减少 n；新签完 k 份；还有 m 份未签完。"""
    totals = progress.get("totals") or {}
    day = _mmdd(base_date or progress.get("baseDate"))
    parts = []
    before, now = totals.get("rateBefore"), totals.get("rateNow")
    if before is not None and now is not None:
        parts.append(f"签署率 {before}% → {now}%{_rate_change(before, now)}")
    change = int(totals.get("remainingChange") or 0)
    if change < 0:
        parts.append(f"待签人次减少 {-change}")
    elif change > 0:
        parts.append(f"待签人次增加 {change}")
    else:
        parts.append("待签人次没有减少")
    parts.append(f"新签完 {len(totals.get('newlyCompleted') or [])} 份")
    parts.append(f"还有 {totals.get('openNow', 0)} 份未签完")
    return (f"较 {day}：" if day else "") + "；".join(parts) + "。"


def progress_sentence(progress: Mapping[str, Any]) -> str:
    """明细数：待签人次 X→Y（↓n）、签完 A→B 份、新签完 k 份、未签完 P→Q 份、新增 n 份、消失 m 份。"""
    totals = progress.get("totals") or {}
    # 前→后是两天各自的总数；括号里的增减只计两天都在的单。有新增/消失的单时两者对不上，
    # 所以把口径直接写进括号，免得读成「9→7 却减少 5」。
    scope = "两天都在的单 " if totals.get("newFlows") or totals.get("removedFlows") else ""
    sentence = (
        f"待签人次 {totals.get('remainingBefore', 0)}→{totals.get('remainingNow', 0)}"
        f"（{scope}{_arrow(totals.get('remainingChange', 0))}）、"
        f"签完 {totals.get('completeBefore', 0)}→{totals.get('completeNow', 0)} 份、"
        f"新签完 {len(totals.get('newlyCompleted') or [])} 份、"
        f"未签完 {totals.get('openBefore', 0)}→{totals.get('openNow', 0)} 份、"
        f"新增 {len(totals.get('newFlows') or [])} 份、"
        f"消失 {len(totals.get('removedFlows') or [])} 份。"
    )
    return sentence


def progress_rows(progress: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """只留有变化的单，排序：新签完 → 待签减少最多 → 待签变多 → 新增（同类按流水单号）。"""
    rows = [item for item in progress.get("flows") or [] if item.get("kind") != "unchanged"]
    return sorted(rows, key=lambda item: (
        _KIND_ORDER.get(item.get("kind"), 9),
        item.get("change") if item.get("kind") in ("progress", "completed") and item.get("change") is not None else 0,
        -(item.get("change") or 0) if item.get("kind") == "regress" else 0,
        str(item.get("serial") or ""),
    ))


def _before_after(item: Mapping[str, Any]) -> str:
    before = item.get("remainingBefore")
    return f"{'—' if before is None else before}→{item.get('remainingNow')}"


def _unchanged_text(progress: Mapping[str, Any], base_date: Any) -> str:
    day = _mmdd(base_date or progress.get("baseDate"))
    return f"与 {day} 相比没有变化" if day else "没有变化"


def progress_html(progress: Mapping[str, Any] | None, base_date: Any = None) -> str:
    """「每日进展」段（邮件安全的行内样式，所有值转义）。"""
    if not progress:
        return ""
    heading = _progress_heading(base_date or progress.get("baseDate"))
    parts = [
        f"<p><b>{_e(heading)}</b></p>",
        f"<p><b>{_e(progress_headline(progress, base_date))}</b><br>{_e(progress_sentence(progress))}</p>",
    ]
    rows = progress_rows(progress)
    removed = (progress.get("totals") or {}).get("removedFlows") or []
    if not rows and not removed:
        parts.append(f"<p>{_e(_unchanged_text(progress, base_date))}</p>")
        return "".join(parts)
    if rows:
        head = "".join(
            f'<th bgcolor="{_TH_BG}" style="{_TH}background:{_TH_BG};">{_e(h)}</th>' for h in _PROGRESS_HEADERS
        )
        body = []
        for item in rows:
            change = item.get("change")
            color = _GREEN if change is not None and change < 0 else (_RED if change else "")
            change_style = f"{_TD}white-space:nowrap;" + (f"color:{color};" if color else "")
            body.append(
                "<tr>"
                f'<td style="{_TD}white-space:nowrap;">{_e(item.get("serial"))}</td>'
                f'<td style="{_TD}white-space:nowrap;">{_e(item.get("project"))}</td>'
                f'<td style="{_TD}white-space:nowrap;">{_e(_before_after(item))}</td>'
                f'<td style="{change_style}">{_e(_arrow(change))}</td>'
                f'<td style="{_TD}">{_e(PROGRESS_KIND_TEXT.get(item.get("kind"), item.get("kind")))}</td>'
                "</tr>"
            )
        parts.append(
            f'<table cellpadding="0" cellspacing="0" border="1" width="640" '
            f'style="border-collapse:collapse;width:640px;{_FONT}"><tr>{head}</tr>{"".join(body)}</table>'
        )
    if removed:
        parts.append(f"<p>消失的单（今天的导出里没有）：{_e('、'.join(str(s) for s in removed))}</p>")
    return "".join(parts)


def progress_text(progress: Mapping[str, Any] | None, base_date: Any = None) -> str:
    """纯文本版「每日进展」：与 progress_html 同样的内容与顺序，制表符分隔。"""
    if not progress:
        return ""
    out = [
        _progress_heading(base_date or progress.get("baseDate")),
        progress_headline(progress, base_date), progress_sentence(progress),
    ]
    rows = progress_rows(progress)
    removed = (progress.get("totals") or {}).get("removedFlows") or []
    if not rows and not removed:
        out.append(_unchanged_text(progress, base_date))
    if rows:
        out.append("\t".join(_PROGRESS_HEADERS))
        for item in rows:
            out.append("\t".join([
                str(item.get("serial") or ""), str(item.get("project") or ""), _before_after(item),
                _arrow(item.get("change")), PROGRESS_KIND_TEXT.get(item.get("kind"), str(item.get("kind"))),
            ]))
    if removed:
        out.append("消失的单（今天的导出里没有）：" + "、".join(str(s) for s in removed))
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
