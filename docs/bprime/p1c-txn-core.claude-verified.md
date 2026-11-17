# B′ P1c 参考补丁：U-BPRIME-TXN-CORE（事务保存核心）

来源：A57（Sol 定稿卡 `U-BPRIME-TXN-CORE`，decompose 19ad6d51…）原样转写为参考文件。卡登记曾被分类器以 `STEP_EXECUTION_UNSUPPORTED` 拒绝（围栏内含方法签名/连接上下文），按"方案 2"改为引用式卡：卡步骤只写"按本文件第 N 段做一次原生 edit"。

## 基线与验证
- 唯一修改文件：`core/repos/project_status.py`；基线 SHA256 `93a49ff77d237101663475b289762cf395eb2aa670f5fc49b60cf73117c62728`（CRLF）。
- 补丁后 SHA256（CRLF）：`a71ff93b9256276e78f405cebe8ba8528fd9f2fa2d5fef8fc1c48d1ef7778b2f`
- 补丁后：+100 / −20（与 A57 静态预算一致），CRLF 保持，1150 行。
- 审阅者（Claude）在云端 Linux 副本上验证（不是本机证据，最终以本机回执为准）：
  - `tests/test_bprime_config_digest_spec.py` + 全部 `tests/test_bprime_config_audit_*.py` + `test_project_status_updates.py` + `test_project_status_sync_runner.py` + `test_db_manager.py` + `test_project_status_sync_runs.py`：170 passed。
  - `test_project_status_policy_api.py` + `test_plugin_project_overview_watchlist.py`：补丁前后均为 38 passed / 1 failed（`test_snapshot_state_falls_back_to_form_snapshot_summary`，Linux 环境差异，本机全量回归中通过），补丁未引入新失败。
- 卡验收命令：`python -m pytest tests/test_bprime_config_audit_isolation.py -q`，预期 2 passed。

## 段 1：导入（在 `from hashlib import sha256` 之后插入一行）
```python
from typing import NamedTuple
```

## 段 2：模块级助手（插入在 `def _parse_policy_json(value: Any) -> Any:` 之前；末尾保留两个空行）
```python
KEEP_CURRENT = object()


class ProjectStatusConfigDigestMismatchError(ProjectStatusConcurrentUpdateError):
    """The stored policy no longer matches the expected configuration digest."""


class _PolicySaveResult(NamedTuple):
    revision: int
    raw: dict


def _read_policy_rows(conn, deliverable_id):
    """Read the same three projections as GET, without seeding any rows."""
    binding = conn.execute(
        "SELECT id, deliverable_id, mode, source_type, external_key, "
        "match_rule_json, mapping_json, enabled, interval_minutes, "
        "last_attempt_at, last_success_at, sync_state, sync_config_revision, "
        "last_error_type, last_error_message, credential_ref, created_at, updated_at "
        "FROM project_status_update_bindings WHERE deliverable_id = ?",
        (deliverable_id,)).fetchone()
    authorities = conn.execute(
        "SELECT field_name, authority, source_type, locked_at, updated_at "
        "FROM project_status_field_authority WHERE deliverable_id = ? ORDER BY field_name",
        (deliverable_id,)).fetchall()
    latest = conn.execute(
        "SELECT id, trigger_type, source_type, external_version, result, error_summary, created_at "
        "FROM project_status_update_audit WHERE deliverable_id = ? ORDER BY id DESC LIMIT 1",
        (deliverable_id,)).fetchone()
    return {
        "binding": dict(binding) if binding is not None else None,
        "authorities": [dict(row) for row in authorities],
        "latest_audit": dict(latest) if latest is not None else None,
    }


def _normalize_policy_rows(deliverable_id, raw):
    """Fill missing policy rows in memory; synthetic database metadata stays None."""
    source_type = str(PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {}).get("sourceType") or "none")
    if raw["binding"] is None:
        raw["binding"] = dict(
            _policy_binding_defaults(deliverable_id),
            id=None, deliverable_id=deliverable_id, source_type=source_type, sync_state="idle",
            last_attempt_at=None, last_success_at=None, last_error_type=None,
            last_error_message=None, created_at=None, updated_at=None,
        )
    by_name = {row["field_name"]: row for row in raw["authorities"]}
    for name in PROJECT_STATUS_EDITABLE_FIELDS:
        by_name.setdefault(name, dict(
            field_name=name, authority=POLICY_AUTHORITY_DEFAULT,
            source_type=source_type, locked_at=None, updated_at=None,
        ))
    raw["authorities"] = [by_name[name] for name in sorted(by_name)]
    return raw
```

## 段 3：setter 入口与新核心签名
把 setter 中以下 5 行（unknown 检查 + 获取连接 + BEGIN IMMEDIATE）：
```python
        unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
```
整体替换为：
```python
        with self.get_connection() as conn:
            return self._save_policy_txn(
                conn, deliverable_id, mode, enabled, external_key, match_rule_json,
                mapping_json, field_authority, credential_ref, interval_minutes,
                expected_sync_config_revision, actor=actor,
                audit_field_names=audit_field_names,
            ).revision

    def _save_policy_txn(
        self,
        conn: sqlite3.Connection,
        deliverable_id: str,
        mode: str,
        enabled: bool,
        external_key: str | None,
        match_rule_json: str,
        mapping_json: str,
        field_authority: dict[str, str],
        credential_ref: Any = None,
        interval_minutes: int | None = 60,
        expected_sync_config_revision: int | None = None,
        *,
        actor: str = "local_web",
        audit_field_names: Mapping[str, str] | None = None,
        expected_config_digest: str | None = None,
    ) -> _PolicySaveResult:
        """Save and return a transaction-owned snapshot after a successful commit."""
        if conn.in_transaction:
            raise ValueError("policy save requires a connection without an active transaction")
        unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        with conn:
            conn.execute('BEGIN IMMEDIATE')
```
其后原有的 deliverable 存在性检查（`deliverable = conn.execute(... project_status_deliverables ...)` 至 `raise KeyError(deliverable_id)`）缩进不变，留在 `with conn:` 内。

## 段 4：初始读取与校验
把核心里从 `            self._ensure_project_status_policy(conn, deliverable_id)`（紧接 KeyError 之后那一处）起、到 `old_authority = { ... }` 字典结束（`new_authority = dict(old_authority)` 之前）的整段，替换为：
```python
            raw = _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))
            old_binding = raw["binding"]
            old_revision = int(old_binding['sync_config_revision'] or 0)
            if (expected_sync_config_revision is not None
                    and old_revision != expected_sync_config_revision):
                raise ProjectStatusConcurrentUpdateError('Binding changed while validating the policy')
            if (expected_config_digest is not None
                    and compute_policy_config_digest(
                        deliverable_id, old_binding, raw["authorities"]) != expected_config_digest):
                raise ProjectStatusConfigDigestMismatchError("Policy configuration digest changed")
            if credential_ref is KEEP_CURRENT:
                credential_ref = old_binding["credential_ref"]
            old_authority = {
                str(row["field_name"]): str(row["authority"])
                for row in raw["authorities"]
            }
```

## 段 5：三处收尾
5a. 无差异返回：
```python
                return old_revision
```
→
```python
                return _PolicySaveResult(old_revision, raw)
```
5b. 在 `            recorder = getattr(self, "record_deliverable_config_audit", None)` 之前插入一行：
```python
            self._ensure_project_status_policy(conn, deliverable_id)
```
5c. 函数末尾（审计行校验 `raise BindingConfigAuditError("binding config audit row was not recorded")` 之后）：
```python
        return new_revision
```
→
```python
            raw = _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))
        return _PolicySaveResult(new_revision, raw)
```
（A60 修订：A57 原文此处未归一化；若写后仍缺 authority 行，服务层用这份 raw 算出的 configDigest 与核心比对时的归一输入不同，GET→PUT 往返会稳定 422。归一化幂等，无副作用。）

## 完整 unified diff（LF 展示，供核对）
```diff
--- a/core/repos/project_status.py
+++ b/core/repos/project_status.py
@@ -6,6 +6,7 @@
 """
 
 from hashlib import sha256
+from typing import NamedTuple
 from core.db_common import (  # noqa: F401
     _dump_extra_fields,
     _LOCAL_NOW_SQL,
@@ -62,6 +63,62 @@
     return "cfgd1:" + sha256(canonical).hexdigest()
 
 
+KEEP_CURRENT = object()
+
+
+class ProjectStatusConfigDigestMismatchError(ProjectStatusConcurrentUpdateError):
+    """The stored policy no longer matches the expected configuration digest."""
+
+
+class _PolicySaveResult(NamedTuple):
+    revision: int
+    raw: dict
+
+
+def _read_policy_rows(conn, deliverable_id):
+    """Read the same three projections as GET, without seeding any rows."""
+    binding = conn.execute(
+        "SELECT id, deliverable_id, mode, source_type, external_key, "
+        "match_rule_json, mapping_json, enabled, interval_minutes, "
+        "last_attempt_at, last_success_at, sync_state, sync_config_revision, "
+        "last_error_type, last_error_message, credential_ref, created_at, updated_at "
+        "FROM project_status_update_bindings WHERE deliverable_id = ?",
+        (deliverable_id,)).fetchone()
+    authorities = conn.execute(
+        "SELECT field_name, authority, source_type, locked_at, updated_at "
+        "FROM project_status_field_authority WHERE deliverable_id = ? ORDER BY field_name",
+        (deliverable_id,)).fetchall()
+    latest = conn.execute(
+        "SELECT id, trigger_type, source_type, external_version, result, error_summary, created_at "
+        "FROM project_status_update_audit WHERE deliverable_id = ? ORDER BY id DESC LIMIT 1",
+        (deliverable_id,)).fetchone()
+    return {
+        "binding": dict(binding) if binding is not None else None,
+        "authorities": [dict(row) for row in authorities],
+        "latest_audit": dict(latest) if latest is not None else None,
+    }
+
+
+def _normalize_policy_rows(deliverable_id, raw):
+    """Fill missing policy rows in memory; synthetic database metadata stays None."""
+    source_type = str(PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {}).get("sourceType") or "none")
+    if raw["binding"] is None:
+        raw["binding"] = dict(
+            _policy_binding_defaults(deliverable_id),
+            id=None, deliverable_id=deliverable_id, source_type=source_type, sync_state="idle",
+            last_attempt_at=None, last_success_at=None, last_error_type=None,
+            last_error_message=None, created_at=None, updated_at=None,
+        )
+    by_name = {row["field_name"]: row for row in raw["authorities"]}
+    for name in PROJECT_STATUS_EDITABLE_FIELDS:
+        by_name.setdefault(name, dict(
+            field_name=name, authority=POLICY_AUTHORITY_DEFAULT,
+            source_type=source_type, locked_at=None, updated_at=None,
+        ))
+    raw["authorities"] = [by_name[name] for name in sorted(by_name)]
+    return raw
+
+
 def _parse_policy_json(value: Any) -> Any:
     """解析绑定 JSON 列用于语义比较（键序无关）；空值或坏 JSON 视为 {}。"""
     if not isinstance(value, str) or not value:
@@ -782,10 +839,39 @@
         ``audit_field_names`` 把字段归属的列名翻译成审计载荷里的字段名（服务层传 API 名）。
         返回保存后的修订号。
         """
+        with self.get_connection() as conn:
+            return self._save_policy_txn(
+                conn, deliverable_id, mode, enabled, external_key, match_rule_json,
+                mapping_json, field_authority, credential_ref, interval_minutes,
+                expected_sync_config_revision, actor=actor,
+                audit_field_names=audit_field_names,
+            ).revision
+
+    def _save_policy_txn(
+        self,
+        conn: sqlite3.Connection,
+        deliverable_id: str,
+        mode: str,
+        enabled: bool,
+        external_key: str | None,
+        match_rule_json: str,
+        mapping_json: str,
+        field_authority: dict[str, str],
+        credential_ref: Any = None,
+        interval_minutes: int | None = 60,
+        expected_sync_config_revision: int | None = None,
+        *,
+        actor: str = "local_web",
+        audit_field_names: Mapping[str, str] | None = None,
+        expected_config_digest: str | None = None,
+    ) -> _PolicySaveResult:
+        """Save and return a transaction-owned snapshot after a successful commit."""
+        if conn.in_transaction:
+            raise ValueError("policy save requires a connection without an active transaction")
         unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
         if unknown:
             raise ValueError(f"unknown project status field: {sorted(unknown)}")
-        with self.get_connection() as conn:
+        with conn:
             conn.execute('BEGIN IMMEDIATE')
             deliverable = conn.execute(
                 "SELECT id FROM project_status_deliverables WHERE id = ?",
@@ -793,29 +879,21 @@
             ).fetchone()
             if deliverable is None:
                 raise KeyError(deliverable_id)
-            self._ensure_project_status_policy(conn, deliverable_id)
-            old_binding = conn.execute(
-                """
-                SELECT mode, enabled, external_key, match_rule_json, mapping_json,
-                       credential_ref, interval_minutes, sync_config_revision
-                FROM project_status_update_bindings
-                WHERE deliverable_id = ?
-                """,
-                (deliverable_id,),
-            ).fetchone()
+            raw = _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))
+            old_binding = raw["binding"]
             old_revision = int(old_binding['sync_config_revision'] or 0)
             if (expected_sync_config_revision is not None
                     and old_revision != expected_sync_config_revision):
                 raise ProjectStatusConcurrentUpdateError('Binding changed while validating the policy')
+            if (expected_config_digest is not None
+                    and compute_policy_config_digest(
+                        deliverable_id, old_binding, raw["authorities"]) != expected_config_digest):
+                raise ProjectStatusConfigDigestMismatchError("Policy configuration digest changed")
+            if credential_ref is KEEP_CURRENT:
+                credential_ref = old_binding["credential_ref"]
             old_authority = {
                 str(row["field_name"]): str(row["authority"])
-                for row in conn.execute(
-                    """
-                    SELECT field_name, authority FROM project_status_field_authority
-                    WHERE deliverable_id = ? ORDER BY field_name
-                    """,
-                    (deliverable_id,),
-                ).fetchall()
+                for row in raw["authorities"]
             }
             new_authority = dict(old_authority)
             new_authority.update({str(k): str(v) for k, v in field_authority.items()})
@@ -856,8 +934,9 @@
                     {names.get(k, k): v for k, v in new_authority.items()},
                 )
             if not diffs:
-                return old_revision
+                return _PolicySaveResult(old_revision, raw)
 
+            self._ensure_project_status_policy(conn, deliverable_id)
             recorder = getattr(self, "record_deliverable_config_audit", None)
             if not callable(recorder):
                 raise BindingConfigAuditError("binding config audit recorder is unavailable")
@@ -953,7 +1032,8 @@
                 or _parse_policy_json(inserted[0]["changes_json"]) != payload
             ):
                 raise BindingConfigAuditError("binding config audit row was not recorded")
-        return new_revision
+            raw = _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))
+        return _PolicySaveResult(new_revision, raw)
 
     def list_project_status_update_audit(
         self,
```
