# -*- coding: utf-8 -*-
"""签署日报 v2.0 配置数据：种子 + 本地改动两层、CSV 导入、备份与回滚（规格 §7 M1–M8）。

- 花名册和长周期规则各有一张本地层表；生效值 = 种子叠加本地改动，同键本地优先（M3）。
- 本地层只记改动：设置、删除标记（种子条目不物理删除，M2）。每条改动记下当时的种子值
  （``seed_base``），种子升级后：与新种子相同的本地改动自动清除；种子和本地都改过的列出来（M4）。
- 整体覆盖导入（M5）后种子层停用（``mode = replace``），直到「恢复内置种子」。
- 导入、批量改动、恢复前自动备份，保留最近 5 份（M6、M7）。
- 花名册只存姓名和科室；导入文件里的工号只用来合并同名行，不落库（R8）。
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from . import rules as V

DATASETS = ("roster", "rules", "vocabulary")
BACKUP_KEEP = 5
MODE_OVERLAY = "overlay"
MODE_REPLACE = "replace"

SOURCE_SEED = "内置"
SOURCE_MODIFIED = "已修改"
SOURCE_LOCAL = "本地新增"
SOURCE_DELETED = "已删除"

RULE_HEADERS = ("规则编号", "零件名称", "备注", "别名", "启用")
ROSTER_HEADERS = ("姓名", "科室")
_TRUE = {"", "1", "是", "启用", "true", "yes", "y"}
_FALSE = {"0", "否", "停用", "false", "no", "n"}


class SettingsError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def csv_text(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def read_csv_text(text: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text))]


# ── 词表 ────────────────────────────────────────────────────────────


def default_vocabulary() -> dict[str, Any]:
    return {
        "globalExcludes": list(V.DEFAULT_GLOBAL_EXCLUDES),
        "synonyms": {canonical: list(aliases) for canonical, aliases in V.DEFAULT_SYNONYMS.items()},
        "orientation": V.ORIENTATION_CHARS,
        "suffixes": list(V.DEFAULT_SUFFIXES),
    }


def _words(value: Any, name: str, limit: int = 200) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise SettingsError(f"{name} 必须是不超过 {limit} 项的文本数组")
    words = []
    for item in value:
        if not isinstance(item, str) or len(item) > 50:
            raise SettingsError(f"{name} 每项必须是不超过 50 字的文本")
        word = item.strip()
        if word and word not in words:
            words.append(word)
    return words


def validate_vocabulary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SettingsError("词表必须是对象")
    synonyms_in = value.get("synonyms")
    if not isinstance(synonyms_in, Mapping) or len(synonyms_in) > 200:
        raise SettingsError("同义词表必须是不超过 200 项的对象")
    synonyms = {}
    for canonical, aliases in synonyms_in.items():
        key = str(canonical).strip()
        if not key or len(key) > 50:
            raise SettingsError("规范词不能为空且不超过 50 字")
        synonyms[key] = _words(aliases, f"「{key}」的别名", 50)
    orientation = value.get("orientation")
    if not isinstance(orientation, str) or not orientation.strip() or len(orientation) > 20:
        raise SettingsError("方位字必须是 1–20 个字")
    return {
        "globalExcludes": _words(value.get("globalExcludes"), "全局排除词"),
        "synonyms": synonyms,
        "orientation": "".join(dict.fromkeys(orientation.strip())),
        "suffixes": _words(value.get("suffixes"), "后缀白名单"),
    }


def to_vocabulary(value: Mapping[str, Any]) -> V.Vocabulary:
    return V.Vocabulary(
        global_excludes=tuple(value["globalExcludes"]),
        synonyms={k: tuple(v) for k, v in value["synonyms"].items()},
        orientation=value["orientation"],
        suffixes=tuple(value["suffixes"]),
    )


# ── 存储 ────────────────────────────────────────────────────────────


class SettingsStore:
    def __init__(self, db: Any, prefix: str, seed_roster: Sequence[tuple[str, str]],
                 seed_rules: Sequence[Mapping[str, Any]]):
        self.db = db
        self.roster_table = f"{prefix}roster_local"
        self.rules_table = f"{prefix}rule_local"
        self.backup_table = f"{prefix}settings_backup"
        self.kv_table = f"{prefix}settings_kv"
        self.seed_roster = {name: department for name, department in seed_roster}
        self.seed_rules = {row["id"]: dict(row) for row in seed_rules}

    def migration(self) -> tuple[int, Any]:
        def v3(conn) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.roster_table} ("
                "name TEXT PRIMARY KEY NOT NULL, department TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, "
                "seed_base TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.rules_table} ("
                "rule_id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, remark TEXT NOT NULL DEFAULT '', "
                "aliases TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, "
                "deleted INTEGER NOT NULL DEFAULT 0, seed_base TEXT NOT NULL DEFAULT '', "
                "note TEXT NOT NULL DEFAULT '', "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.backup_table} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, dataset TEXT NOT NULL, reason TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.kv_table} ("
                "key TEXT PRIMARY KEY NOT NULL, value_json TEXT NOT NULL)"
            )

        return (3, v3)

    # KV：数据集模式、词表

    def _kv(self, conn: Any, key: str, default: Any) -> Any:
        row = conn.execute(f"SELECT value_json FROM {self.kv_table} WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def _set_kv(self, conn: Any, key: str, value: Any) -> None:
        conn.execute(
            f"INSERT INTO {self.kv_table} (key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (key, _json(value)),
        )

    def mode(self, dataset: str) -> str:
        with self.db.get_connection() as conn:
            return self._kv(conn, f"mode:{dataset}", MODE_OVERLAY)

    def vocabulary(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            return self._kv(conn, "vocabulary", None) or default_vocabulary()

    def save_vocabulary(self, value: Mapping[str, Any] | None, reason: str) -> None:
        with self.db.get_connection() as conn:
            self._backup(conn, "vocabulary", reason)
            if value is None:
                conn.execute(f"DELETE FROM {self.kv_table} WHERE key = 'vocabulary'")
            else:
                self._set_kv(conn, "vocabulary", value)

    # 本地层读写

    def _roster_local(self, conn: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(
            f"SELECT name, department, deleted, seed_base, note, updated_at FROM {self.roster_table} ORDER BY name"
        )]

    def _rules_local(self, conn: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(
            f"SELECT rule_id, name, remark, aliases, enabled, deleted, seed_base, note, updated_at "
            f"FROM {self.rules_table} ORDER BY rule_id"
        )]

    def _local(self, conn: Any, dataset: str) -> list[dict[str, Any]]:
        return self._roster_local(conn) if dataset == "roster" else self._rules_local(conn)

    def _snapshot(self, conn: Any, dataset: str) -> dict[str, Any]:
        if dataset == "vocabulary":
            return {"vocabulary": self._kv(conn, "vocabulary", None)}
        return {"mode": self._kv(conn, f"mode:{dataset}", MODE_OVERLAY), "local": self._local(conn, dataset)}

    def _backup(self, conn: Any, dataset: str, reason: str) -> None:
        conn.execute(
            f"INSERT INTO {self.backup_table} (dataset, reason, payload_json) VALUES (?, ?, ?)",
            (dataset, reason, _json(self._snapshot(conn, dataset))),
        )
        conn.execute(
            f"DELETE FROM {self.backup_table} WHERE dataset = ? AND id NOT IN "
            f"(SELECT id FROM {self.backup_table} WHERE dataset = ? ORDER BY id DESC LIMIT ?)",
            (dataset, dataset, BACKUP_KEEP),
        )

    def backups(self, dataset: str) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [
                {"id": row["id"], "reason": row["reason"], "createdAt": row["created_at"]}
                for row in conn.execute(
                    f"SELECT id, reason, created_at FROM {self.backup_table} WHERE dataset = ? ORDER BY id DESC",
                    (dataset,),
                )
            ]

    def restore(self, dataset: str, backup_id: int) -> None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT payload_json FROM {self.backup_table} WHERE dataset = ? AND id = ?", (dataset, backup_id)
            ).fetchone()
            if row is None:
                raise SettingsError("没有这份备份")
            payload = json.loads(row["payload_json"])
            self._backup(conn, dataset, f"恢复备份 #{backup_id} 前")
            if dataset == "vocabulary":
                if payload.get("vocabulary") is None:
                    conn.execute(f"DELETE FROM {self.kv_table} WHERE key = 'vocabulary'")
                else:
                    self._set_kv(conn, "vocabulary", payload["vocabulary"])
                return
            self._replace_local(conn, dataset, payload.get("mode") or MODE_OVERLAY, payload.get("local") or [])

    def _replace_local(self, conn: Any, dataset: str, mode: str, rows: Sequence[Mapping[str, Any]]) -> None:
        self._set_kv(conn, f"mode:{dataset}", mode)
        if dataset == "roster":
            conn.execute(f"DELETE FROM {self.roster_table}")
            conn.executemany(
                f"INSERT INTO {self.roster_table} (name, department, deleted, seed_base, note) VALUES (?, ?, ?, ?, ?)",
                [(r["name"], r["department"], int(r.get("deleted") or 0), r.get("seed_base") or "", r.get("note") or "")
                 for r in rows],
            )
        else:
            conn.execute(f"DELETE FROM {self.rules_table}")
            conn.executemany(
                f"INSERT INTO {self.rules_table} (rule_id, name, remark, aliases, enabled, deleted, seed_base, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(r["rule_id"], r["name"], r.get("remark") or "", r.get("aliases") or "", int(r.get("enabled", 1)),
                  int(r.get("deleted") or 0), r.get("seed_base") or "", r.get("note") or "") for r in rows],
            )

    def reset_seed(self, dataset: str) -> None:
        """恢复内置种子：清空本地层并重新启用种子（先备份）。"""
        with self.db.get_connection() as conn:
            self._backup(conn, dataset, "恢复内置种子前")
            if dataset == "vocabulary":
                conn.execute(f"DELETE FROM {self.kv_table} WHERE key = 'vocabulary'")
            else:
                self._replace_local(conn, dataset, MODE_OVERLAY, [])

    # ── 花名册 ──────────────────────────────────────────────────────

    def reconcile(self) -> dict[str, list[dict[str, Any]]]:
        """M4：与当前种子相同的本地改动自动清除；种子和本地都改过的列出来（本地优先）。"""
        conflicts: dict[str, list[dict[str, Any]]] = {"roster": [], "rules": []}
        with self.db.get_connection() as conn:
            if self._kv(conn, "mode:roster", MODE_OVERLAY) == MODE_OVERLAY:
                for row in self._roster_local(conn):
                    seed = self.seed_roster.get(row["name"], "")
                    same = (not row["deleted"] and row["department"] == seed) or (row["deleted"] and not seed)
                    if same:
                        conn.execute(f"DELETE FROM {self.roster_table} WHERE name = ?", (row["name"],))
                    elif seed != row["seed_base"]:
                        conflicts["roster"].append({"key": row["name"], "seed": seed, "seedBase": row["seed_base"],
                                                    "local": "" if row["deleted"] else row["department"]})
            if self._kv(conn, "mode:rules", MODE_OVERLAY) == MODE_OVERLAY:
                for row in self._rules_local(conn):
                    seed = self.seed_rules.get(row["rule_id"])
                    seed_json = _json(_rule_fields(seed)) if seed else ""
                    local_json = "" if row["deleted"] else _json(_rule_fields(row))
                    if local_json == seed_json:
                        conn.execute(f"DELETE FROM {self.rules_table} WHERE rule_id = ?", (row["rule_id"],))
                    elif seed_json != row["seed_base"]:
                        conflicts["rules"].append({"key": row["rule_id"], "seed": seed_json, "local": local_json})
        return conflicts

    def roster_rows(self) -> list[dict[str, Any]]:
        """设置页列表：每行带来源；已删除的种子条目也列出来，但不生效。"""
        with self.db.get_connection() as conn:
            mode = self._kv(conn, "mode:roster", MODE_OVERLAY)
            local = {row["name"]: row for row in self._roster_local(conn)}
        rows: dict[str, dict[str, Any]] = {}
        if mode == MODE_OVERLAY:
            for name, department in self.seed_roster.items():
                rows[name] = {"name": name, "department": department, "source": SOURCE_SEED}
        for name, row in local.items():
            seeded = mode == MODE_OVERLAY and name in self.seed_roster
            if row["deleted"]:
                if seeded:
                    rows[name] = {"name": name, "department": self.seed_roster[name], "source": SOURCE_DELETED}
                continue
            rows[name] = {"name": name, "department": row["department"],
                          "source": SOURCE_MODIFIED if seeded else SOURCE_LOCAL, "note": row["note"]}
        return sorted(rows.values(), key=lambda r: (r["department"], r["name"]))

    def roster(self) -> list[tuple[str, str]]:
        return [(r["name"], r["department"]) for r in self.roster_rows() if r["source"] != SOURCE_DELETED]

    def set_person(self, name: str, department: str | None, note: str = "") -> None:
        """单条新增或修改（department 为科室）、删除（department 为 None）。只写本地层（M2）。"""
        with self.db.get_connection() as conn:
            seed = self.seed_roster.get(name, "") if self._kv(conn, "mode:roster", MODE_OVERLAY) == MODE_OVERLAY else ""
            conn.execute(
                f"INSERT INTO {self.roster_table} (name, department, deleted, seed_base, note) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET department = excluded.department, deleted = excluded.deleted, "
                "seed_base = excluded.seed_base, note = excluded.note, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (name, department or "", 0 if department else 1, seed, note),
            )
            if department is None and not seed:
                conn.execute(f"DELETE FROM {self.roster_table} WHERE name = ?", (name,))

    def revert_person(self, name: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(f"DELETE FROM {self.roster_table} WHERE name = ?", (name,))

    def roster_import_plan(self, source: str | Sequence[Sequence[Any]], replace: bool) -> dict[str, Any]:
        """source 是 CSV 原文，或已读出的表格行（xlsx）。"""
        parsed = V.parse_roster_table(read_csv_text(source) if isinstance(source, str) else source)
        current = {name: department for name, department in self.roster()}
        incoming = {e["name"]: e["department"] for e in parsed["entries"]}
        added = [{"name": n, "department": d} for n, d in incoming.items() if n not in current]
        changed = [{"name": n, "from": current[n], "to": d} for n, d in incoming.items() if n in current and current[n] != d]
        removed = [{"name": n, "department": d} for n, d in current.items() if replace and n not in incoming]
        return {
            "mode": MODE_REPLACE if replace else "merge",
            "added": added, "changed": changed, "removed": removed,
            "conflicts": parsed["conflicts"], "errors": parsed["errors"], "merged": parsed["merged"],
            "entries": [(e["name"], e["department"]) for e in parsed["entries"]],
        }

    def commit_roster_import(self, plan: Mapping[str, Any]) -> None:
        with self.db.get_connection() as conn:
            self._backup(conn, "roster", "导入前")
            if plan["mode"] == MODE_REPLACE:
                rows = [{"name": n, "department": d} for n, d in plan["entries"]]
                self._replace_local(conn, "roster", MODE_REPLACE, rows)
                return
            overlay = self._kv(conn, "mode:roster", MODE_OVERLAY) == MODE_OVERLAY
            for item in [*plan["added"], *({"name": c["name"], "department": c["to"]} for c in plan["changed"])]:
                seed = self.seed_roster.get(item["name"], "") if overlay else ""
                conn.execute(
                    f"INSERT INTO {self.roster_table} (name, department, deleted, seed_base, note) "
                    "VALUES (?, ?, 0, ?, '导入') ON CONFLICT(name) DO UPDATE SET department = excluded.department, "
                    "deleted = 0, seed_base = excluded.seed_base, note = excluded.note, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                    (item["name"], item["department"], seed),
                )

    def roster_csv(self) -> str:
        return csv_text(ROSTER_HEADERS, self.roster())

    # ── 长周期规则 ──────────────────────────────────────────────────

    def rule_rows(self) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            mode = self._kv(conn, "mode:rules", MODE_OVERLAY)
            local = {row["rule_id"]: row for row in self._rules_local(conn)}
        rows: dict[str, dict[str, Any]] = {}
        if mode == MODE_OVERLAY:
            for rule_id, seed in self.seed_rules.items():
                rows[rule_id] = {**_rule_fields(seed), "id": rule_id, "source": SOURCE_SEED}
        for rule_id, row in local.items():
            seeded = mode == MODE_OVERLAY and rule_id in self.seed_rules
            if row["deleted"]:
                if seeded:
                    rows[rule_id] = {**_rule_fields(self.seed_rules[rule_id]), "id": rule_id, "source": SOURCE_DELETED}
                continue
            rows[rule_id] = {**_rule_fields(row), "id": rule_id,
                             "source": SOURCE_MODIFIED if seeded else SOURCE_LOCAL, "note": row["note"]}
        return sorted(rows.values(), key=lambda r: _rule_sort_key(r["id"]))

    def rules(self, vocab: V.Vocabulary) -> list[V.LongCycleRule]:
        result = []
        for row in self.rule_rows():
            if row["source"] == SOURCE_DELETED or not row["enabled"]:
                continue
            aliases = [a for a in re.split(r"[、,，;；]+", row["aliases"]) if a.strip()]
            rule = V.build_rule(row["id"], row["name"], row["remark"], vocab, aliases)
            if rule.core_groups:
                result.append(rule)
        return result

    def set_rule(self, rule_id: str, fields: Mapping[str, Any] | None, note: str = "") -> None:
        """单条新增或修改（fields）、删除（None）。只写本地层；种子条目记删除标记。"""
        with self.db.get_connection() as conn:
            self._set_rule(conn, rule_id, fields, note)

    def _set_rule(self, conn: Any, rule_id: str, fields: Mapping[str, Any] | None, note: str) -> None:
        overlay = self._kv(conn, "mode:rules", MODE_OVERLAY) == MODE_OVERLAY
        seed = self.seed_rules.get(rule_id) if overlay else None
        seed_base = _json(_rule_fields(seed)) if seed else ""
        if fields is None and not seed:
            conn.execute(f"DELETE FROM {self.rules_table} WHERE rule_id = ?", (rule_id,))
            return
        values = _rule_fields(fields or seed or {})
        conn.execute(
            f"INSERT INTO {self.rules_table} (rule_id, name, remark, aliases, enabled, deleted, seed_base, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(rule_id) DO UPDATE SET name = excluded.name, "
            "remark = excluded.remark, aliases = excluded.aliases, enabled = excluded.enabled, "
            "deleted = excluded.deleted, seed_base = excluded.seed_base, note = excluded.note, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            (rule_id, values["name"], values["remark"], values["aliases"], int(values["enabled"]),
             0 if fields is not None else 1, seed_base, note),
        )

    def revert_rule(self, rule_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(f"DELETE FROM {self.rules_table} WHERE rule_id = ?", (rule_id,))

    def next_rule_id(self) -> str:
        used = {row["id"] for row in self.rule_rows()} | set(self.seed_rules)
        with self.db.get_connection() as conn:
            used |= {row["rule_id"] for row in self._rules_local(conn)}
        number = 1
        while f"LC{number:02d}" in used:
            number += 1
        return f"LC{number:02d}"

    def rules_import_plan(self, source: str | Sequence[Sequence[Any]], replace: bool,
                          vocab: V.Vocabulary) -> dict[str, Any]:
        parsed = parse_rule_table(read_csv_text(source) if isinstance(source, str) else source, vocab)
        current = {row["id"]: row for row in self.rule_rows() if row["source"] != SOURCE_DELETED}
        by_name = {row["name"]: rule_id for rule_id, row in current.items()}
        # 文件里显式写的编号先占位，空编号行分配时不会撞上后面的显式编号。
        used = set(current) | set(self.seed_rules) | {item["id"] for item in parsed["rows"] if item["id"]}
        entries = []
        for item in parsed["rows"]:
            rule_id = item["id"] or by_name.get(item["name"]) or ""
            if not rule_id:
                number = 1
                while f"LC{number:02d}" in used:
                    number += 1
                rule_id = f"LC{number:02d}"
            used.add(rule_id)
            entries.append({**item, "id": rule_id})
        incoming = {e["id"]: e for e in entries}
        added = [e for e in entries if e["id"] not in current]
        changed = [
            {"id": e["id"], "from": _rule_fields(current[e["id"]]), "to": _rule_fields(e)}
            for e in entries if e["id"] in current and _rule_fields(current[e["id"]]) != _rule_fields(e)
        ]
        removed = [row for rule_id, row in current.items() if replace and rule_id not in incoming]
        return {"mode": MODE_REPLACE if replace else "merge", "added": added, "changed": changed,
                "removed": removed, "conflicts": [], "errors": parsed["errors"], "entries": entries}

    def commit_rules_import(self, plan: Mapping[str, Any]) -> None:
        with self.db.get_connection() as conn:
            self._backup(conn, "rules", "导入前")
            if plan["mode"] == MODE_REPLACE:
                rows = [{"rule_id": e["id"], **_rule_fields(e)} for e in plan["entries"]]
                self._replace_local(conn, "rules", MODE_REPLACE, rows)
                return
            for item in [*plan["added"], *({"id": c["id"], **c["to"]} for c in plan["changed"])]:
                self._set_rule(conn, item["id"], item, "导入")

    def rules_csv(self) -> str:
        return csv_text(RULE_HEADERS, [
            (r["id"], r["name"], r["remark"], r["aliases"], "启用" if r["enabled"] else "停用")
            for r in self.rule_rows() if r["source"] != SOURCE_DELETED
        ])


def _rule_fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        "name": str(row.get("name") or "").strip(),
        "remark": str(row.get("remark") or "").strip(),
        "aliases": str(row.get("aliases") or "").strip(),
        "enabled": bool(row.get("enabled", True)),
    }


def _rule_sort_key(rule_id: str) -> tuple[int, str]:
    match = re.match(r"^LC(\d+)$", rule_id)
    return (int(match.group(1)), "") if match else (10 ** 6, rule_id)


def parse_rule_table(rows: Sequence[Sequence[Any]], vocab: V.Vocabulary) -> dict[str, Any]:
    """长周期清单 CSV -> 行（规则编号可空）。要有「零件名称」「备注」；可选「别名」「启用」「规则编号」。"""
    if not rows:
        return {"rows": [], "errors": [{"line": 1, "text": "文件为空"}]}
    header = [re.sub(r"\s+", "", V.halfwidth(V.cell_text(h))) for h in rows[0]]

    def col(name: str) -> int | None:
        return header.index(name) if name in header else None

    name_col, remark_col = col("零件名称"), col("备注")
    if name_col is None or remark_col is None:
        return {"rows": [], "errors": [{"line": 1, "text": "表头要有「零件名称」「备注」"}]}
    alias_col, enabled_col, id_col = col("别名"), col("启用"), col("规则编号")
    out, errors, seen_ids = [], [], set()

    def cell(row: Sequence[Any], index: int | None) -> str:
        return V.cell_text(row[index]) if index is not None and index < len(row) else ""

    for line, row in enumerate(rows[1:], start=2):
        name = cell(row, name_col)
        if not name:
            continue
        rule_id = cell(row, id_col)
        if rule_id and (not re.match(r"^[A-Za-z0-9_-]{1,20}$", rule_id) or rule_id in seen_ids):
            errors.append({"line": line, "text": f"规则编号「{rule_id}」无效或重复"})
            continue
        flag = cell(row, enabled_col).lower()
        if flag not in _TRUE and flag not in _FALSE:
            errors.append({"line": line, "text": f"「启用」列只能填 启用/停用，现在是「{flag}」"})
            continue
        item = {"id": rule_id, "name": name, "remark": cell(row, remark_col),
                "aliases": cell(row, alias_col), "enabled": flag not in _FALSE}
        aliases = [a for a in re.split(r"[、,，;；]+", item["aliases"]) if a.strip()]
        if not V.build_rule("x", name, item["remark"], vocab, aliases).core_groups:
            errors.append({"line": line, "text": f"「{name}」规范化后没有核心词"})
            continue
        if rule_id:
            seen_ids.add(rule_id)
        out.append(item)
    return {"rows": out, "errors": errors}
