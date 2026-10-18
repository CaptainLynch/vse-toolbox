# B′ P1c 预读快照参考文档（只读参考，不应用生产补丁）

## 基线

- `core/repos/project_status.py`：SHA256 `a71ff93b9256276e78f405cebe8ba8528fd9f2fa2d5fef8fc1c48d1ef7778b2f`，1150 行。
- `services/project_status_updates.py`：SHA256 `722899d9c215f2fff363424d94fa9830816b9983a0ee8928273c50759ab2ac88`，1254 行。

两个基线在本单元读取时均校验一致。本文仅记录后续实施卡的逐字 old/new，不应用补丁、不运行解释器、不做行为验收。

## 1. 仓储：新增公开只读快照方法

目标文件：`core/repos/project_status.py`
定位范围：基线第 814 行 `set_project_status_update_policy` 声明首行，作为唯一插入锚点。

old（第 814 行，逐字）：

```python
    def set_project_status_update_policy(
```

new（新增方法 + 一个空行 + 原锚点行）：

```python
    def read_project_status_update_policy_snapshot(
        self, deliverable_id: str
    ) -> dict[str, object] | None:
        """Read policy rows without seeding missing rows."""
        with self.get_connection() as conn:
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                return None
            return _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))

    def set_project_status_update_policy(
```

连接上下文与交付物存在性检查逐字取自原 GET 第 768–774 行；存在时直接返回 `_normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))`。缺行与部分 authority 只在内存补齐，保留已有字段与 `latest_audit`；不调用补行函数，不开启事务、不执行写入、不获取写锁，不新增默认值来源、策略读取查询或摘要算法。

## 2. 仓储 GET：收敛为共享读取

目标文件：`core/repos/project_status.py`
定位范围：基线第 776–812 行（原三段读取、binding 断言与最终字典组装）；不含第 775 行补行调用。

old（第 776–812 行，逐字）：

```python
            binding = conn.execute(
                """
                SELECT id, deliverable_id, mode, source_type, external_key,
                       match_rule_json, mapping_json, enabled, interval_minutes,
                       last_attempt_at, last_success_at, sync_state, sync_config_revision,
                        last_error_type, last_error_message, credential_ref,
                        created_at, updated_at
                FROM project_status_update_bindings
                WHERE deliverable_id = ?
                """,
                (deliverable_id,),
            ).fetchone()
            assert binding is not None
            authorities = conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = ?
                ORDER BY field_name
                """,
                (deliverable_id,),
            ).fetchall()
            latest = conn.execute(
                """
                SELECT id, trigger_type, source_type, external_version, result,
                       error_summary, created_at
                FROM project_status_update_audit
                WHERE deliverable_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (deliverable_id,),
            ).fetchone()
            return {
                "binding": dict(binding),
                "authorities": [dict(row) for row in authorities],
                "latest_audit": dict(latest) if latest is not None else None,
            }
```

new（仅一行，保留十二空格缩进）：

```python
            return _read_policy_rows(conn, deliverable_id)
```

GET 原有的交付物存在性检查与补行调用保持不动，返回值不改为内存归一结果；未知交付物、字段集合、排序、真实数据库 ID、时间戳与 `latest_audit` 的外部行为保持一致。

## 3. 服务：update_update_policy 保存前预读

目标文件：`services/project_status_updates.py`
定位范围：基线第 912 行。

old（第 912 行，逐字）：

```python
        raw = self._db.get_project_status_update_policy(deliverable_id)
```

new：

```python
        raw = self._db.read_project_status_update_policy_snapshot(deliverable_id)
```

保留该行缩进与赋值目标，只改被调用方法名。仅在 `update_update_policy` 内替换一次；同文件其他方法中的同文调用不替换，不做全局替换。

## 4. 不变性核对：_save_policy_txn 无差异返回

目标文件：`core/repos/project_status.py`
定位范围：基线第 936–939 行。本段不产生编辑，old 与 new 必须完全相同。

old（第 936–939 行，逐字）：

```python
            if not diffs:
                return _PolicySaveResult(old_revision, raw)

            self._ensure_project_status_policy(conn, deliverable_id)
```

new（与 old 逐字相同）：

```python
            if not diffs:
                return _PolicySaveResult(old_revision, raw)

            self._ensure_project_status_policy(conn, deliverable_id)
```

整个 `_save_policy_txn` 不改：检查、差异计算、无差异返回、补行与后续审计写入顺序全部保留。除第 1–3 段外均不改；默认值、共享助手、服务格式与摘要校验、修订号校验、KEEP_CURRENT、错误映射、事务结果投影及其他调用方保持原样。无策略行且无历史审计的无差异保存直接返回内存结果，`createdAt`、`updatedAt`、`latestUpdate` 为 None，不用保存后二次 GET 消除差异。不修改 DDL、`web/app.py`、conftest、任何测试或 P1b 冻结节点。后续实施卡静态预期 33 passed；本单元不执行行为验收。
