# B′ P1a 实施参考补丁（Claude 审阅者提供，已在云端副本验证）

## 来源与验证边界
- 基线：E:\project\vse-toolbox 当前工作区（commit 3a270a5 之后、测试已提交前的状态）；以下 4 个源文件的基线与本机文件逐字节一致（cmp 校验）。
- 云端副本（Linux, Python 3.13, pytest 9.1.1）验证结果：
  - `tests/test_bprime_config_audit_*.py`（14 节点）+ `tests/test_project_status_updates.py`（31）= 45 passed。
  - 扩大回归（同一副本加入 test_archive_jobs / test_archive_admin / test_db_manager / test_project_status_sync_runner / test_project_status_sync_runs / test_project_status_aggregate_sync / test_ewo_v2_integration / test_ewo_binding_v2 / test_project_status_scheduler / test_scheduled_archive_admin / test_scheduled_archive_runner / test_project_status_connectors / test_project_status_contracts）= 498 passed。
  - 云端结果不是本机证据；最终验收必须在本机跑真实 pytest。
- 行尾：本机文件为 CRLF；补丁以 LF 展示（diff --strip-trailing-cr）。按片段 edit 即可，不要整文件重写。

## 冻结测试里发现的两处夹具缺陷（需要一张测试修复卡）
这两处只在真实运行时暴露（collect-only 验收看不出来）：
- TD-2 `tests/test_bprime_config_audit_isolation.py` 第 10 行：`mapping["progress"] = ...`。服务层校验只允许映射键 owner/plannedDate/note（`PROJECT_STATUS_AUTOMATIC_API_FIELDS`），保存直接抛 ProjectStatusPolicyError，测不到"零写入"。改为 `mapping["plannedDate"] = "SYNTHETIC_MARKER_1"`（仍有两个键，倒序断言仍成立）。
- TD-3 `tests/test_bprime_config_audit_noarchive.py`：断言 VPI-T2-D5 没有关联归档任务，但 init_database 的 `_seed_archive_jobs` 会种入 `tdc_data_model`（project_status_deliverable_id = VPI-T2-D5）。在计数前先解除关联（见下方补丁）。
- 其余 12 个节点与 conftest.py 不改。

## 实现要点（对应冻结契约 A11）
1. 新模块 `core/project_status_config_audit.py`：表结构（CHECK/AUTOINCREMENT/created_at 默认值与 isolation_schema 测试逐字一致）、`ensure_binding_config_audit_schema(conn)`（事务内调用即抛 BindingConfigAuditError；自身 BEGIN IMMEDIATE / COMMIT 各一次）、`BindingConfigAuditError(RuntimeError)`、载荷构造与递归脱敏（按原始值判差异，from/to 脱敏，changed 恒 True）。
2. `core/db_manager.py`：init_database 的初始化事务结束后，单独一个连接调用一次 ensure（不改 user_version=14）。
3. `core/repos/archive_jobs.py`：`record_deliverable_config_audit(self, deliverable_id, changes, actor='local_web', *, conn) -> bool`，在调用方连接上 INSERT 一行、不提交，修订号取 `changes["afterRevision"]`，与归档任务解耦。recorder 收到的 `changes` 就是完整载荷。
4. `core/repos/project_status.py`：
   - `_ensure_project_status_policy` 改为先读后写：已齐备时不发任何 DML（否则 get_policy 的 INSERT OR IGNORE 会破坏"无差异零写入"）。
   - `set_project_status_update_policy`：BEGIN IMMEDIATE 内读变更前状态（并发测试要求读到 P1）；JSON 列按解析后比较（键序无关）；无差异直接返回原修订号（零 DML、不调 recorder）；有差异时只写变化的绑定列与变化的字段归属行；目标变化（mode/externalKey/matchRule/mapping）修订号 +1、清 cursor 与分析缓存；同一连接调用 recorder(…, conn=conn)，再核对恰好新增一行且内容与载荷一致，否则抛 BindingConfigAuditError（异常链保留原异常，消息不含原文）。
   - 新增仅关键字参数 `actor='local_web'`、`audit_field_names=None`。原因：冻结测试里直接调用仓储（并发测试）期望 fieldAuthority 用列名（planned_date/remark），经服务层调用（changes/mixed）期望 API 名（plannedDate/note）；服务层传 `PROJECT_STATUS_FIELD_NAME_TO_API` 做翻译。凭据别名不进审计，只记 credentialConfigured。
5. `services/project_status_updates.py`：删除保存后的 `_audit_policy_change`（含方法本身），调用仓储时传 actor 与 audit_field_names；update_update_policy 增加仅关键字参数 actor（默认 local_web）。
6. 其他调用方：`services/project_status_sync_runner.py:855` 直接调用 set_project_status_update_policy（自动锚点），改后也会在同一事务记一条审计（字段归属键为列名），无需改代码；`web/app.py:5220` 的 PATCH 路由对 BindingConfigAuditError 走既有的 500 分支。

## 建议拆卡（每张 ≤3 文件；每个文件按片段 edit，新文件一次 write）
- IMPL-1：新建 core/project_status_config_audit.py（write）+ core/db_manager.py（2 处 edit）。验收：isolation_schema、fixture_state、fixture_trace 3 节点。
- IMPL-2：core/repos/project_status.py（5 处 edit，对应下方 5 个 hunk）+ core/repos/archive_jobs.py（1 处 edit）。依赖 IMPL-1。
- IMPL-3：services/project_status_updates.py（3 处 edit）。依赖 IMPL-2。
- TESTFIX：两个测试文件各 1 处 edit（tests-only）。
- 总验收：14 个 bprime 节点 + tests/test_project_status_updates.py 31 节点全过，再加上面扩大回归列表。

## 新文件 core/project_status_config_audit.py（sha256 前16位 9d00c7553de1fb05）
```python
# -*- coding: utf-8 -*-
"""交付物同步绑定配置审计（B′ P1a）：专用审计表结构与审计载荷构造。

审计行与绑定/字段归属写入同处 ``set_project_status_update_policy`` 的事务；
记录器失败时整笔回滚并抛出 ``BindingConfigAuditError``。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from core.redaction import redact_sensitive_text

BINDING_CONFIG_AUDIT_TABLE = "project_status_binding_config_audit"
BINDING_CONFIG_AUDIT_EVENT = "configuration_updated"
BINDING_CONFIG_AUDIT_ACTORS = frozenset({"local_web", "cli"})
BINDING_CONFIG_AUDIT_PAYLOAD_VERSION = 1
BINDING_CONFIG_AUDIT_SOURCE = "deliverable_sync_settings"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS project_status_binding_config_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deliverable_id TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('local_web', 'cli')),
    event_type TEXT NOT NULL CHECK (event_type IN ('configuration_updated')),
    config_revision INTEGER NOT NULL CHECK (config_revision >= 0),
    changes_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_project_status_binding_config_audit_deliverable
ON project_status_binding_config_audit (deliverable_id, id)
"""


class BindingConfigAuditError(RuntimeError):
    """绑定配置审计无法写入或无法确认写入；调用方的事务必须整体回滚。"""


def ensure_binding_config_audit_schema(conn: sqlite3.Connection) -> None:
    """幂等创建专用审计表；必须在调用方事务之外调用，自身开启并提交一次事务。"""
    if conn.in_transaction:
        raise BindingConfigAuditError("binding config audit schema requires no open transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def sanitize_audit_value(value: Any) -> Any:
    """递归脱敏审计值：字符串走 redact_sensitive_text，容器逐项处理，其余原样保留。"""
    if isinstance(value, str):
        return redact_sensitive_text(value, limit=1000)
    if isinstance(value, list):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_audit_value(item) for key, item in value.items()}
    return value


def build_binding_config_audit_payload(
    deliverable_id: str,
    before_revision: int,
    after_revision: int,
    changes: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    """按原始值判定差异后构造载荷；from/to 脱敏，changed 恒为 True（脱敏后相等也保留）。"""
    return {
        "payloadVersion": BINDING_CONFIG_AUDIT_PAYLOAD_VERSION,
        "source": BINDING_CONFIG_AUDIT_SOURCE,
        "deliverableId": deliverable_id,
        "beforeRevision": int(before_revision),
        "afterRevision": int(after_revision),
        "scope": None,
        "changes": {
            name: {
                "from": sanitize_audit_value(old),
                "to": sanitize_audit_value(new),
                "changed": True,
            }
            for name, (old, new) in changes.items()
        },
    }
```

## 补丁 db_manager
```diff
--- db_manager.orig.py	2026-10-17 19:03:47.795173855 +0800
+++ vt/core/db_manager.py	2026-10-17 19:03:53.220962646 +0800
@@ -85,6 +85,7 @@
     SyncLeaseLostError,
     TABLE_DEFINITIONS,
 )
+from core.project_status_config_audit import ensure_binding_config_audit_schema
 from core.repos.archive_jobs import ArchiveRepo
 from core.repos.crawl_tasks import CrawlTaskRepo
 from core.repos.form_snapshots import FormSnapshotRepo
@@ -166,6 +167,10 @@
 
                 conn.commit()
 
+            # B′ 绑定配置审计表：在上面的初始化事务结束后单独建表（自带 BEGIN IMMEDIATE/COMMIT）。
+            with self.get_connection() as conn:
+                ensure_binding_config_audit_schema(conn)
+
             logger.info("数据库初始化完成")
 
         except sqlite3.Error:
```

## 补丁 archive_jobs
```diff
--- archive_jobs.orig.py	2026-10-17 19:05:23.517732554 +0800
+++ vt/core/repos/archive_jobs.py	2026-10-17 19:05:23.536318441 +0800
@@ -237,36 +237,28 @@
         deliverable_id: str,
         changes: Mapping[str, object],
         actor: str = "local_web",
+        *,
+        conn: sqlite3.Connection,
     ) -> bool:
-        """把交付物同步设置的改动写进其归档任务的配置审计（签署日报规格 §9 S21）。
+        """在调用方的连接与事务内写入一行绑定配置审计（B′ P1a），不提交。
 
-        交付物与归档任务按 project_status_deliverable_id 关联；没有关联任务时返回 False。
-        changes 只放非敏感字段（凭据只记是否配置，不记别名）。
+        ``changes`` 是完整审计载荷（payloadVersion/source/.../changes），已由调用方脱敏；
+        修订号取 ``changes["afterRevision"]``。与归档任务解耦：没有关联归档任务也照常记录。
         """
         if actor not in {"local_web", "cli"}:
-            raise ValueError("archive configuration actor is invalid")
+            raise ValueError("binding configuration actor is invalid")
+        revision = changes.get("afterRevision")
+        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
+            raise ValueError("binding configuration revision is invalid")
         changes_json = json.dumps(
             dict(changes), ensure_ascii=False, sort_keys=True, separators=(",", ":")
         )
-        with self.get_connection() as conn:
-            row = conn.execute(
-                """
-                SELECT id, job_key FROM scheduled_archive_jobs
-                WHERE project_status_deliverable_id = ? AND archived_at IS NULL
-                ORDER BY id LIMIT 1
-                """,
-                (deliverable_id,),
-            ).fetchone()
-            if row is None:
-                return False
-            conn.execute(
-                """
-                INSERT INTO scheduled_archive_config_audit
-                    (job_id, job_key, actor, event_type, changes_json)
-                VALUES (?, ?, ?, 'configuration_updated', ?)
-                """,
-                (int(row["id"]), str(row["job_key"]), actor, changes_json),
-            )
+        conn.execute(
+            "INSERT INTO project_status_binding_config_audit "
+            "(deliverable_id, actor, event_type, config_revision, changes_json) "
+            "VALUES (?, ?, 'configuration_updated', ?, ?)",
+            (deliverable_id, actor, revision, changes_json),
+        )
         return True
 
     def list_archive_jobs(
```

## 补丁 project_status
```diff
--- project_status.orig.py	2026-10-17 19:04:32.472872080 +0800
+++ vt/core/repos/project_status.py	2026-10-17 19:05:07.795115239 +0800
@@ -20,6 +20,20 @@
     Sequence,
     sqlite3,
 )
+from core.project_status_config_audit import (
+    BindingConfigAuditError,
+    build_binding_config_audit_payload,
+)
+
+
+def _parse_policy_json(value: Any) -> Any:
+    """解析绑定 JSON 列用于语义比较（键序无关）；空值或坏 JSON 视为 {}。"""
+    if not isinstance(value, str) or not value:
+        return {}
+    try:
+        return json.loads(value)
+    except (TypeError, ValueError):
+        return {}
 
 
 class ProjectStatusRepo:
@@ -534,25 +548,37 @@
         capabilities = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {})
         source_type = str(capabilities.get("sourceType") or "none")
         mode = "automatic" if capabilities.get("syncCapable") else "manual"
-        conn.execute(
-            """
-            INSERT OR IGNORE INTO project_status_update_bindings
-                (deliverable_id, mode, source_type, enabled, sync_state)
-            VALUES (?, ?, ?, 0, 'idle')
-            """,
-            (deliverable_id, mode, source_type),
-        )
-        conn.executemany(
-            """
-            INSERT OR IGNORE INTO project_status_field_authority
-                (deliverable_id, field_name, authority, source_type)
-            VALUES (?, ?, 'manual', ?)
-            """,
-            [
-                (deliverable_id, field_name, source_type)
-                for field_name in PROJECT_STATUS_EDITABLE_FIELDS
-            ],
-        )
+        # 先读后写：已齐备时不发任何 DML（B′ P1a 无差异保存零写入）。
+        has_binding = conn.execute(
+            "SELECT 1 FROM project_status_update_bindings WHERE deliverable_id = ?",
+            (deliverable_id,),
+        ).fetchone() is not None
+        if not has_binding:
+            conn.execute(
+                """
+                INSERT OR IGNORE INTO project_status_update_bindings
+                    (deliverable_id, mode, source_type, enabled, sync_state)
+                VALUES (?, ?, ?, 0, 'idle')
+                """,
+                (deliverable_id, mode, source_type),
+            )
+        present = {
+            row[0]
+            for row in conn.execute(
+                "SELECT field_name FROM project_status_field_authority WHERE deliverable_id = ?",
+                (deliverable_id,),
+            ).fetchall()
+        }
+        missing = [name for name in PROJECT_STATUS_EDITABLE_FIELDS if name not in present]
+        if missing:
+            conn.executemany(
+                """
+                INSERT OR IGNORE INTO project_status_field_authority
+                    (deliverable_id, field_name, authority, source_type)
+                VALUES (?, ?, 'manual', ?)
+                """,
+                [(deliverable_id, field_name, source_type) for field_name in missing],
+            )
 
     @staticmethod
     def _prune_project_status_audit(
@@ -702,12 +728,21 @@
         credential_ref: str | None = None,
         interval_minutes: int | None = 60,
         expected_sync_config_revision: int | None = None,
+        *,
+        actor: str = "local_web",
+        audit_field_names: Mapping[str, str] | None = None,
     ) -> int:
-        """原子写入绑定与字段归属，自动归属同时解除人工锁。
+        """原子写入绑定、字段归属与绑定配置审计，自动归属同时解除人工锁。
 
         同步配置修订号（GPT 终审任务 2）：匹配规则、稳定键、映射或模式变化时
         在本事务内 +1 并清空分析快照/明细缓存（旧车型数据隔离）；仅改
-        interval/credential 不递增、不清缓存。返回递增后的修订号。
+        interval/credential/enabled/字段归属不递增、不清缓存。
+
+        B′ P1a：变更前状态在 BEGIN IMMEDIATE 内读取；与请求无差异时零写入、不审计；
+        有差异时在同一连接、同一事务内调用 ``record_deliverable_config_audit(..., conn=conn)``，
+        并核对恰好新增一行匹配的审计记录，否则抛出 ``BindingConfigAuditError`` 整笔回滚。
+        ``audit_field_names`` 把字段归属的列名翻译成审计载荷里的字段名（服务层传 API 名）。
+        返回保存后的修订号。
         """
         unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
         if unknown:
@@ -723,39 +758,92 @@
             self._ensure_project_status_policy(conn, deliverable_id)
             old_binding = conn.execute(
                 """
-                SELECT mode, external_key, match_rule_json, mapping_json,
-                       sync_config_revision
+                SELECT mode, enabled, external_key, match_rule_json, mapping_json,
+                       credential_ref, interval_minutes, sync_config_revision
                 FROM project_status_update_bindings
                 WHERE deliverable_id = ?
                 """,
                 (deliverable_id,),
             ).fetchone()
+            old_revision = int(old_binding['sync_config_revision'] or 0)
             if (expected_sync_config_revision is not None
-                    and int(old_binding['sync_config_revision'] or 0) != expected_sync_config_revision):
+                    and old_revision != expected_sync_config_revision):
                 raise ProjectStatusConcurrentUpdateError('Binding changed while validating the policy')
-            target_changed = (
-                old_binding["match_rule_json"] != match_rule_json
-                or old_binding["mapping_json"] != mapping_json
-                or old_binding["external_key"] != external_key
-                or old_binding["mode"] != mode
-            )
-            new_revision = int(old_binding["sync_config_revision"] or 0) + (
-                1 if target_changed else 0
-            )
-            conn.execute(
-                """
-                UPDATE project_status_update_bindings
-                SET mode = ?, enabled = ?, external_key = ?, match_rule_json = ?,
-                    mapping_json = ?, credential_ref = ?, interval_minutes = ?,
-                    sync_config_revision = ?,
-                    cursor_json = CASE WHEN ? THEN '{}' ELSE cursor_json END,
-                    updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
-                WHERE deliverable_id = ?
-                """,
-                (mode, int(enabled), external_key, match_rule_json, mapping_json,
-                 credential_ref, interval_minutes, new_revision, int(target_changed), deliverable_id),
+            old_authority = {
+                str(row["field_name"]): str(row["authority"])
+                for row in conn.execute(
+                    """
+                    SELECT field_name, authority FROM project_status_field_authority
+                    WHERE deliverable_id = ? ORDER BY field_name
+                    """,
+                    (deliverable_id,),
+                ).fetchall()
+            }
+            new_authority = dict(old_authority)
+            new_authority.update({str(k): str(v) for k, v in field_authority.items()})
+            changed_authority = [
+                name for name, value in new_authority.items()
+                if old_authority.get(name) != value
+            ]
+
+            old_rule = _parse_policy_json(old_binding["match_rule_json"])
+            new_rule = _parse_policy_json(match_rule_json)
+            old_mapping = _parse_policy_json(old_binding["mapping_json"])
+            new_mapping = _parse_policy_json(mapping_json)
+            old_credential = old_binding["credential_ref"]
+            diffs: dict[str, tuple[Any, Any]] = {}
+            if old_binding["mode"] != mode:
+                diffs["mode"] = (old_binding["mode"], mode)
+            if bool(old_binding["enabled"]) != bool(enabled):
+                diffs["enabled"] = (bool(old_binding["enabled"]), bool(enabled))
+            if old_binding["external_key"] != external_key:
+                diffs["externalKey"] = (old_binding["external_key"], external_key)
+            if old_rule != new_rule:
+                diffs["matchRule"] = (old_rule, new_rule)
+            if old_mapping != new_mapping:
+                diffs["mapping"] = (old_mapping, new_mapping)
+            if old_binding["interval_minutes"] != interval_minutes:
+                diffs["intervalMinutes"] = (old_binding["interval_minutes"], interval_minutes)
+            if old_credential != credential_ref:
+                # 凭据别名不进审计，只记是否已配置。
+                diffs["credentialConfigured"] = (
+                    bool(str(old_credential or "").strip()),
+                    bool(str(credential_ref or "").strip()),
+                )
+            binding_changed = bool(diffs)
+            if changed_authority:
+                names = audit_field_names or {}
+                diffs["fieldAuthority"] = (
+                    {names.get(k, k): v for k, v in old_authority.items()},
+                    {names.get(k, k): v for k, v in new_authority.items()},
+                )
+            if not diffs:
+                return old_revision
+
+            recorder = getattr(self, "record_deliverable_config_audit", None)
+            if not callable(recorder):
+                raise BindingConfigAuditError("binding config audit recorder is unavailable")
+            target_changed = any(
+                name in diffs for name in ("mode", "externalKey", "matchRule", "mapping")
             )
-            for field_name, authority in field_authority.items():
+            new_revision = old_revision + (1 if target_changed else 0)
+            if binding_changed:
+                conn.execute(
+                    """
+                    UPDATE project_status_update_bindings
+                    SET mode = ?, enabled = ?, external_key = ?, match_rule_json = ?,
+                        mapping_json = ?, credential_ref = ?, interval_minutes = ?,
+                        sync_config_revision = ?,
+                        cursor_json = CASE WHEN ? THEN '{}' ELSE cursor_json END,
+                        updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
+                    WHERE deliverable_id = ?
+                    """,
+                    (mode, int(enabled), external_key, match_rule_json, mapping_json,
+                     credential_ref, interval_minutes, new_revision, int(target_changed),
+                     deliverable_id),
+                )
+            for field_name in changed_authority:
+                authority = new_authority[field_name]
                 conn.execute(
                     """
                     INSERT INTO project_status_field_authority
@@ -781,6 +869,35 @@
                     "DELETE FROM project_status_analysis_items WHERE deliverable_id = ?",
                     (deliverable_id,),
                 )
+
+            payload = build_binding_config_audit_payload(
+                deliverable_id, old_revision, new_revision, diffs,
+            )
+            last_id = int(conn.execute(
+                "SELECT COALESCE(MAX(id), 0) FROM project_status_binding_config_audit"
+            ).fetchone()[0])
+            try:
+                recorded = recorder(deliverable_id, payload, actor, conn=conn)
+            except Exception as exc:
+                raise BindingConfigAuditError("binding config audit recorder failed") from exc
+            inserted = conn.execute(
+                """
+                SELECT deliverable_id, actor, event_type, config_revision, changes_json
+                FROM project_status_binding_config_audit
+                WHERE id > ? ORDER BY id
+                """,
+                (last_id,),
+            ).fetchall()
+            if (
+                recorded is not True
+                or len(inserted) != 1
+                or inserted[0]["deliverable_id"] != deliverable_id
+                or inserted[0]["actor"] != actor
+                or inserted[0]["event_type"] != "configuration_updated"
+                or inserted[0]["config_revision"] != new_revision
+                or _parse_policy_json(inserted[0]["changes_json"]) != payload
+            ):
+                raise BindingConfigAuditError("binding config audit row was not recorded")
         return new_revision
 
     def list_project_status_update_audit(
```

## 补丁 project_status_updates
```diff
--- project_status_updates.orig.py	2026-10-17 19:05:23.519308064 +0800
+++ vt/services/project_status_updates.py	2026-10-17 19:05:23.537625287 +0800
@@ -903,6 +903,8 @@
         self,
         deliverable_id: str,
         payload: dict[str, Any],
+        *,
+        actor: str = "local_web",
     ) -> dict[str, Any]:
         raw = self._db.get_project_status_update_policy(deliverable_id)
         if raw is None:
@@ -1152,45 +1154,16 @@
                     if project_status_supports_record_set(deliverable_id)
                     else None
                 ),
+                # 绑定配置审计在保存事务内写入（B′ P1a）；字段归属用 API 字段名记审计。
+                actor=actor,
+                audit_field_names=PROJECT_STATUS_FIELD_NAME_TO_API,
             )
         except ProjectStatusConcurrentUpdateError:
             raise ProjectStatusPolicyError({'request': '绑定已发生变化，请刷新配置后重试'}) from None
         raw = self._db.get_project_status_update_policy(deliverable_id)
         assert raw is not None
-        self._audit_policy_change(deliverable_id, binding, raw["binding"])
         return self._policy_to_api(raw)
 
-    def _audit_policy_change(
-        self,
-        deliverable_id: str,
-        before: Mapping[str, Any],
-        after: Mapping[str, Any],
-    ) -> None:
-        """同步设置改动写进关联归档任务的配置审计（§9 S21）；凭据只记是否配置。"""
-        def view(binding: Mapping[str, Any]) -> dict[str, Any]:
-            return {
-                "enabled": bool(binding.get("enabled")),
-                # None = 没有自己的间隔，跟随调度器频率（services/project_status_scheduler.py _is_fresh）。
-                "intervalMinutes": binding.get("interval_minutes"),
-                "mode": binding.get("mode"),
-                "matchRule": _json_loads(binding.get("match_rule_json")),
-                "credentialConfigured": bool(str(binding.get("credential_ref") or "").strip()),
-            }
-
-        old, new = view(before), view(after)
-        changes = {key: {"from": old[key], "to": new[key]} for key in old if old[key] != new[key]}
-        if not changes:
-            return
-        recorder = getattr(self._db, "record_deliverable_config_audit", None)
-        if recorder is None:
-            return
-        try:
-            recorder(deliverable_id, {"source": "deliverable_sync_settings", "deliverableId": deliverable_id,
-                                      "changes": changes})
-        except Exception as exc:  # noqa: BLE001 - 设置已保存，审计失败只记日志
-            _logger.warning("deliverable sync settings audit failed for %s: %s",
-                            deliverable_id, redact_sensitive_text(str(exc), limit=200))
-
     def list_updates(
         self,
         deliverable_id: str,
```

## 补丁 test_isolation
```diff
--- tests.frozen/test_bprime_config_audit_isolation.py	2026-10-17 19:05:59.726126817 +0800
+++ vt/tests/test_bprime_config_audit_isolation.py	2026-10-17 19:05:59.730879836 +0800
@@ -7,7 +7,7 @@
     deliverable_id = case["deliverable_id"]
     with db.get_connection() as conn:
         mapping = json.loads(case["snapshot"](conn)["binding"][0]["mapping_json"])
-        mapping["progress"] = "SYNTHETIC_MARKER_1"
+        mapping["plannedDate"] = "SYNTHETIC_MARKER_1"
         conn.execute(
             "UPDATE project_status_update_bindings SET mapping_json = ? WHERE deliverable_id = ?",
             (json.dumps(mapping), deliverable_id))
```

## 补丁 test_noarchive
```diff
--- tests.frozen/test_bprime_config_audit_noarchive.py	2026-10-17 19:05:59.726244913 +0800
+++ vt/tests/test_bprime_config_audit_noarchive.py	2026-10-17 19:05:59.750505841 +0800
@@ -6,6 +6,9 @@
     db, service = case["db"], case["service"]
     deliverable_id = case["deliverable_id"]
     with db.get_connection() as conn:
+        conn.execute(
+            "UPDATE scheduled_archive_jobs SET project_status_deliverable_id = NULL "
+            "WHERE project_status_deliverable_id = ?", (deliverable_id,))
         count = conn.execute(
             "SELECT COUNT(*) FROM scheduled_archive_jobs "
             "WHERE project_status_deliverable_id = ?", (deliverable_id,)).fetchone()[0]
```

