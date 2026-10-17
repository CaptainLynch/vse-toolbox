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
