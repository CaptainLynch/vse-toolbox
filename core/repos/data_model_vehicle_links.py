# -*- coding: utf-8 -*-
"""数模设计审核流程（D5）：车型 ↔ 架构件单号的人工关联声明。

表 ``data_model_vehicle_arch_links`` 只存"谁在什么时候依据什么，把哪张
架构单关联到哪个车型"。**不做任何推断**：不读 SOR 号、不读流水前缀、
不读 TDC 查询结果（那三者都不是归属证据，见 services/data_model_attribution）。

版本语义：同一 ``(车型, 单号)`` 重新声明时新增一行并把旧行 ``active`` 置 0，
因此历史声明可追溯，撤销只改标志位不删行。
"""

from __future__ import annotations

from typing import Any, Iterable

from core.db_common import Any as _Any  # noqa: F401  （保持与其它 repo 一致的依赖形态）


class DataModelVehicleLinkRepo:
    """``DatabaseManager`` 的领域分片：D5 车型↔架构单关联。"""

    def list_data_model_vehicle_links(
        self,
        vehicle: str | None = None,
        *,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM data_model_vehicle_arch_links"
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = 1")
        if vehicle is not None:
            clauses.append("vehicle = ?")
            params.append(str(vehicle))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY vehicle, serial, revision DESC"
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def replace_data_model_vehicle_links(
        self,
        vehicle: str,
        serials: Iterable[str],
        *,
        operator: str = "",
        basis: str = "",
        effective_from: str | None = None,
        effective_to: str | None = None,
    ) -> dict[str, Any]:
        """用给定单号集合**替换**某车型的全部有效关联。

        返回 ``{"vehicle", "added", "removed", "unchanged"}``。已经有效的单号
        保持不变（不产生新 revision），只有新增/移除会留下痕迹。
        """
        target = str(vehicle).strip()
        wanted = [str(serial).strip() for serial in serials if str(serial).strip()]
        wanted_set = list(dict.fromkeys(wanted))
        current = self.list_data_model_vehicle_links(target, active_only=True)
        current_map = {str(item["serial"]): item for item in current}
        added = [serial for serial in wanted_set if serial not in current_map]
        removed = [serial for serial in current_map if serial not in set(wanted_set)]
        unchanged = [serial for serial in wanted_set if serial in current_map]
        with self.get_connection() as conn:
            for serial in removed:
                conn.execute(
                    """
                    UPDATE data_model_vehicle_arch_links
                       SET active = 0, effective_to = COALESCE(effective_to, datetime('now', 'localtime'))
                     WHERE id = ?
                    """,
                    (int(current_map[serial]["id"]),),
                )
            for serial in added:
                row = conn.execute(
                    """
                    SELECT COALESCE(MAX(revision), 0) AS revision
                      FROM data_model_vehicle_arch_links
                     WHERE vehicle = ? AND serial = ?
                    """,
                    (target, serial),
                ).fetchone()
                next_revision = int(row["revision"]) + 1 if row else 1
                conn.execute(
                    """
                    INSERT INTO data_model_vehicle_arch_links
                        (vehicle, serial, basis, operator, effective_from, effective_to, revision, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        target,
                        serial,
                        str(basis or "")[:500],
                        str(operator or "")[:120],
                        effective_from,
                        effective_to,
                        next_revision,
                    ),
                )
        return {
            "vehicle": target,
            "added": added,
            "removed": removed,
            "unchanged": unchanged,
        }

    def clear_data_model_vehicle_links(self, vehicle: str) -> int:
        """撤销某车型的全部有效关联；返回撤销条数。"""
        target = str(vehicle).strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE data_model_vehicle_arch_links
                   SET active = 0, effective_to = COALESCE(effective_to, datetime('now', 'localtime'))
                 WHERE vehicle = ? AND active = 1
                """,
                (target,),
            )
            return int(cursor.rowcount or 0)
