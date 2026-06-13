"""里程碑自动评估引擎。

根据 milestone_rules 的 condition_config 自动计算当前状态。
R-02: 所有 SQL 参数化。
R-05: 使用 get_connection() 上下文管理器。
"""

import json
import logging
from datetime import datetime

from services.db import get_connection, DBManager

logger = logging.getLogger("VSE_TOOLBOX.evaluator")

# 白名单：允许查询的表名映射
_TABLE_MAP = {
    "issues": "issues",
    "ewo": "ewo_ncr",
    "ewo_ncr": "ewo_ncr",
    "tir": "tir",
}

# 白名单：允许的字段名
_VALID_FIELDS = {"status", "priority", "severity", "type"}


class MilestoneEvaluator:
    """根据规则自动评估里程碑完成状态。"""

    def evaluate_all(self) -> int:
        """遍历所有 is_active=1 的规则，计算 current_value 并更新 evaluation。"""
        rules = DBManager.list_milestone_rules()
        updated = 0
        for rule in rules:
            if not rule.get("is_active"):
                continue
            if rule["condition_type"] == "manual":
                self._ensure_evaluation_exists(rule)
                continue
            config = rule.get("condition_config") or {}
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except (json.JSONDecodeError, TypeError):
                    config = {}
            current = self._compute(rule["condition_type"], config)
            threshold = rule.get("target_value", 0) / 100.0 if rule.get("target_value", 0) > 0 else 1.0
            status = self._determine_status(current, threshold)
            DBManager.upsert_evaluation(rule["id"], {
                "current_value": round(current, 4),
                "target_value": rule.get("target_value", 0),
                "status": status,
            })
            updated += 1
        logger.info("Milestone evaluation refreshed: %d rules updated", updated)
        return updated

    def _ensure_evaluation_exists(self, rule: dict) -> None:
        """确保手动规则也有 evaluation 记录。"""
        existing = DBManager.get_evaluation_by_rule(rule["id"])
        if not existing:
            DBManager.upsert_evaluation(rule["id"], {
                "current_value": 0,
                "target_value": rule.get("target_value", 0),
                "status": "not_started",
            })

    def _compute(self, condition_type: str, config: dict) -> float:
        if condition_type == "count_threshold":
            return self._compute_count(config)
        elif condition_type == "status_match":
            return self._compute_status_match(config)
        return 0.0

    def _compute_count(self, config: dict) -> float:
        """统计 data_source 表中满足条件的记录占比。"""
        data_source = config.get("data_source", "")
        count_field = config.get("count_field", "status")
        count_value = config.get("count_value", "")

        table = _TABLE_MAP.get(data_source)
        if not table or count_field not in _VALID_FIELDS:
            return 0.0

        with get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            matched = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {count_field} = ?",
                (count_value,)
            ).fetchone()[0]

        return matched / total if total > 0 else 0.0

    def _compute_status_match(self, config: dict) -> float:
        """统计 data_source 表中匹配状态集合的记录占比。"""
        data_source = config.get("data_source", "")
        match_field = config.get("match_field", "status")
        match_values = config.get("match_values", [])

        table = _TABLE_MAP.get(data_source)
        if not table or match_field not in _VALID_FIELDS or not match_values:
            return 0.0

        placeholders = ", ".join("?" for _ in match_values)

        with get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            matched = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {match_field} IN ({placeholders})",
                match_values
            ).fetchone()[0]

        return matched / total if total > 0 else 0.0

    def _determine_status(self, current: float, threshold: float) -> str:
        if current >= threshold:
            return "completed"
        elif current > 0:
            return "in_progress"
        return "not_started"
