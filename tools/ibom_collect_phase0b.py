"""iBOM 双源方案开工前取证（阶段 0B）：一次收集方案缺的三类信息。

在装有 VSE Toolbox 的 Windows 电脑上运行（源码目录或任意目录均可）::

    python tools/ibom_collect_phase0b.py

收集内容（全部只读）：

1. **筛选条件（方案 Q5）**：只读打开本机 VSE Toolbox 数据库，列出 TDC 归档任务与项目状态绑定里
   实际填写的筛选键，并按双源方案 §3.4 标出 iBOM 侧能否本地套用。
2. **TDC 快照与 iBOM 单号交集**：读本机 ``tdc_data_model`` 表单快照的流水单号，与下载目录里最新的
   ``ibom_phase0_*.json``（浏览器取证脚本的产出）求交集；并统计近期 TDC 快照里新出现的单号，
   判断 TDC 是否还在接收新单。
3. **iBOM 登录跳转链**：**不登录、不发送任何账号密码**，以未登录状态访问 iBOM，逐跳记录重定向
   （主机、路径、查询参数名、Cookie 名），解析登录页表单的提交地址与字段名，并在 iBOM 前端脚本里
   检索登录相关的接口路径。

访问 iBOM 报代理错误时，先执行 ``set NO_PROXY=ibom.sgmw.com.cn`` 再运行（内网主机不走代理）。

产出：``<仓库根目录或当前目录>/.runtime/ibom-impact/phase0/collect_<时间>/`` 下的
``report.json`` 与 ``summary.md``，把整个文件夹（或两个文件）交回即可。

不写数据库、不改配置、不调用任何会改变服务端状态的接口。``state``/``code``/``nonce`` 等一次性
参数值、Cookie 值一律不记录。
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import platform
import re
import sqlite3
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urljoin, urlsplit

SCRIPT_VERSION = "2026-11-19.1"
IBOM_ORIGIN = "https://ibom.sgmw.com.cn"
FORM_KEY = "tdc_data_model"
MAX_HOPS = 15
MAX_SCRIPTS = 12
MAX_SCRIPT_BYTES = 6 * 1024 * 1024
TIMEOUT = 20

#: 方案 §3.4：iBOM 侧本地套用的分类。
FILTER_CLASS = {
    "documentNo": "本地精确匹配（可用）",
    "documentNos": "本地精确匹配（可用）",
    "watchlist": "本地精确匹配（可用）",
    "syncScope": "关注清单范围开关（可用）",
    "sections": "按「部门」列科室归集（可用）",
    "incident": "iBOM 侧取 0 行（仅 TDC 单有实例号）",
    "applicationStart": "按申请日期闭区间（可用）",
    "applicationEnd": "按申请日期闭区间（可用）",
    "status": "按状态精确匹配（可用）",
    "applicant": "未取证 → fail-closed",
    "projectModel": "未取证 → fail-closed",
    "partNumber": "未取证 → fail-closed",
    "modelNumber": "未取证 → fail-closed",
    "section": "未取证 → fail-closed",
    "department": "iBOM 报表无上级部门列 → fail-closed",
}
#: 不属于筛选的结构键。
NON_FILTER_KEYS = {"aggregate", "reportType", "contractVersion"}

#: 查询参数里可以原样记录值的键（非一次性、非凭据）。
SAFE_QUERY_KEYS = {
    "client_id", "response_type", "scope", "redirect_uri", "service", "response_mode",
    "kc_idp_hint", "ui_locales", "prompt", "returnUrl", "returnurl", "redirect", "target",
    "loginType", "logintype", "lang", "locale",
}
SECRET_HINT = re.compile(r"(pass|pwd|secret|token|ticket|code|state|nonce|session|sid|auth)", re.I)

JS_PATTERNS = (
    r"ssoAuth[A-Za-z/._-]*",
    r"/fwSecurity/authentication/[A-Za-z]+\.api",
    r"/fwPlatform/[A-Za-z]+/[A-Za-z]*[Ll]ogin[A-Za-z]*\.api",
    r"[A-Za-z/]*login\.api",
    r"/auth/realms/[A-Za-z0-9_-]+",
    r"openid-connect/[a-z]+",
    r"account\.sgmw\.com\.cn[^\"'\s]*",
    r"NORMAL_LOGIN|DEFAULT_SSO|CHOOSE_LOGIN_METHOD|SSO_CHECK_URL",
    r"client_id[\"']?\s*[:=]\s*[\"'][^\"']{1,60}[\"']",
    r"/cas/[a-zA-Z]+",
)


# ── 通用 ────────────────────────────────────────────────────────────


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def summarize_value(value: Any) -> Any:
    if isinstance(value, list):
        return {"count": len(value), "sample": value[:3]}
    if isinstance(value, dict):
        return {"keys": sorted(value)[:20]}
    if isinstance(value, str) and len(value) > 80:
        return value[:80] + "…"
    return value


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


def safe_url(url: str) -> dict[str, Any]:
    """URL → 主机、路径、查询参数（只保留白名单键的值）。"""
    parts = urlsplit(url)
    params = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        keep = key in SAFE_QUERY_KEYS and not SECRET_HINT.search(key)
        if key in ("redirect_uri", "service", "returnUrl", "returnurl", "redirect", "target"):
            keep = True
            value = safe_redirect_value(value)
        params.append({"name": key, "value": value if keep else "<omitted>"})
    return {"scheme": parts.scheme, "host": parts.hostname, "path": parts.path, "query": params,
            "fragmentKeys": [k for k, _ in parse_qsl(parts.fragment)] if "=" in parts.fragment else []}


def safe_redirect_value(value: str) -> str:
    """回跳地址只保留 scheme://host/path 与参数名。"""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<unparsable>"
    names = [k for k, _ in parse_qsl(parts.query, keep_blank_values=True)]
    tail = ("?" + "&".join(f"{n}=…" for n in names)) if names else ""
    return f"{parts.scheme}://{parts.hostname or ''}{parts.path}{tail}"


# ── 1/2. 本机数据库 ────────────────────────────────────────────────


def candidate_db_paths(explicit: str | None) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    env_root = os.environ.get("VSE_DATA_ROOT", "").strip()
    if env_root:
        paths.append(Path(env_root) / "data" / "vse_toolbox.db")
    script_root = Path(__file__).resolve().parent.parent
    paths.append(script_root / "data" / "vse_toolbox.db")
    paths.append(Path.cwd() / "data" / "vse_toolbox.db")
    for env_name in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env_name)
        if base:
            paths.append(Path(base) / "VSE-Toolbox" / "data" / "vse_toolbox.db")
    paths.append(Path.home() / "VSE-Toolbox" / "data" / "vse_toolbox.db")
    seen: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.append(resolved)
    return seen


def open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def classify_filters(rule: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(rule):
        value = rule[key]
        if key in NON_FILTER_KEYS:
            continue
        if is_blank(value):
            continue
        out.append({
            "key": key,
            "value": summarize_value(value),
            "ibom": FILTER_CLASS.get(key, "方案未覆盖的键 → 需评估"),
        })
    return out


def collect_filters(conn: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {"archiveJobs": [], "bindings": []}
    if table_exists(conn, "scheduled_archive_jobs"):
        for row in conn.execute(
            "SELECT job_key, source_type, report_type, enabled, display_name, filters_json,"
            " credential_ref, sync_state, last_success_at, archived_at FROM scheduled_archive_jobs"
            " WHERE source_type = 'tdc' ORDER BY job_key"
        ):
            try:
                filters = json.loads(row["filters_json"] or "{}")
            except ValueError:
                filters = {"<unparsable>": True}
            result["archiveJobs"].append({
                "jobKey": row["job_key"], "reportType": row["report_type"], "enabled": bool(row["enabled"]),
                "displayName": row["display_name"], "syncState": row["sync_state"],
                "lastSuccessAt": row["last_success_at"], "archived": bool(row["archived_at"]),
                "hasCredentialRef": bool(row["credential_ref"]),
                "filters": classify_filters(filters if isinstance(filters, dict) else {}),
            })
    if table_exists(conn, "project_status_update_bindings"):
        for row in conn.execute(
            "SELECT deliverable_id, mode, source_type, external_key, match_rule_json, enabled,"
            " sync_state, last_success_at, last_error_type FROM project_status_update_bindings"
            " WHERE source_type = 'tdc' ORDER BY deliverable_id"
        ):
            try:
                rule = json.loads(row["match_rule_json"] or "{}")
            except ValueError:
                rule = {}
            rule = rule if isinstance(rule, dict) else {}
            report = rule.get("reportType") or ("sor" if row["deliverable_id"] == "VPI-T2-D2" else "data_model")
            result["bindings"].append({
                "deliverableId": row["deliverable_id"], "reportType": report, "mode": row["mode"],
                "enabled": bool(row["enabled"]), "syncState": row["sync_state"],
                "lastSuccessAt": row["last_success_at"], "lastErrorType": row["last_error_type"],
                "externalKey": row["external_key"], "aggregate": rule.get("aggregate"),
                "filters": classify_filters(rule),
            })
    used = collections.Counter()
    blocked = collections.Counter()
    for item in result["archiveJobs"] + result["bindings"]:
        if item.get("reportType") != "data_model":
            continue
        for f in item["filters"]:
            used[f["key"]] += 1
            if "fail-closed" in f["ibom"] or "需评估" in f["ibom"]:
                blocked[f["key"]] += 1
    result["dataModelFilterKeysUsed"] = dict(used)
    result["dataModelFilterKeysFailClosed"] = dict(blocked)
    return result


def _serial_index(schema: dict[str, Any]) -> tuple[int, int, int]:
    serial, status, applied = 2, 46, 6
    for column in schema.get("columns") or []:
        label = str(column.get("label") or "")
        index = column.get("index")
        if not isinstance(index, int):
            continue
        if label == "流水单号":
            serial = index
        elif label == "状态":
            status = index
        elif label == "申请日期":
            applied = index
    return serial, status, applied


def _coverage_kind(schema: dict[str, Any]) -> str:
    coverage = schema.get("coverage")
    if isinstance(coverage, dict) and coverage.get("kind") == "watchlist":
        return "watchlist"
    return "all"


def collect_tdc_snapshots(conn: sqlite3.Connection, limit: int = 60) -> dict[str, Any]:
    if not (table_exists(conn, "deliverable_form_snapshots") and table_exists(conn, "deliverable_form_rows")):
        return {"error": "snapshot tables not found"}
    snaps = conn.execute(
        "SELECT id, snapshot_at, source, row_count, schema_json FROM deliverable_form_snapshots"
        " WHERE form_key = ? ORDER BY snapshot_at DESC, id DESC LIMIT ?",
        (FORM_KEY, limit),
    ).fetchall()
    listing = []
    full_serials: list[tuple[str, set[str]]] = []
    latest_detail: dict[str, Any] | None = None
    for snap in snaps:
        try:
            schema = json.loads(snap["schema_json"] or "{}")
        except ValueError:
            schema = {}
        kind = _coverage_kind(schema)
        listing.append({"id": snap["id"], "snapshotAt": snap["snapshot_at"], "source": snap["source"],
                        "rowCount": snap["row_count"], "coverage": kind})
        if kind != "all":
            continue
        serial_i, status_i, applied_i = _serial_index(schema)
        serials: set[str] = set()
        statuses: collections.Counter = collections.Counter()
        applied_max = ""
        for row in conn.execute("SELECT values_json FROM deliverable_form_rows WHERE snapshot_id = ?", (snap["id"],)):
            try:
                values = json.loads(row["values_json"] or "[]")
            except ValueError:
                continue
            if not isinstance(values, list):
                continue
            serial = str(values[serial_i]).strip() if len(values) > serial_i and values[serial_i] is not None else ""
            if serial:
                serials.add(serial)
            if len(values) > status_i:
                statuses[str(values[status_i])] += 1
            if len(values) > applied_i and values[applied_i] is not None:
                applied_max = max(applied_max, str(values[applied_i]))
        full_serials.append((str(snap["snapshot_at"]), serials))
        if latest_detail is None:
            ordered = sorted(serials)
            latest_detail = {
                "snapshotId": snap["id"], "snapshotAt": snap["snapshot_at"], "source": snap["source"],
                "documents": len(serials), "serialRange": [ordered[0], ordered[-1]] if ordered else None,
                "statusRows": dict(statuses.most_common(12)), "latestAppliedDate": applied_max,
            }
    # 近期新单：按时间正序比较相邻全量快照。
    trend = []
    ordered_full = list(reversed(full_serials))
    for (prev_at, prev), (at, cur) in zip(ordered_full, ordered_full[1:]):
        new = sorted(cur - prev)
        trend.append({"snapshotAt": at, "newSerials": len(new), "sample": new[:10],
                      "goneSerials": len(prev - cur)})
    union: set[str] = set()
    for _, serials in full_serials:
        union |= serials
    return {"snapshots": listing, "latestFull": latest_detail, "newSerialTrend": trend[-30:],
            "_latestSerials": full_serials[0][1] if full_serials else set(), "_unionSerials": union}


def find_phase0_json(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    dirs = [Path.home() / "Downloads", Path.home() / "下载", Path.cwd()]
    found: list[Path] = []
    for folder in dirs:
        if folder.is_dir():
            found.extend(folder.glob("ibom_phase0_*.json"))
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def collect_intersection(phase0: Path | None, tdc: dict[str, Any]) -> dict[str, Any]:
    if phase0 is None or not phase0.is_file():
        return {"error": "未找到 ibom_phase0_*.json（下载目录或 --phase0 指定）"}
    try:
        bundle = json.loads(phase0.read_text(encoding="utf-8"))
        codes = set(bundle["summary"]["dmm"]["allChangeCodes"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"error": f"phase0 JSON 无法读取：{type(exc).__name__}"}
    latest = tdc.get("_latestSerials") or set()
    union = tdc.get("_unionSerials") or set()
    ordered = sorted(codes)
    return {
        "phase0File": phase0.name, "phase0StartedAt": bundle.get("startedAt"),
        "ibomDocuments": len(codes), "ibomSerialRange": [ordered[0], ordered[-1]] if ordered else None,
        "overlapWithLatestTdc": sorted(codes & latest)[:200],
        "overlapWithAnyRecentTdc": sorted(codes & union)[:200],
        "overlapCountLatest": len(codes & latest), "overlapCountAnyRecent": len(codes & union),
    }


# ── 3. iBOM 登录跳转链（不登录）────────────────────────────────────


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self.scripts: list[str] = []
        self.title = ""
        self._in_title = False
        self._form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "form":
            self._form = {"action": a.get("action", ""), "method": a.get("method", "get").lower(), "fields": []}
            self.forms.append(self._form)
        elif tag in ("input", "select", "button") and self._form is not None:
            name = a.get("name") or a.get("id") or ""
            if name:
                self._form["fields"].append({"name": name, "type": a.get("type", tag)})
        elif tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._form = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()


def _http_session():
    try:
        import requests  # 与 services/tdc_auth.py 相同的依赖
    except ImportError:
        return None
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) vse-toolbox-phase0b"
    session.headers["Accept-Language"] = "zh-CN"
    return session


def _cookie_names(response: Any) -> list[str]:
    raw = response.raw.headers.getlist("Set-Cookie") if hasattr(response.raw.headers, "getlist") else []
    if not raw and response.headers.get("Set-Cookie"):
        raw = [response.headers["Set-Cookie"]]
    names = []
    for item in raw:
        name = item.split("=", 1)[0].strip()
        flags = [p.strip().split("=")[0].lower() for p in item.split(";")[1:]]
        names.append({"name": name, "flags": sorted(set(f for f in flags if f in ("httponly", "secure", "samesite", "domain", "path")))})
    return names


def follow_chain(session: Any, start: str) -> dict[str, Any]:
    hops = []
    url = start
    final_html = ""
    final_url = start
    for _ in range(MAX_HOPS):
        try:
            resp = session.get(url, allow_redirects=False, timeout=TIMEOUT)
        except Exception as exc:  # 网络/证书问题照实记录
            hops.append({"url": safe_url(url), "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            break
        hop = {
            "url": safe_url(url), "status": resp.status_code,
            "contentType": resp.headers.get("Content-Type", ""),
            "setCookies": _cookie_names(resp),
            "server": resp.headers.get("Server", ""),
        }
        location = resp.headers.get("Location")
        if location:
            nxt = urljoin(url, location)
            hop["location"] = safe_url(nxt)
            hops.append(hop)
            url = nxt
            continue
        hops.append(hop)
        final_url = url
        if "html" in hop["contentType"].lower():
            final_html = resp.text[:2_000_000]
        else:
            hop["bodyHead"] = resp.text[:300] if "json" in hop["contentType"].lower() else ""
        break
    page: dict[str, Any] = {}
    if final_html:
        parser = _FormParser()
        try:
            parser.feed(final_html)
        except Exception:
            pass
        page = {
            "title": parser.title[:120],
            "forms": [{"action": safe_url(urljoin(final_url, f["action"])) if f["action"] else None,
                       "method": f["method"], "fields": f["fields"][:30]} for f in parser.forms[:5]],
            "scripts": [urljoin(final_url, s) for s in parser.scripts[:MAX_SCRIPTS]],
            "metaRefresh": re.findall(r'http-equiv=["\']refresh["\'][^>]*content=["\']([^"\']+)', final_html, re.I)[:3],
            "jsRedirects": sorted(set(re.findall(r'(?:location\.href|window\.location)\s*=\s*["\']([^"\']{1,200})', final_html)))[:5],
        }
    return {"start": start, "hops": hops, "finalPage": page, "_finalHtml": final_html, "_finalUrl": final_url}


def grep_scripts(session: Any, urls: Iterable[str]) -> dict[str, Any]:
    hits: dict[str, set[str]] = collections.defaultdict(set)
    fetched = []
    for url in list(urls)[:MAX_SCRIPTS]:
        if urlsplit(url).hostname != urlsplit(IBOM_ORIGIN).hostname:
            fetched.append({"url": safe_url(url), "skipped": "非 iBOM 主机"})
            continue
        try:
            resp = session.get(url, timeout=TIMEOUT, stream=True)
            body = resp.raw.read(MAX_SCRIPT_BYTES, decode_content=True).decode("utf-8", "replace")
        except Exception as exc:
            fetched.append({"url": safe_url(url), "error": type(exc).__name__})
            continue
        fetched.append({"url": safe_url(url), "status": resp.status_code, "bytes": len(body)})
        for pattern in JS_PATTERNS:
            for match in re.finditer(pattern, body):
                start = max(0, match.start() - 60)
                snippet = body[start:match.end() + 60].replace("\n", " ")
                hits[pattern].add(snippet)
                if len(hits[pattern]) >= 8:
                    break
    return {"scripts": fetched, "hits": {k: sorted(v) for k, v in hits.items()}}


def collect_sso(no_network: bool) -> dict[str, Any]:
    if no_network:
        return {"skipped": "--no-network"}
    session = _http_session()
    if session is None:
        return {"error": "缺少 requests 库：请在 VSE Toolbox 的 Python 环境里运行"}
    result: dict[str, Any] = {}
    root = follow_chain(session, IBOM_ORIGIN + "/")
    sso = follow_chain(_http_session(), IBOM_ORIGIN + "/fwPlatform/ssoAuth/login.api")
    scripts = list(root["finalPage"].get("scripts", []))
    if not any(urlsplit(s).hostname == urlsplit(IBOM_ORIGIN).hostname for s in scripts):
        try:
            resp = session.get(IBOM_ORIGIN + "/", allow_redirects=False, timeout=TIMEOUT)
            if "html" in resp.headers.get("Content-Type", "").lower():
                parser = _FormParser()
                parser.feed(resp.text[:2_000_000])
                scripts += [urljoin(IBOM_ORIGIN + "/", s) for s in parser.scripts]
        except Exception:
            pass
    for item in (root, sso):
        item.pop("_finalHtml", None)
        item.pop("_finalUrl", None)
    result["rootChain"] = root
    result["ssoAuthChain"] = sso
    result["frontendScripts"] = grep_scripts(session, dict.fromkeys(scripts))
    return result


# ── 汇总 ────────────────────────────────────────────────────────────


def render_summary(report: dict[str, Any]) -> str:
    lines = [f"# iBOM 阶段 0B 取证摘要（{report['collectedAt']}）", ""]
    db = report["database"]
    lines.append(f"- 数据库：{db.get('used') or '未找到'}")
    filters = report.get("filters") or {}
    lines += ["", "## 1. 数模筛选条件（方案 Q5）", ""]
    rows = [i for i in filters.get("archiveJobs", []) + filters.get("bindings", []) if i.get("reportType") == "data_model"]
    if not rows:
        lines.append("没有找到 TDC 数模的归档任务或项目状态绑定。")
    for item in rows:
        name = item.get("jobKey") or item.get("deliverableId")
        kind = "归档任务" if "jobKey" in item else "项目状态绑定"
        lines.append(f"- **{kind} {name}**（启用={item.get('enabled')}）")
        if not item["filters"]:
            lines.append("  - 无筛选（全量）")
        for f in item["filters"]:
            lines.append(f"  - `{f['key']}` = {json.dumps(f['value'], ensure_ascii=False)} → {f['ibom']}")
    blocked = filters.get("dataModelFilterKeysFailClosed") or {}
    lines.append("")
    lines.append("**会导致 iBOM 侧 fail-closed 的键**：" + ("、".join(blocked) if blocked else "无"))
    tdc = report.get("tdcSnapshots") or {}
    latest = tdc.get("latestFull") or {}
    lines += ["", "## 2. TDC 快照与 iBOM 单号", ""]
    if latest:
        lines.append(f"- 最新全量 TDC 快照：{latest.get('snapshotAt')}，{latest.get('documents')} 张单，"
                     f"单号范围 {latest.get('serialRange')}，最近申请日期 {latest.get('latestAppliedDate')}")
    trend = tdc.get("newSerialTrend") or []
    if trend:
        recent = trend[-10:]
        lines.append("- 近期 TDC 快照新增单号数：" + "，".join(f"{t['snapshotAt'][:10]}:{t['newSerials']}" for t in recent))
    inter = report.get("intersection") or {}
    if "error" in inter:
        lines.append(f"- 交集：{inter['error']}")
    else:
        lines.append(f"- iBOM：{inter.get('ibomDocuments')} 张，范围 {inter.get('ibomSerialRange')}（来自 {inter.get('phase0File')}）")
        lines.append(f"- 与最新 TDC 快照重叠 {inter.get('overlapCountLatest')} 张；与近期任一 TDC 快照重叠 {inter.get('overlapCountAnyRecent')} 张")
        if inter.get("overlapWithAnyRecentTdc"):
            lines.append("  - 重叠单号：" + "、".join(inter["overlapWithAnyRecentTdc"][:30]))
    sso = report.get("sso") or {}
    lines += ["", "## 3. iBOM 登录跳转链（未登录）", ""]
    if "error" in sso or "skipped" in sso:
        lines.append(f"- {sso.get('error') or sso.get('skipped')}")
    else:
        for label, key in (("访问首页", "rootChain"), ("访问 ssoAuth/login.api", "ssoAuthChain")):
            chain = sso.get(key) or {}
            lines.append(f"- {label}：")
            for hop in chain.get("hops", []):
                u = hop["url"]
                params = ",".join(p["name"] for p in u.get("query", []))
                tail = f" → {hop['location']['host']}{hop['location']['path']}" if hop.get("location") else ""
                lines.append(f"  - {hop.get('status', hop.get('error'))} {u.get('host')}{u.get('path')}"
                             f"{' ?' + params if params else ''}{tail}")
            for form in (chain.get("finalPage") or {}).get("forms", []):
                action = form.get("action") or {}
                lines.append(f"  - 登录表单：{form.get('method')} {action.get('host')}{action.get('path')}，"
                             f"字段 {[f['name'] for f in form.get('fields', [])]}")
        hits = (sso.get("frontendScripts") or {}).get("hits") or {}
        lines.append(f"- 前端脚本检索命中 {sum(len(v) for v in hits.values())} 处（详见 report.json → sso.frontendScripts）")
    lines += ["", "本摘要不含任何密码、Cookie 值、token 或一次性参数值。", ""]
    return "\n".join(lines)


def output_dir(base: Path) -> Path:
    path = base / ".runtime" / "ibom-impact" / "phase0" / f"collect_{now_stamp()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    global IBOM_ORIGIN
    for stream in (sys.stdout, sys.stderr):
        try:  # GBK 控制台或重定向时不因中文输出报错
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="iBOM 双源方案开工前只读取证")
    parser.add_argument("--db", help="VSE Toolbox 数据库路径（默认自动查找）")
    parser.add_argument("--phase0", help="浏览器取证脚本产出的 ibom_phase0_*.json（默认取下载目录最新一份）")
    parser.add_argument("--out", help="输出根目录（默认：脚本所在仓库根目录，找不到则当前目录）")
    parser.add_argument("--no-network", action="store_true", help="不访问 iBOM（只读本机数据库）")
    parser.add_argument("--origin", default=IBOM_ORIGIN, help=argparse.SUPPRESS)  # 仅测试用
    args = parser.parse_args(argv)
    IBOM_ORIGIN = args.origin.rstrip("/")

    report: dict[str, Any] = {
        "scriptVersion": SCRIPT_VERSION,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "database": {"candidates": []},
    }
    candidates = candidate_db_paths(args.db)
    existing = []
    for path in candidates:
        info = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            stat = path.stat()
            info.update(size=stat.st_size, modified=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"))
            existing.append(path)
        report["database"]["candidates"].append(info)
    db_path = Path(args.db) if args.db else (max(existing, key=lambda p: p.stat().st_mtime) if existing else None)
    tdc: dict[str, Any] = {}
    if db_path is not None and db_path.is_file():
        report["database"]["used"] = str(db_path)
        try:
            conn = open_ro(db_path)
            try:
                report["filters"] = collect_filters(conn)
                tdc = collect_tdc_snapshots(conn)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            report["database"]["error"] = f"{type(exc).__name__}: {exc}"
    else:
        report["database"]["error"] = "未找到 vse_toolbox.db，可用 --db 指定"
    report["intersection"] = collect_intersection(find_phase0_json(args.phase0), tdc)
    report["tdcSnapshots"] = {k: v for k, v in tdc.items() if not k.startswith("_")}
    print("[1/3] 本机数据库读取完成" if "used" in report["database"] else "[1/3] 未找到本机数据库")
    print("[2/3] 正在以未登录状态访问 iBOM（不发送账号密码）…" if not args.no_network else "[2/3] 跳过网络")
    report["sso"] = collect_sso(args.no_network)
    print("[3/3] 汇总")

    base = Path(args.out) if args.out else Path(__file__).resolve().parent.parent
    if not (base / "tools").is_dir() and not args.out:
        base = Path.cwd()
    out = output_dir(base)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "summary.md").write_text(render_summary(report), encoding="utf-8")
    print(f"完成：{out}")
    print("请把这个文件夹里的 report.json 与 summary.md 交回。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
