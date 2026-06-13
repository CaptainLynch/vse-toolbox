/**
 * 后端 snake_case -> 前端 camelCase 转换器。
 */

import type {
  Issue, IssueStats, Milestone, DepartmentStat, TrendPoint, Mail, Todo,
  EWOItem, TIRItem,
  TimelineNode, MilestoneRule, MilestoneEvaluation,
} from '@/types';
import type {
  IssueOut, IssueStatsOut, MilestoneOut, MailOut, TodoOut,
  EWOOut, TIROut,
  TimelineNodeOut, MilestoneRuleOut, MilestoneEvaluationOut,
} from '@/services/api';

/** 截取 ISO 日期时间到日期部分 */
function fmtDate(iso: string | null): string {
  if (!iso) return '';
  return iso.slice(0, 10);
}

export function toIssue(o: IssueOut): Issue {
  return {
    id: o.id,
    priority: o.priority,
    component: o.component,
    description: o.description,
    department: o.department,
    status: o.status,
    assignee: o.assignee,
    partSystem: o.part_system ?? null,
    subSystem: o.sub_system ?? null,
    rootCause: o.root_cause ?? null,
    shortTermAction: o.short_term_action ?? null,
    longTermAction: o.long_term_action ?? null,
    cutoffPoint: o.cutoff_point ?? null,
    actionPlan: o.action_plan ?? null,
    source: o.source ?? null,
    sourceFile: o.source_file ?? null,
    createdAt: fmtDate(o.created_at),
    updatedAt: fmtDate(o.updated_at),
  };
}

export function toStats(s: IssueStatsOut): IssueStats {
  return {
    totalOpen: s.total_open,
    newThisWeek: s.new_this_week,
    closedThisWeek: s.closed_this_week,
    highRiskCount: s.high_risk_count,
    departmentStats: s.department_stats.map((d) => ({
      department: d.department,
      closedRate: d.closed_rate,
      totalIssues: d.total_issues,
    } as DepartmentStat)),
    trend: s.trend.map((t) => ({ date: t.date, count: t.count } as TrendPoint)),
  };
}

export function toMilestone(m: MilestoneOut): Milestone {
  return {
    id: m.id,
    name: m.name,
    category: m.category,
    percentage: m.percentage,
    targetDate: m.target_date ?? null,
    actualDate: m.actual_date ?? null,
    actualPercentage: m.actual_percentage ?? null,
  };
}

export function toMail(m: MailOut): Mail {
  return {
    id: m.id,
    sender: m.sender,
    subject: m.subject,
    preview: m.preview ?? '',
    date: m.date,
    isRead: m.is_read,
    isStarred: m.is_starred,
    hasAttachment: m.has_attachment,
    category: m.category ?? '',
  };
}

export function toTodo(t: TodoOut): Todo {
  return {
    id: t.id,
    content: t.content,
    source: t.source ?? '',
    deadline: t.deadline ?? '',
    completed: t.completed,
    createdAt: t.created_at ?? '',
  };
}

export function toEWO(e: EWOOut): EWOItem {
  return {
    id: e.id,
    type: e.type,
    title: e.title,
    description: e.description,
    severity: e.severity,
    status: e.status,
    department: e.department,
    assignee: e.assignee,
    raisedDate: fmtDate(e.raised_date),
    targetDate: fmtDate(e.target_date),
    source: e.source ?? null,
    sourceFile: e.source_file ?? null,
    createdAt: fmtDate(e.created_at),
    updatedAt: fmtDate(e.updated_at),
  };
}

export function toTIR(t: TIROut): TIRItem {
  return {
    id: t.id,
    title: t.title,
    description: t.description,
    category: t.category,
    status: t.status,
    department: t.department,
    assignee: t.assignee,
    testDate: fmtDate(t.test_date),
    result: t.result,
    source: t.source ?? null,
    sourceFile: t.source_file ?? null,
    createdAt: fmtDate(t.created_at),
    updatedAt: fmtDate(t.updated_at),
  };
}
export function toTimelineNode(o: TimelineNodeOut): TimelineNode {
  return {
    id: o.id,
    name: o.name,
    targetDate: o.target_date ?? null,
    actualDate: o.actual_date ?? null,
    description: o.description ?? null,
    sortOrder: o.sort_order,
    status: o.status as TimelineNode['status'],
    createdAt: o.created_at ?? null,
    updatedAt: o.updated_at ?? null,
  };
}

export function toMilestoneRule(o: MilestoneRuleOut): MilestoneRule {
  return {
    id: o.id,
    name: o.name,
    timelineNodeId: o.timeline_node_id ?? null,
    category: o.category,
    conditionType: o.condition_type as MilestoneRule['conditionType'],
    conditionConfig: o.condition_config ?? null,
    targetValue: o.target_value,
    sortOrder: o.sort_order,
    isActive: o.is_active,
    createdAt: o.created_at ?? null,
    updatedAt: o.updated_at ?? null,
  };
}

export function toMilestoneEvaluation(o: MilestoneEvaluationOut): MilestoneEvaluation {
  return {
    evaluationId: o.evaluation_id,
    ruleId: o.rule_id,
    ruleName: o.rule_name,
    timelineNodeName: o.timeline_node_name ?? null,
    category: o.category,
    conditionType: o.condition_type,
    currentValue: o.current_value,
    targetValue: o.target_value,
    status: o.status as MilestoneEvaluation['status'],
    notes: o.notes ?? null,
    evaluatedAt: o.evaluated_at ?? null,
  };
}
