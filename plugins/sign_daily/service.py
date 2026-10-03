# -*- coding: utf-8 -*-
"""签署日报 v2.0：零件级快照、基线重算、长周期结论记忆与后台抓取。

口径全部在 ``rules.py``；本模块只负责取数、存取和组装，供 ``backend.py`` 的
``/v2/*`` 路由使用。v1 路由（``report.py``）在前端切换前保持不变。

- 快照（D1）：每次生成成功后按「数据日期 + 项目」存 TDC 原始行（只留口径用到的列），
  基线（D3）用同一套解析代码、按今天的范围、花名册和长周期结论重算，改规则不会造出假变化。
- 数据日期取 TDC 表单快照的抓取时间（本机时区）。
"""

from __future__ import annotations

import csv
import functools
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import rules as V

FORM_KEY = "tdc_data_model"
ARCHIVE_JOB_KEY = "tdc_data_model"
TASK_SOURCE = "sign-daily"
TASK_TYPE = "sign_daily_refresh"
SNAPSHOT_RETENTION_DAYS = 90
BASELINE_MAX_GAP_DAYS = 14
SEEDS_DIR = Path(__file__).resolve().parent / "seeds"
_TASK_ID = re.compile(r"^crawl_[0-9a-f]{12}$")


# ── 种子 ────────────────────────────────────────────────────────────


def _read_csv(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(V.decode_csv(path.read_bytes()))))


@functools.lru_cache(maxsize=1)
def seed_roster() -> tuple[tuple[str, str], ...]:
    parsed = V.parse_roster_table(_read_csv(SEEDS_DIR / "roster.csv"))
    return tuple((entry["name"], entry["department"]) for entry in parsed["entries"])


@functools.lru_cache(maxsize=1)
def seed_rules() -> tuple[V.LongCycleRule, ...]:
    return tuple(V.parse_long_cycle_table(_read_csv(SEEDS_DIR / "long_cycle.csv"))["rules"])


@functools.lru_cache(maxsize=1)
def seed_version() -> str:
    try:
        return str(json.loads((SEEDS_DIR / "seed.json").read_text(encoding="utf-8")).get("seedVersion") or "")
    except (OSError, ValueError):
        return ""


# ── 存储 ────────────────────────────────────────────────────────────


class SnapshotStore:
    """插件自有表：快照元数据、快照行、长周期结论（前缀由宿主分配）。"""

    def __init__(self, db: Any, prefix: str):
        self.db = db
        self.meta_table = f"{prefix}snapshot_meta"
        self.rows_table = f"{prefix}snapshot_rows"
        self.conclusion_table = f"{prefix}long_cycle_conclusion"

    def migration(self) -> tuple[int, Callable[[Any], None]]:
        def v2(conn) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.meta_table} ("
                "data_date TEXT NOT NULL, project TEXT NOT NULL, scope_kind TEXT NOT NULL, "
                "serials_json TEXT NOT NULL, source_snapshot_at TEXT, row_count INTEGER NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "PRIMARY KEY (data_date, project))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.rows_table} ("
                "data_date TEXT NOT NULL, project TEXT NOT NULL, seq INTEGER NOT NULL, row_json TEXT NOT NULL, "
                "PRIMARY KEY (data_date, project, seq))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.conclusion_table} ("
                "project TEXT NOT NULL, part_key TEXT NOT NULL, include INTEGER NOT NULL, "
                "auto_result TEXT NOT NULL, rule_id TEXT NOT NULL, "
                "decided_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "PRIMARY KEY (project, part_key))"
            )

        return (2, v2)

    # 快照

    def snapshot_dates(self, project: str) -> list[date]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT data_date FROM {self.meta_table} WHERE project = ? ORDER BY data_date DESC", (project,)
            ).fetchall()
        return [date.fromisoformat(row["data_date"]) for row in rows]

    def snapshot_scope(self, project: str, day: date) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT scope_kind, serials_json FROM {self.meta_table} WHERE project = ? AND data_date = ?",
                (project, day.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return {"kind": row["scope_kind"], "serials": json.loads(row["serials_json"])}

    def snapshot_rows(self, projects: Iterable[str], day: date) -> list[dict[str, Any]]:
        projects = list(projects)
        if not projects:
            return []
        marks = ",".join("?" for _ in projects)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT row_json FROM {self.rows_table} WHERE data_date = ? AND project IN ({marks}) "
                "ORDER BY project, seq",
                (day.isoformat(), *projects),
            ).fetchall()
        return [json.loads(row["row_json"]) for row in rows]

    def save_snapshot(self, day: date, project: str, rows: Sequence[Mapping[str, Any]], *,
                      scope_kind: str, serials: Sequence[str], source_snapshot_at: str | None) -> None:
        """D1：同一数据日期重复生成时后一次覆盖前一次；保留 90 天。"""
        cutoff = (day - timedelta(days=SNAPSHOT_RETENTION_DAYS)).isoformat()
        with self.db.get_connection() as conn:
            conn.execute(f"DELETE FROM {self.rows_table} WHERE data_date = ? AND project = ?", (day.isoformat(), project))
            conn.executemany(
                f"INSERT INTO {self.rows_table} (data_date, project, seq, row_json) VALUES (?, ?, ?, ?)",
                [(day.isoformat(), project, seq, json.dumps(row, ensure_ascii=False)) for seq, row in enumerate(rows)],
            )
            conn.execute(
                f"INSERT INTO {self.meta_table} (data_date, project, scope_kind, serials_json, source_snapshot_at, "
                "row_count) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(data_date, project) DO UPDATE SET "
                "scope_kind = excluded.scope_kind, serials_json = excluded.serials_json, "
                "source_snapshot_at = excluded.source_snapshot_at, row_count = excluded.row_count, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (day.isoformat(), project, scope_kind, json.dumps(sorted(serials), ensure_ascii=False),
                 source_snapshot_at, len(rows)),
            )
            conn.execute(f"DELETE FROM {self.rows_table} WHERE data_date < ?", (cutoff,))
            conn.execute(f"DELETE FROM {self.meta_table} WHERE data_date < ?", (cutoff,))

    # 长周期结论

    def conclusions(self, projects: Iterable[str]) -> dict[str, dict[str, bool]]:
        projects = list(projects)
        result: dict[str, dict[str, bool]] = {project: {} for project in projects}
        if not projects:
            return result
        marks = ",".join("?" for _ in projects)
        with self.db.get_connection() as conn:
            for row in conn.execute(
                f"SELECT project, part_key, include FROM {self.conclusion_table} WHERE project IN ({marks})", projects
            ):
                result[row["project"]][row["part_key"]] = bool(row["include"])
        return result

    def save_conclusions(self, project: str, items: Sequence[Mapping[str, Any]]) -> None:
        with self.db.get_connection() as conn:
            conn.executemany(
                f"INSERT INTO {self.conclusion_table} (project, part_key, include, auto_result, rule_id) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(project, part_key) DO UPDATE SET include = excluded.include, "
                "auto_result = excluded.auto_result, rule_id = excluded.rule_id, "
                "decided_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                [(project, item["key"], int(bool(item["include"])), item["autoResult"], item["rule"]) for item in items],
            )

    def clear_conclusions(self, project: str) -> int:
        with self.db.get_connection() as conn:
            return conn.execute(f"DELETE FROM {self.conclusion_table} WHERE project = ?", (project,)).rowcount


# ── 取数 ────────────────────────────────────────────────────────────


class NoData(LookupError):
    pass


@dataclass
class SourceData:
    records: list[dict[str, Any]]
    snapshot_at: str | None
    data_date: date


def data_date_of(snapshot_at: Any, tz: tzinfo | None = None) -> date | None:
    """抓取完成时间（ISO，通常是 UTC）-> 本机时区的日期。"""
    text = str(snapshot_at or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(tz).date()


def load_source(db: Any, headers_of: Callable[[Mapping[str, Any]], list[str]], tz: tzinfo | None = None) -> SourceData:
    latest = db.get_latest_deliverable_form_snapshot(FORM_KEY)
    if latest is None:
        raise NoData("还没有 TDC 数模设计审核流程数据，请先点「一键生成」抓取")
    headers = headers_of(latest)
    V.check_columns(headers)
    rows = db.list_deliverable_form_snapshot_rows(int(latest["id"]))
    keep = set(V.REQUIRED_COLUMNS)
    records = [
        {key: value for key, value in zip(headers, row.get("values") or []) if key in keep}
        for row in rows
    ]
    snapshot_at = latest.get("snapshot_at")
    data_date = data_date_of(snapshot_at, tz)
    if data_date is None:
        raise NoData("TDC 数据缺少抓取时间，无法确定数据日期")
    return SourceData(records, snapshot_at, data_date)


# ── 组装 ────────────────────────────────────────────────────────────


@dataclass
class Scope:
    projects: list[str]
    departments: list[str]


def _jsonable(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if k in V.PERCENT_KEYS and v is not None else v) for k, v in metrics.items()}


def _jsonable_summary(summary: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {group: _jsonable(values) for group, values in summary.items()}


class _Context:
    """一次计算用到的生效配置：花名册、长周期规则与结论、未在册人员指定区域。"""

    def __init__(self, store: SnapshotStore, projects: Iterable[str], person_areas: Mapping[str, str]):
        self.roster = V.Roster(seed_roster())
        self.rules = list(seed_rules())
        self.vocab = V.Vocabulary()
        self.person_areas = dict(person_areas)
        self.conclusions = store.conclusions(projects)

    def department(self, flow: V.Flow) -> str:
        return V.flow_department(flow, self.roster)[0]

    def in_scope(self, flows: Iterable[V.Flow], scope: Scope) -> list[V.Flow]:
        projects, departments = set(scope.projects), set(scope.departments)
        return [
            flow for flow in flows
            if (not projects or flow.project in projects)
            and (not departments or self.department(flow) in departments)
        ]


def _long_cycle(ctx: _Context, today: Sequence[V.Flow], base: Sequence[V.Flow]) -> dict[str, Any]:
    """按项目做长周期判定；基线也用今天的规则和结论（D3）。"""
    by_project: dict[str, list[str]] = {}
    for flow in [*today, *base]:
        by_project.setdefault(flow.project, []).extend(flow.parts.values())
    today_keys = {
        (flow.project, V.conclusion_key(name)) for flow in today for name in flow.parts.values() if name
    }
    counted: dict[str, set[str]] = {}
    review: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for project, names in sorted(by_project.items()):
        decisions = V.long_cycle_decisions(names, ctx.rules, ctx.conclusions.get(project, {}), ctx.vocab)
        counted[project] = decisions["counted"]
        for bucket, items in (("review", decisions["review"]), ("excluded", decisions["excluded"])):
            target = review if bucket == "review" else excluded
            for item in items:
                if (project, item["normalized"]) in today_keys:
                    serials = sorted({
                        f.serial for f in today if f.project == project
                        and any(V.conclusion_key(n) == item["normalized"] for n in f.parts.values() if n)
                    })
                    target.append({**item, "project": project, "flows": len(serials)})

    def long_parts(flows: Sequence[V.Flow]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for flow in flows:
            keys = {
                key for key, name in flow.parts.items()
                if name and V.conclusion_key(name) in counted.get(flow.project, set())
            }
            if keys:
                result[flow.serial] = keys
        return result

    return {"review": review, "excluded": excluded, "longParts": long_parts}


def _pick_baseline(store: SnapshotStore, projects: Sequence[str], data_date: date,
                   serials_by_project: Mapping[str, set[str]]) -> date | None:
    """D2：早于数据日期、所选项目都有快照且覆盖今天范围的最近一天。"""
    common: set[date] | None = None
    for project in projects:
        dates = {d for d in store.snapshot_dates(project) if d < data_date}
        common = dates if common is None else common & dates
    for day in sorted(common or (), reverse=True):
        if all(
            V.snapshot_covers(store.snapshot_scope(project, day) or {}, serials_by_project.get(project, ()))
            for project in projects
        ):
            return day
    return None


def _summary_lines(label: str, region: str, current: Mapping[str, Any], delta: Mapping[str, Any] | None) -> list[str]:
    total, long = current["total"], current["longCycle"]
    d_total = (delta or {}).get("total") or {}
    d_long = (delta or {}).get("longCycle") or {}

    def pct(values: Mapping[str, Any], d: Mapping[str, Any], key: str) -> str:
        return V.fmt_pct(values[key]) + V.fmt_delta(d.get(key), percent=True)

    def count(values: Mapping[str, Any], d: Mapping[str, Any], key: str) -> str:
        return f"{values[key]}{V.fmt_delta(d.get(key), percent=False)}"

    def line(values: Mapping[str, Any], d: Mapping[str, Any], t2_label: str) -> str:
        return (
            f"会签签单率{pct(values, d, 'countersignRate')}，总签单率{pct(values, d, 'totalRate')}，"
            f"3D单完成{count(values, d, 'complete')}/{values['flows']}份，"
            f"{t2_label}{pct(values, d, 't2Rate')}，已锁定发布{count(values, d, 'locked')}/{values['parts']}"
        )

    def nm(values: Mapping[str, Any], d: Mapping[str, Any], key: str) -> str:
        return f"{values[key]}{V.fmt_count_delta(d.get(key))}"  # D6：N、M 有变化才带括号

    return [
        f"{label}-{region}-3D单流程共{nm(total, d_total, 'flows')}份，涉及零件{nm(total, d_total, 'parts')}个，"
        f"其中长周期件流程共{nm(long, d_long, 'flows')}份，涉及零件{nm(long, d_long, 'parts')}个。",
        "长周期：" + line(long, d_long, "LLP T2发布率") + "；",
        "总：" + line(total, d_total, "T2发布率") + "。",
    ]


def project_label(projects: Sequence[str], flows: Sequence[V.Flow]) -> str:
    chosen = list(projects) or sorted({f.project for f in flows if f.project})
    return "&".join(chosen) or "全部项目"


def subject_for(label: str, region: str, day: date) -> str:
    return f"{label}项目3D单签署进展-{region}-{day:%Y%m%d}"


def scope_options(flows: Sequence[V.Flow], ctx: _Context) -> dict[str, list[str]]:
    present = {ctx.department(f) for f in flows}
    departments = [d for d in V.CURRENT_DEPARTMENTS] + sorted(d for d in present if d and d not in V.CURRENT_DEPARTMENTS)
    return {"projects": sorted({f.project for f in flows if f.project}), "departments": departments}


def compose(
    store: SnapshotStore,
    source: SourceData,
    scope: Scope,
    *,
    region: str,
    person_areas: Mapping[str, str],
    save_snapshot: bool,
    today: date | None = None,
) -> dict[str, Any]:
    """today 是生成当天的日历日期；数据日期早于它且那天的快照已存，说明在用旧数据。"""
    parsed = V.build_flows(source.records)
    projects_all = sorted({f.project for f in parsed.flows if f.project})
    projects = [p for p in scope.projects if p] or projects_all
    ctx = _Context(store, projects, person_areas)
    flows = ctx.in_scope(parsed.flows, Scope(projects, scope.departments))
    if not flows:
        raise LookupError("范围内没有 3D单")
    projects = sorted({f.project for f in flows})
    serials_by_project: dict[str, set[str]] = {}
    for flow in flows:
        serials_by_project.setdefault(flow.project, set()).add(flow.serial)

    # 旧数据（如抓取失败后用最近一次数据生成）：已有更晚数据日期的快照，或数据日期早于今天且
    # 那天的快照已经存过——不写快照、不显示括号，预览顶部标数据时间（§5、§8）。
    stored = {p: store.snapshot_dates(p) for p in projects}
    stale = any(
        any(d > source.data_date for d in dates)
        or (today is not None and today > source.data_date and source.data_date in dates)
        for dates in stored.values()
    )
    base_date = None if stale else _pick_baseline(store, projects, source.data_date, serials_by_project)
    mode = {"show": False, "note": ""} if stale else V.baseline_mode(source.data_date, base_date, BASELINE_MAX_GAP_DAYS)
    base_flows: list[V.Flow] = []
    if mode["show"] and base_date is not None:
        base_parsed = V.build_flows(store.snapshot_rows(projects, base_date))
        base_flows = ctx.in_scope(base_parsed.flows, Scope(projects, scope.departments))

    long_cycle = _long_cycle(ctx, flows, base_flows)
    long_parts = long_cycle["longParts"](flows)
    current = V.summary(flows, long_parts)
    base = V.summary(base_flows, long_cycle["longParts"](base_flows)) if mode["show"] else None
    delta = V.deltas(current, base)

    charts = V.owed_charts(flows, ctx.roster, ctx.person_areas)
    table = V.flow_rows(flows, source.data_date, ctx.roster, long_parts.keys(), ctx.person_areas)
    for row in table:
        row["partLabel"] = V.part_label(row)
        row["todoText"] = V.todo_text(row)

    label = project_label(scope.projects, flows)
    notices = _notices(flows, ctx, charts, long_cycle, parsed.anomalies)
    lines = _summary_lines(label, region, current, delta)
    if mode["note"]:
        lines.append(mode["note"])

    if save_snapshot and not stale:
        keep = [r for r in source.records if V.cell_text(r.get("项目/车型")) in set(projects)]
        for project in projects:
            rows = [r for r in keep if V.cell_text(r.get("项目/车型")) == project]
            serials = {V.cell_text(r.get("流水单号")) for r in rows if V.cell_text(r.get("流水单号"))}
            store.save_snapshot(source.data_date, project, rows, scope_kind="all", serials=sorted(serials),
                                source_snapshot_at=source.snapshot_at)

    return {
        "subject": subject_for(label, region, source.data_date),
        "projectLabel": label,
        "dataDate": source.data_date.isoformat(),
        "snapshotAt": source.snapshot_at,
        "stale": stale,
        "baseDate": base_date.isoformat() if base_date and mode["show"] else None,
        "summary": _jsonable_summary(current),
        "baseline": _jsonable_summary(base),
        "delta": _jsonable_summary(delta),
        "summaryLines": lines,
        "charts": charts,
        "flows": table,
        "longCycle": {"review": long_cycle["review"], "excluded": long_cycle["excluded"]},
        "exportBlocked": bool(long_cycle["review"]),
        "notices": notices,
        "anomalies": parsed.anomalies,
        "seedVersion": seed_version(),
        "snapshotSaved": bool(save_snapshot and not stale),
    }


def _notices(flows: Sequence[V.Flow], ctx: _Context, charts: Mapping[str, Any],
             long_cycle: Mapping[str, Any], anomalies: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """预览顶部提示，按 §8 顺序：长周期待确认（阻塞导出）、待补录、同名与历史科室、数据异常。"""
    notices: list[dict[str, Any]] = []
    if long_cycle["review"]:
        notices.append({
            "kind": "longCycleReview", "blocking": True,
            "text": f"{len(long_cycle['review'])} 项长周期初筛待确认",
        })
    if charts["needsEntry"]:
        notices.append({
            "kind": "needsEntry", "blocking": False,
            "text": "以下人员未在花名册，请补录：" + "、".join(charts["needsEntry"]), "names": charts["needsEntry"],
        })
    conflict: set[str] = set()
    history: set[str] = set()
    for flow in flows:
        if not flow.in_flight:
            continue
        for _, name in flow.unsigned():
            status = ctx.roster.lookup(name).status
            if status == "conflict":
                conflict.add(name)
            elif status == "history":
                history.add(name)
        department, flagged = V.flow_department(flow, ctx.roster)
        if flagged:
            history.add(f"{flow.serial}（{department}）")
    if conflict:
        notices.append({"kind": "nameConflict", "blocking": False,
                        "text": "花名册里同名不同科室，请到花名册处理：" + "、".join(sorted(conflict))})
    if history:
        notices.append({"kind": "historyDepartment", "blocking": False,
                        "text": "科室是历史值「结构工程科」，请指定现行科室：" + "、".join(sorted(history))})
    if anomalies:
        notices.append({"kind": "anomalies", "blocking": False, "text": f"数据异常 {len(anomalies)} 条，已按规则处理"})
    return notices


def classify_keys(keys: Iterable[str]) -> dict[str, V.Classification]:
    rules, vocab = list(seed_rules()), V.Vocabulary()
    return {key: V.classify_part(key, rules, vocab) for key in keys}


# ── 后台抓取（R1、R3）────────────────────────────────────────────────


def valid_task_id(task_id: str) -> bool:
    return bool(_TASK_ID.match(task_id or ""))


def make_refresh_worker(
    archive: Any,
    db: Any,
    describe_failure: Callable[[Mapping[str, Any]], str],
    *,
    wait_timeout: float = 20 * 60,
    poll_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Any], None]:
    """抓取任务体：调宿主归档任务；若调度器正在抓（租约被占），等它产出的新快照，不重复抓取。"""

    def latest_id() -> int:
        latest = db.get_latest_deliverable_form_snapshot(FORM_KEY)
        return int(latest["id"]) if latest else 0

    def run(task: Any) -> None:
        before = latest_id()
        task.update_progress(stage="正在抓取 TDC 数模设计审核流程", percent=5)
        try:
            result = archive.sync_now(ARCHIVE_JOB_KEY)
        except KeyError:
            raise RuntimeError("未找到 TDC 数模设计审核流程归档任务，请到「自动归档」页检查") from None
        first = (result.get("results") or [{}])[0] if isinstance(result, Mapping) else {}
        if isinstance(result, Mapping) and result.get("exitCode") == 0 and first.get("outcome") == "completed":
            task.update_progress(stage="抓取完成", percent=100)
            return
        if first.get("errorType") == "lease_busy" or first.get("remedy") == "wait_and_retry":
            task.update_progress(stage="已有抓取在运行，等待它完成", percent=10)
            waited = 0.0
            while waited < wait_timeout:
                if task.is_cancelled:
                    return
                if latest_id() > before:
                    task.update_progress(stage="抓取完成", percent=100)
                    return
                sleep(poll_seconds)
                waited += poll_seconds
            raise RuntimeError("等待进行中的抓取超时，请稍后重试")
        raise RuntimeError(describe_failure(result if isinstance(result, Mapping) else {}))

    return run


def task_view(task: Mapping[str, Any]) -> dict[str, Any]:
    try:
        progress = json.loads(task.get("progress_json") or "{}")
    except ValueError:
        progress = {}
    return {
        "taskId": task.get("task_id"),
        "status": task.get("status"),
        "stage": progress.get("stage"),
        "percent": progress.get("percent"),
        "error": task.get("error_message"),
    }
