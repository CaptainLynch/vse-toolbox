/**
 * 前端类型定义 - 与后�?Pydantic schemas 对齐�? *
 * 命名约定：后端用 snake_case，前�?UI 组件内部�?camelCase�? * 此文件定义前端内部使用的 camelCase 类型�? */

// ---------------------------------------------------------------------------
// 问题追踪
// ---------------------------------------------------------------------------

export interface Issue {
  id: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  component: string;
  description: string;
  department: string;
  status: 'open' | 'in_progress' | 'resolved' | 'closed';
  assignee: string | null;
  partSystem: string | null;
  subSystem: string | null;
  rootCause: string | null;
  shortTermAction: string | null;
  longTermAction: string | null;
  cutoffPoint: string | null;
  actionPlan: string | null;
  source: string | null;
  sourceFile: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface IssueStats {
  totalOpen: number;
  newThisWeek: number;
  closedThisWeek: number;
  highRiskCount: number;
  departmentStats: DepartmentStat[];
  trend: TrendPoint[];
}

export interface DepartmentStat {
  department: string;
  closedRate: number;
  totalIssues: number;
}

export interface TrendPoint {
  date: string;
  count: number;
}

// ---------------------------------------------------------------------------
// 里程�?// ---------------------------------------------------------------------------

export interface Milestone {
  id: number;
  name: string;
  category: string;
  percentage: number;
  targetDate: string | null;
  actualDate: string | null;
  actualPercentage: number | null;
}

// ---------------------------------------------------------------------------
// KPI
// ---------------------------------------------------------------------------

export interface KpiCard {
  label: string;
  value: number;
  change: number;
  changeType: 'positive' | 'negative';
}

// ---------------------------------------------------------------------------
// 工具矩阵
// ---------------------------------------------------------------------------

export interface ToolCard {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  status: 'ready' | 'planned' | 'beta';
}

// ---------------------------------------------------------------------------
// 飞书邮件 / 待办
// ---------------------------------------------------------------------------

export interface Mail {
  id: string;
  sender: string;
  subject: string;
  preview: string;
  date: string;
  isRead: boolean;
  isStarred: boolean;
  hasAttachment: boolean;
  category: string;
}

export interface Todo {
  id: string;
  content: string;
  source: string;
  deadline: string;
  completed: boolean;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Deliverable Categories
// ---------------------------------------------------------------------------

export interface DeliverableCategory {
  id: string;
  name: string;
  icon: string | null;
  sortOrder: number;
  isVisible: boolean;
}

// ---------------------------------------------------------------------------
// Dashboard Layouts
// ---------------------------------------------------------------------------

export interface LayoutCard {
  id?: number;
  pageKey: string;
  cardId: string;
  cardType: string;
  x: number;
  y: number;
  w: number;
  h: number;
  config?: string;
}

// ---------------------------------------------------------------------------
// Dashboard Overview
// ---------------------------------------------------------------------------

export interface DashboardOverview {
  totalIssues: number;
  openIssues: number;
  closedRate: number;
  highRiskCount: number;
  newThisWeek: number;
  closedThisWeek: number;
  milestoneProgress: { name: string; percentage: number; actualPercentage: number | null; targetDate: string | null; actualDate: string | null; category: string }[];
  completionPie: { name: string; value: number; color: string }[];
  departmentBar: { department: string; total: number; closed: number }[];
  trend: { date: string; count: number }[];
  deliverableCounts: Record<string, number>;
}

// ---------------------------------------------------------------------------
// EWO/NCR
// ---------------------------------------------------------------------------

export interface EWOItem {
  id: string;
  type: 'EWO' | 'NCR';
  title: string;
  description: string | null;
  severity: 'critical' | 'major' | 'minor';
  status: 'open' | 'investigating' | 'resolved' | 'closed';
  department: string | null;
  assignee: string | null;
  raisedDate: string | null;
  targetDate: string | null;
  source: string | null;
  sourceFile: string | null;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// TIR
// ---------------------------------------------------------------------------

export interface TIRItem {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  status: 'draft' | 'submitted' | 'approved' | 'rejected';
  department: string | null;
  assignee: string | null;
  testDate: string | null;
  result: string | null;
  source: string | null;
  sourceFile: string | null;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface Setting {
  key: string;
  value: string;
}
// ---------------------------------------------------------------------------
// Timeline Nodes
// ---------------------------------------------------------------------------

export interface TimelineNode {
  id: number;
  name: string;
  targetDate: string | null;
  actualDate: string | null;
  description: string | null;
  sortOrder: number;
  status: 'pending' | 'in_progress' | 'completed' | 'delayed';
  createdAt: string | null;
  updatedAt: string | null;
}

// ---------------------------------------------------------------------------
// Milestone Rules
// ---------------------------------------------------------------------------

export interface MilestoneRule {
  id: number;
  name: string;
  timelineNodeId: number | null;
  category: string;
  conditionType: 'count_threshold' | 'status_match' | 'manual';
  conditionConfig: Record<string, unknown> | null;
  targetValue: number;
  sortOrder: number;
  isActive: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

// ---------------------------------------------------------------------------
// Milestone Evaluations
// ---------------------------------------------------------------------------

export interface MilestoneEvaluation {
  evaluationId: number;
  ruleId: number;
  ruleName: string;
  timelineNodeName: string | null;
  category: string;
  conditionType: string;
  currentValue: number;
  targetValue: number;
  status: 'not_started' | 'in_progress' | 'completed' | 'blocked';
  notes: string | null;
  evaluatedAt: string | null;
}