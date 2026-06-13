"""里程碑规则 + 评估 CRUD 路由。"""

import logging

from fastapi import APIRouter
from api.response import success_response, error_response
from models.schemas import MilestoneRuleCreate, MilestoneRuleUpdate, MilestoneEvaluationUpdate
from services.db import DBManager
from services.milestone_evaluator import MilestoneEvaluator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["milestone-rules"])

evaluator = MilestoneEvaluator()


@router.get("/milestone-rules")
def list_milestone_rules(timeline_node_id: int | None = None):
    try:
        rules = DBManager.list_milestone_rules(timeline_node_id)
        return success_response(rules)
    except Exception as e:
        logger.error("list_milestone_rules failed: %s", e)
        return error_response(str(e), status_code=500)


@router.post("/milestone-rules")
def create_milestone_rule(data: MilestoneRuleCreate):
    try:
        rule = DBManager.create_milestone_rule(data.model_dump())
        logger.info("Created milestone rule %s", rule.get("id"))
        return success_response(rule)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.get("/milestone-rules/evaluations")
def list_evaluations(timeline_node_id: int | None = None):
    try:
        evals = DBManager.list_evaluations(timeline_node_id)
        return success_response(evals)
    except Exception as e:
        logger.error("list_evaluations failed: %s", e)
        return error_response(str(e), status_code=500)


@router.post("/milestone-rules/evaluations/refresh")
def refresh_evaluations():
    try:
        count = evaluator.evaluate_all()
        logger.info("Refreshed %s evaluations", count)
        return success_response({"refreshed": count})
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.put("/milestone-rules/evaluations/{evaluation_id}")
def update_evaluation(evaluation_id: int, data: MilestoneEvaluationUpdate):
    ev = DBManager.update_evaluation(evaluation_id, data.model_dump(exclude_unset=True))
    if not ev:
        return error_response("评估记录不存在", status_code=404)
    logger.info("Updated evaluation %s", evaluation_id)
    return success_response(ev)


@router.get("/milestone-rules/{rule_id}")
def get_milestone_rule(rule_id: int):
    rule = DBManager.get_milestone_rule(rule_id)
    if not rule:
        return error_response("规则不存在", status_code=404)
    return success_response(rule)


@router.put("/milestone-rules/{rule_id}")
def update_milestone_rule(rule_id: int, data: MilestoneRuleUpdate):
    rule = DBManager.update_milestone_rule(rule_id, data.model_dump(exclude_unset=True))
    if not rule:
        return error_response("规则不存在", status_code=404)
    logger.info("Updated milestone rule %s", rule_id)
    return success_response(rule)


@router.delete("/milestone-rules/{rule_id}")
def delete_milestone_rule(rule_id: int):
    ok = DBManager.delete_milestone_rule(rule_id)
    if not ok:
        return error_response("规则不存在", status_code=404)
    logger.info("Deleted milestone rule %s", rule_id)
    return success_response({"deleted": True})