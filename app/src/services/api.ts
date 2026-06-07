/**
 * API Service - 与后端 FastAPI 通信的统一层。
 * 所有接口调用均通过此模块，统一错误处理、超时控制、离线检测。
 */

const API_BASE = '/api';
const DEFAULT_TIMEOUT = 10000;

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

interface ApiResponse<T = unknown> {
  success: boolean;
  data: T | null;
  message: string | null;
}

// ---------------------------------------------------------------------------
// 通用 fetch 封装
// ---------------------------------------------------------------------------

async function request<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
  timeout = DEFAULT_TIMEOUT,
): Promise<ApiResponse<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const opts: RequestInit = {
      method,
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(`${API_BASE}${path}`, opts);
    return (await res.json()) as ApiResponse<T>;
  } catch (err) {
    const msg = err instanceof DOMException && err.name === 'AbortError'
      ? '请求超时'
      : '网络错误，后端不可达';
    return { success: false, data: null, message: msg };
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// 公开方法
// ---------------------------------------------------------------------------

export const api = {
  get:  <T>(path: string, timeout?: number) => request<T>('GET', path, undefined, timeout),
  post: <T>(path: string, body?: unknown, timeout?: number) => request<T>('POST', path, body, timeout),
  put:  <T>(path: string, body?: unknown, timeout?: number) => request<T>('PUT', path, body, timeout),
  del:  <T>(path: string, timeout?: number) => request<T>('DELETE', path, undefined, timeout),

  /** 上传 multipart/form-data */
  async upload<T>(path: string, formData: FormData, timeout = 60000): Promise<ApiResponse<T>> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });
      return (await res.json()) as ApiResponse<T>;
    } catch (err) {
      const msg = err instanceof DOMException && err.name === 'AbortError'
        ? '上传超时'
        : '网络错误，后端不可达';
      return { success: false, data: null, message: msg };
    } finally {
      clearTimeout(timer);
    }
  },

  /** 下载文件（触发浏览器下载） */
  download(filePath: string) {
    window.open(`${API_BASE}/download?path=${encodeURIComponent(filePath)}`, '_blank');
  },

  /** Excel 导入（issues / ewo / tir 共用） */
  async importExcel<T>(endpoint: string, file: File, timeout = 120000): Promise<ApiResponse<T>> {
    const fd = new FormData();
    fd.append('files', file);
    return this.upload<T>(endpoint, fd, timeout);
  },

  /** 检测后端是否可达 */
  async healthCheck(): Promise<boolean> {
    const res = await request<unknown>('GET', '/issues/stats', undefined, 3000);
    return res.success;
  },
};

// ---------------------------------------------------------------------------
// 后端返回的业务类型
// ---------------------------------------------------------------------------

export interface IssueOut {
  id: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  component: string;
  description: string;
  department: string;
  status: 'open' | 'in_progress' | 'resolved' | 'closed';
  assignee: string | null;
  part_system: string | null;
  sub_system: string | null;
  root_cause: string | null;
  short_term_action: string | null;
  long_term_action: string | null;
  cutoff_point: string | null;
  action_plan: string | null;
  source: string | null;
  source_file: string | null;
  created_at: string;
  updated_at: string;
}

export interface IssueStatsOut {
  total_open: number;
  new_this_week: number;
  closed_this_week: number;
  high_risk_count: number;
  department_stats: { department: string; closed_rate: number; total_issues: number }[];
  trend: { date: string; count: number }[];
}

export interface MilestoneOut {
  id: number;
  name: string;
  category: string;
  percentage: number;
  target_date: string | null;
  actual_date: string | null;
  actual_percentage: number | null;
}

export interface MailOut {
  id: string;
  sender: string;
  subject: string;
  preview: string | null;
  date: string;
  is_read: boolean;
  is_starred: boolean;
  has_attachment: boolean;
  category: string | null;
}

export interface TodoOut {
  id: string;
  content: string;
  source: string | null;
  deadline: string | null;
  completed: boolean;
  created_at: string | null;
}

export interface TemplateOut {
  id: string;
  name: string;
  description: string;
  slides: number;
}

export interface ExcelMergeResult {
  file_path: string;
  file_name: string;
  sheet_count: number;
}

export interface ExcelMergeSameResult {
  file_path: string;
  file_name: string;
  row_count: number;
}

export interface ExcelRenameResult {
  renamed_files: { old: string; new: string }[];
  skipped_files: string[];
  count: number;
}

export interface PPTResult {
  file_path: string;
  file_name: string;
}

export interface CrawlerFetchResult {
  url: string;
  title: string;
  content: string;
  browser_used: string;
}

export interface CrawlerTableResult {
  headers: string[];
  rows: string[][];
  row_count: number;
}

export interface FeishuSyncResult {
  synced_count: number;
  new_count: number;
  demo: boolean;
}

export interface TodoToggleResult {
  id: string;
  completed: boolean;
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

// ---------------------------------------------------------------------------
// Dashboard / Deliverable Categories
// ---------------------------------------------------------------------------

export interface DeliverableCategoryOut {
  id: string;
  name: string;
  icon: string | null;
  sort_order: number;
  is_visible: boolean;
}

export interface DashboardOverviewOut {
  total_issues: number;
  open_issues: number;
  closed_rate: number;
  high_risk_count: number;
  new_this_week: number;
  closed_this_week: number;
  milestone_progress: { name: string; percentage: number; actual_percentage: number | null; target_date: string | null; actual_date: string | null; category: string }[];
  completion_pie: { name: string; value: number; color: string }[];
  department_bar: { department: string; total: number; closed: number }[];
  trend: { date: string; count: number }[];
  deliverable_counts: Record<string, number>;
}

export interface LayoutCardOut {
  id: number;
  page_key: string;
  card_id: string;
  card_type: string;
  x: number;
  y: number;
  w: number;
  h: number;
  config?: string;
}

// ---------------------------------------------------------------------------
// EWO/NCR
// ---------------------------------------------------------------------------

export interface EWOOut {
  id: string;
  type: 'EWO' | 'NCR';
  title: string;
  description: string | null;
  severity: 'critical' | 'major' | 'minor';
  status: 'open' | 'investigating' | 'resolved' | 'closed';
  department: string | null;
  assignee: string | null;
  raised_date: string | null;
  target_date: string | null;
  source: string | null;
  source_file: string | null;
  created_at: string;
  updated_at: string;
}

export interface EWOStatsOut {
  total: number;
  open: number;
  critical_risk: number;
  by_type: Record<string, number>;
}

// ---------------------------------------------------------------------------
// TIR
// ---------------------------------------------------------------------------

export interface TIROut {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  status: 'draft' | 'submitted' | 'approved' | 'rejected';
  department: string | null;
  assignee: string | null;
  test_date: string | null;
  result: string | null;
  source: string | null;
  source_file: string | null;
  created_at: string;
  updated_at: string;
}

export interface TIRStatsOut {
  total: number;
  approved: number;
  pending: number;
  by_category: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Excel Import
// ---------------------------------------------------------------------------

export interface ExcelImportResult {
  created: number;
  updated: number;
  errors: string[];
}

// ---------------------------------------------------------------------------
// Lookup - 零件总成 / 工程师
// ---------------------------------------------------------------------------

export interface PartSystemOut {
  part_system: string;
  sub_system: string;
}

export interface EngineerOut {
  name: string;
  department: string;
}