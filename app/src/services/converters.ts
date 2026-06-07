/**
 * 后端 snake_case -> 前端 camelCase 转换器。
 */

import type {
  Issue, IssueStats, Milestone, DepartmentStat, TrendPoint, Mail, Todo,
  EWOItem, TIRItem,
} from '@/types';
import type {
  IssueOut, IssueStatsOut, MilestoneOut, MailOut, TodoOut,
  EWOOut, TIROut,
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
    targetDate: m.target_date,
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
    createdAt: fmtDate(t.created_at),
    updatedAt: fmtDate(t.updated_at),
  };
}