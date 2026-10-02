# -*- coding: utf-8 -*-
"""Per-plugin schema versions (DatabaseManager 的领域分片)。

插件自己的表由插件声明的迁移步骤创建和升级，版本记在
``plugin_schema_versions``，与宿主的 ``PRAGMA user_version``（冻结在 14）互不影响。

约定（勿破）：
- 插件表名以 ``p_<插件 id，-换成_>_`` 开头，避免与宿主表冲突。
- 迁移只做加法（加表、加列、加索引），这样回滚到旧版插件包时旧代码仍能读写；
  因此数据库版本高于插件已知版本时不报错，只跳过。
- 每一步在独立事务中执行并同时记录版本，失败时该步整体回滚，之前的步骤保留。
"""

from __future__ import annotations

import re
from typing import Callable, Sequence, Tuple

from core.db_common import logger

MigrationStep = Tuple[int, Callable[..., None]]

_PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")

PLUGIN_SCHEMA_VERSIONS_DDL = """
    CREATE TABLE IF NOT EXISTS plugin_schema_versions (
        plugin_id   TEXT PRIMARY KEY NOT NULL,
        version     INTEGER NOT NULL CHECK (version >= 0),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
"""


def plugin_table_prefix(plugin_id: str) -> str:
    """Return the table-name prefix reserved for one plugin (``p_<id>_``)."""
    return "p_" + plugin_id.replace("-", "_") + "_"


class PluginSchemaRepo:
    def get_plugin_schema_version(self, plugin_id: str) -> int:
        with self.get_connection() as conn:
            conn.execute(PLUGIN_SCHEMA_VERSIONS_DDL)
            row = conn.execute(
                "SELECT version FROM plugin_schema_versions WHERE plugin_id = ?", (plugin_id,)
            ).fetchone()
        return int(row["version"]) if row else 0

    def apply_plugin_migrations(self, plugin_id: str, steps: Sequence[MigrationStep]) -> int:
        """Apply the steps above the stored version in order; return the resulting version."""
        if not _PLUGIN_ID_PATTERN.match(plugin_id):
            raise ValueError("无效的插件 id")
        ordered = sorted(steps, key=lambda step: step[0])
        versions = [int(version) for version, _ in ordered]
        if any(v < 1 for v in versions) or len(set(versions)) != len(versions):
            raise ValueError("插件迁移版本必须是互不相同的正整数")
        current = self.get_plugin_schema_version(plugin_id)
        if versions and current > versions[-1]:
            logger.warning(
                "Plugin %s schema version %s is newer than its migrations (%s); keeping it",
                plugin_id, current, versions[-1],
            )
            return current
        for version, step in ordered:
            if version <= current:
                continue
            with self.get_connection() as conn:
                # 显式开启事务：sqlite3 默认不为 DDL 开事务，否则建表无法随失败回滚。
                conn.execute("BEGIN")
                step(conn)
                conn.execute(
                    "INSERT INTO plugin_schema_versions (plugin_id, version) VALUES (?, ?) "
                    "ON CONFLICT(plugin_id) DO UPDATE SET version = excluded.version, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                    (plugin_id, version),
                )
            current = version
        return current
