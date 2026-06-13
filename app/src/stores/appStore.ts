import { create } from 'zustand';
import type {
  Issue, IssueStats, Milestone, ToolCard, Mail, Todo,
  DeliverableCategory, LayoutCard, DashboardOverview,
  EWOItem, TIRItem,
  TimelineNode, MilestoneRule, MilestoneEvaluation,
} from '@/types';
import type {
  MailOut, TodoOut, PaginatedData, EWOOut, TIROut,
  ExcelImportResult,
  TimelineNodeOut, MilestoneRuleOut, MilestoneEvaluationOut,
} from '@/services/api';
import { api } from '@/services/api';
import { toIssue, toStats, toMilestone, toMail, toTodo, toEWO, toTIR, toTimelineNode, toMilestoneRule, toMilestoneEvaluation } from '@/services/converters';

// ---------------------------------------------------------------------------
// 鐘舵€佹帴鍙?
// ---------------------------------------------------------------------------

interface AppState {
  // Navigation
  currentPage: string;
  setCurrentPage: (page: string) => void;
  activeSubPage: string;
  setActiveSubPage: (page: string) => void;
  isSidebarOpen: boolean;
  toggleSidebar: () => void;

  // Loading
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // Offline
  isOnline: boolean;
  setOnline: (v: boolean) => void;

  // Issues
  issues: Issue[];
  issueTotal: number;
  issuePage: number;
  setIssuePage: (p: number) => void;
  fetchIssues: (opts?: { page?: number; size?: number; priority?: string; status?: string; department?: string }) => Promise<void>;
  createIssue: (data: { priority: string; component: string; description: string; department: string; assignee?: string; part_system?: string; sub_system?: string; root_cause?: string; short_term_action?: string; long_term_action?: string; cutoff_point?: string; action_plan?: string }) => Promise<boolean>;
  updateIssue: (id: string, data: Partial<Issue>) => Promise<boolean>;
  deleteIssue: (id: string) => Promise<boolean>;
  importIssuesExcel: (file: File) => Promise<ExcelImportResult | null>;

  // Stats
  stats: IssueStats | null;
  fetchStats: () => Promise<void>;

  // Milestones
  milestones: Milestone[];
  fetchMilestones: () => Promise<void>;
  createMilestone: (data: { name: string; category: string; percentage?: number; target_date?: string }) => Promise<boolean>;
  updateMilestone: (id: number, data: Partial<Milestone>) => Promise<boolean>;
  deleteMilestone: (id: number) => Promise<boolean>;

  // Tools
  tools: ToolCard[];

  // Feishu
  mails: Mail[];
  mailTotal: number;
  todos: Todo[];
  fetchMails: (opts?: { page?: number; size?: number }) => Promise<void>;
  syncMails: () => Promise<{ synced: number; fresh: number; demo: boolean } | null>;
  fetchTodos: () => Promise<void>;
  toggleTodo: (id: string) => Promise<boolean>;

  // Deliverable Categories
  deliverableCategories: DeliverableCategory[];
  fetchDeliverableCategories: () => Promise<void>;
  createDeliverableCategory: (data: { id: string; name: string; icon?: string }) => Promise<boolean>;

  // Dashboard Overview
  dashboardOverview: DashboardOverview | null;
  fetchDashboardOverview: () => Promise<void>;

  // Layouts
  layouts: Record<string, LayoutCard[]>;
  fetchLayouts: (pageKey: string) => Promise<void>;
  saveLayouts: (pageKey: string, layouts: LayoutCard[]) => Promise<void>;

  // EWO/NCR
  ewos: EWOItem[];
  ewoTotal: number;
  ewoPage: number;
  setEwoPage: (p: number) => void;
  fetchEwos: (opts?: { page?: number; size?: number; status?: string; severity?: string }) => Promise<void>;
  createEwo: (data: { type?: string; title: string; description?: string; severity?: string; department?: string; assignee?: string }) => Promise<boolean>;
  deleteEwo: (id: string) => Promise<boolean>;

  // TIR
  tirs: TIRItem[];
  tirTotal: number;
  tirPage: number;
  setTirPage: (p: number) => void;
  fetchTirs: (opts?: { page?: number; size?: number; status?: string; category?: string }) => Promise<void>;
  createTir: (data: { title: string; description?: string; category?: string; department?: string; assignee?: string }) => Promise<boolean>;
  deleteTir: (id: string) => Promise<boolean>;
  importTirsExcel: (file: File) => Promise<ExcelImportResult | null>;

  // EWO Excel import
  importEwosExcel: (file: File) => Promise<ExcelImportResult | null>;

  // Settings
  settings: Record<string, string>;
  fetchSettings: () => Promise<void>;
  updateSetting: (key: string, value: string) => Promise<boolean>;

  // Timeline Nodes
  timelineNodes: TimelineNode[];
  fetchTimelineNodes: () => Promise<void>;
  createTimelineNode: (data: Partial<TimelineNode>) => Promise<boolean>;
  updateTimelineNode: (id: number, data: Partial<TimelineNode>) => Promise<boolean>;
  deleteTimelineNode: (id: number) => Promise<boolean>;

  // Milestone Rules
  milestoneRules: MilestoneRule[];
  fetchMilestoneRules: (timelineNodeId?: number) => Promise<void>;
  createMilestoneRule: (data: Partial<MilestoneRule>) => Promise<boolean>;
  updateMilestoneRule: (id: number, data: Partial<MilestoneRule>) => Promise<boolean>;
  deleteMilestoneRule: (id: number) => Promise<boolean>;

  // Milestone Evaluations
  milestoneEvaluations: MilestoneEvaluation[];
  fetchMilestoneEvaluations: (timelineNodeId?: number) => Promise<void>;
  refreshMilestoneEvaluations: (timelineNodeId?: number) => Promise<void>;
  updateMilestoneEvaluation: (id: number, data: { notes?: string; status?: string }) => Promise<boolean>;

  // Selected Timeline Node (for filtering)
  selectedTimelineNodeId: number | null;
  setSelectedTimelineNodeId: (id: number | null) => void;
}

const mockIssues = [
  { id: 'ISS-2024-001', priority: 'P0' as const, component: 'Front Bumper', description: 'Gap exceeds 2.5mm at fender joint', department: 'Body', status: 'open' as const, createdAt: '2024-01-10', assignee: 'Zhang Wei', updatedAt: '2024-01-10', partSystem: 'Body Assembly', subSystem: 'Exterior', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-002', priority: 'P1' as const, component: 'Instrument Panel', description: 'Surface shrinkage marks visible, needs injection optimization', department: 'Interior', status: 'in_progress' as const, createdAt: '2024-01-14', assignee: 'Li Fang', updatedAt: '2024-01-14', partSystem: 'Instrument Panel', subSystem: 'Interior', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-003', priority: 'P2' as const, component: 'Headlamp', description: 'LED DRL color temperature deviation, pending design confirmation', department: 'Lighting', status: 'open' as const, createdAt: '2024-01-15', assignee: 'Wang Ming', updatedAt: '2024-01-15', partSystem: 'Lighting', subSystem: 'Front Lighting', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-004', priority: 'P1' as const, component: 'Door Seal', description: 'Compression load does not meet waterproof requirement', department: 'Body', status: 'open' as const, createdAt: '2024-01-16', assignee: 'Chen Jie', updatedAt: '2024-01-16', partSystem: 'Body Assembly', subSystem: 'Sealing', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-005', priority: 'P0' as const, component: 'Taillight', description: 'Seal failure causing water ingress and fogging', department: 'Lighting', status: 'in_progress' as const, createdAt: '2024-01-17', assignee: 'Liu Yang', updatedAt: '2024-01-17', partSystem: 'Lighting', subSystem: 'Rear Lighting', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-006', priority: 'P3' as const, component: 'Seat Frame', description: 'Seat adjustment noise, needs lubrication', department: 'Interior', status: 'closed' as const, createdAt: '2024-01-18', assignee: 'Zhao Qiang', updatedAt: '2024-01-18', partSystem: 'Seat', subSystem: 'Interior', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-007', priority: 'P2' as const, component: 'Engine Hood', description: 'Flush gap inconsistent after closing', department: 'Body', status: 'open' as const, createdAt: '2024-01-19', assignee: 'Sun Lei', updatedAt: '2024-01-19', partSystem: 'Body Assembly', subSystem: 'Closure', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-008', priority: 'P1' as const, component: 'Rearview Mirror', description: 'Motor over-temperature protection during folding', department: 'Interior', status: 'open' as const, createdAt: '2024-01-20', assignee: 'Zhou Hua', updatedAt: '2024-01-20', partSystem: 'Exterior Mirror', subSystem: 'Exterior', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-009', priority: 'P2' as const, component: 'Fog Lamp', description: 'Installation angle mismatch with design', department: 'Lighting', status: 'open' as const, createdAt: '2024-01-21', assignee: 'Wu Jie', updatedAt: '2024-01-21', partSystem: 'Lighting', subSystem: 'Front Lighting', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
  { id: 'ISS-2024-010', priority: 'P3' as const, component: 'Door Trim', description: 'Mounting hole offset 2mm', department: 'Body', status: 'open' as const, createdAt: '2024-01-22', assignee: 'Xu Dong', updatedAt: '2024-01-22', partSystem: 'Body Assembly', subSystem: 'Interior', rootCause: null, shortTermAction: null, longTermAction: null, cutoffPoint: null, actionPlan: null, source: 'manual', sourceFile: null },
];
const mockMilestones = [
  { id: 1, name: 'Body Sheet Metal Assembly', percentage: 85, category: 'Body', targetDate: '2024-03-15', actualDate: '2024-03-12', actualPercentage: 88 },
  { id: 2, name: 'Interior Trim Matching', percentage: 62, category: 'Interior', targetDate: '2024-04-01', actualDate: null, actualPercentage: null },
  { id: 3, name: 'Lighting Verification', percentage: 78, category: 'Lighting', targetDate: '2024-03-20', actualDate: '2024-03-18', actualPercentage: 80 },
  { id: 4, name: 'Vehicle Seal Test', percentage: 45, category: 'General', targetDate: '2024-04-15', actualDate: null, actualPercentage: null },
  { id: 5, name: 'NVH Performance', percentage: 30, category: 'General', targetDate: '2024-05-01', actualDate: null, actualPercentage: null },
];
const mockStats = {
  totalOpen: 5, newThisWeek: 5, closedThisWeek: 0, highRiskCount: 2,
  departmentStats: [
    { department: 'Body', closedRate: 0, totalIssues: 2 },
    { department: 'Interior', closedRate: 0, totalIssues: 1 },
    { department: 'Lighting', closedRate: 0, totalIssues: 1 },
    { department: 'Assembly', closedRate: 0, totalIssues: 0 },
  ],
  trend: Array.from({ length: 15 }, (_, i) => ({ date: '05-' + String(13 + i).padStart(2, '0'), count: 0 })),
};
const mockTools = [
  { id: 'excel-merge', name: 'Excel Batch Merge', description: 'Merge multiple deliverable spreadsheets with auto-dedup', icon: 'FileSpreadsheet', category: 'Data', status: 'ready' as const },
  { id: 'excel-rename', name: 'Excel Batch Rename', description: 'Batch rename files by rules, supports regex', icon: 'FileEdit', category: 'Data', status: 'ready' as const },
  { id: 'excel-same', name: 'Same-Structure Merge', description: 'Vertically join multiple same-structure Excel sheets', icon: 'FileSpreadsheet', category: 'Data', status: 'ready' as const },
  { id: 'web-crawler', name: 'Intranet Data Crawler', description: 'Auto-fetch deliverable data from intranet pages', icon: 'Globe', category: 'Collection', status: 'ready' as const },
  { id: 'ppt-weekly', name: 'Weekly PPT Generator', description: 'Auto-generate weekly report PPT from issue data', icon: 'Presentation', category: 'Reporting', status: 'ready' as const },
  { id: 'ppt-deliverable', name: 'Deliverable PPT', description: 'Convert deliverable data to standard PPT format', icon: 'FileStack', category: 'Reporting', status: 'ready' as const },
  { id: 'feishu-mail', name: 'Feishu Mail Assistant', description: 'View Feishu emails and auto-generate todo tasks', icon: 'Mail', category: 'Collaboration', status: 'ready' as const },
  { id: 'task-track', name: 'Task Assignment Tracker', description: 'Batch assign tasks and track completion', icon: 'ListChecks', category: 'Management', status: 'ready' as const },
  { id: 'risk-warn', name: 'Risk Warning System', description: 'Auto-assess risk level based on milestone deliverables', icon: 'AlertTriangle', category: 'Analytics', status: 'planned' as const },
  { id: 'ai-assistant', name: 'AI Assistant', description: 'Voice interaction, smart Q&A and data analysis', icon: 'Sparkles', category: 'Analytics', status: 'planned' as const },
];
const mockMails = [
  { id: 'M001', sender: 'Li Ming - Body Engineering', subject: '[Deliverable] Body Sheet Metal DV Test Report', preview: 'Attached is the body sheet metal DV test report, please review.', date: '2024-01-15', isRead: false, isStarred: false, hasAttachment: false, category: 'inbox' },
  { id: 'M002', sender: 'Wang Fang - Interior Dept', subject: 'Instrument Panel Surface Shrinkage Issue', preview: 'After supplier discussion, injection temperature adjustment has significantly improved shrinkage.', date: '2024-01-14', isRead: true, isStarred: false, hasAttachment: false, category: 'inbox' },
  { id: 'M003', sender: 'Zhang Zong - PM Dept', subject: '[URGENT] Friday Vehicle Build Review Meeting Notice', preview: 'This Friday 14:00 vehicle build phase review meeting, please prepare materials.', date: '2024-01-13', isRead: false, isStarred: false, hasAttachment: false, category: 'inbox' },
];
const mockTodos = [
  { id: 'T001', content: 'Review Body Sheet Metal DV Test Report', source: 'Li Ming Email', deadline: 'Today', completed: false, createdAt: '' },
  { id: 'T002', content: 'Confirm Instrument Panel Shrinkage Process Plan', source: 'Wang Fang Email', deadline: 'Today', completed: false, createdAt: '' },
  { id: 'T003', content: 'Prepare Friday Vehicle Build Review Materials', source: 'Zhang Zong Email', deadline: 'Tomorrow', completed: false, createdAt: '' },
];

export const useAppStore = create<AppState>((set, get) => ({
  currentPage: 'analytics',
  setCurrentPage: (page) => set({ currentPage: page }),
  activeSubPage: 'overview',
  setActiveSubPage: (page) => set({ activeSubPage: page }),
  isSidebarOpen: true,
  toggleSidebar: () => set((s) => ({ isSidebarOpen: !s.isSidebarOpen })),
  isLoading: true,
  setIsLoading: (loading) => set({ isLoading: loading }),
  isOnline: true,
  setOnline: (v) => set({ isOnline: v }),
  issues: mockIssues,
  issueTotal: mockIssues.length,
  issuePage: 1,
  setIssuePage: (p) => set({ issuePage: p }),
  fetchIssues: async (opts) => {
    const page = opts?.page ?? 1;
    const size = opts?.size ?? 10;
    const params = new URLSearchParams({ page: String(page), size: String(size) });
    if (opts?.priority) params.set('priority', opts.priority);
    if (opts?.status) params.set('status', opts.status);
    if (opts?.department) params.set('department', opts.department);
    const res = await api.get<PaginatedData<import('@/services/api').IssueOut>>('/issues?' + params);
    if (res.success && res.data) {
      set({ issues: res.data.items.map(toIssue), issueTotal: res.data.total, issuePage: res.data.page, isOnline: true });
    } else { set({ isOnline: false }); }
  },
  createIssue: async (data) => {
    const res = await api.post<import('@/services/api').IssueOut>('/issues', data);
    if (res.success && res.data) { set((s) => ({ issues: [toIssue(res.data!), ...s.issues] })); return true; }
    return false;
  },
  updateIssue: async (id, data) => {
    const body: Record<string, unknown> = {};
    if (data.priority !== undefined) body.priority = data.priority;
    if (data.component !== undefined) body.component = data.component;
    if (data.description !== undefined) body.description = data.description;
    if (data.department !== undefined) body.department = data.department;
    if (data.status !== undefined) body.status = data.status;
    if (data.assignee !== undefined) body.assignee = data.assignee;
    if (data.partSystem !== undefined) body.part_system = data.partSystem;
    if (data.subSystem !== undefined) body.sub_system = data.subSystem;
    if (data.rootCause !== undefined) body.root_cause = data.rootCause;
    if (data.shortTermAction !== undefined) body.short_term_action = data.shortTermAction;
    if (data.longTermAction !== undefined) body.long_term_action = data.longTermAction;
    if (data.cutoffPoint !== undefined) body.cutoff_point = data.cutoffPoint;
    if (data.actionPlan !== undefined) body.action_plan = data.actionPlan;
    if (data.source !== undefined) body.source = data.source;
    if (data.sourceFile !== undefined) body.source_file = data.sourceFile;
    const res = await api.put<import('@/services/api').IssueOut>('/issues/' + id, body);
    if (res.success && res.data) { set((s) => ({ issues: s.issues.map((i) => i.id === id ? toIssue(res.data!) : i) })); return true; }
    return false;
  },
  deleteIssue: async (id) => {
    const res = await api.del('/issues/' + id);
    if (res.success) { set((s) => ({ issues: s.issues.filter((i) => i.id !== id) })); return true; }
    return false;
  },
  importIssuesExcel: async (file) => {
    const res = await api.importExcel<ExcelImportResult>('/issues/import-excel', file);
    if (res.success && res.data) {
      await get().fetchIssues({ page: 1, size: 10 });
      await get().fetchStats();
      return res.data;
    }
    return null;
  },
  stats: mockStats,
  fetchStats: async () => {
    const res = await api.get<import('@/services/api').IssueStatsOut>('/issues/stats');
    if (res.success && res.data) { set({ stats: toStats(res.data), isOnline: true }); } else { set({ isOnline: false }); }
  },
  milestones: mockMilestones,
  fetchMilestones: async () => {
    const res = await api.get<import('@/services/api').MilestoneOut[]>('/milestones');
    if (res.success && res.data) { set({ milestones: res.data.map(toMilestone), isOnline: true }); }
    else { set({ isOnline: false }); }
  },
  createMilestone: async (data) => {
    const res = await api.post<import('@/services/api').MilestoneOut>('/milestones', data);
    if (res.success && res.data) { set((s) => ({ milestones: [...s.milestones, toMilestone(res.data!)] })); return true; }
    return false;
  },
  updateMilestone: async (id, data) => {
    const body: Record<string, unknown> = {};
    if (data.name !== undefined) body.name = data.name;
    if (data.category !== undefined) body.category = data.category;
    if (data.percentage !== undefined) body.percentage = data.percentage;
    if (data.targetDate !== undefined) body.target_date = data.targetDate;
    if (data.actualDate !== undefined) body.actual_date = data.actualDate;
    if (data.actualPercentage !== undefined) body.actual_percentage = data.actualPercentage;
    const res = await api.put<import('@/services/api').MilestoneOut>('/milestones/' + id, body);
    if (res.success && res.data) { set((s) => ({ milestones: s.milestones.map((m) => m.id === id ? toMilestone(res.data!) : m) })); return true; }
    return false;
  },
  deleteMilestone: async (id) => {
    const res = await api.del('/milestones/' + id);
    if (res.success) { set((s) => ({ milestones: s.milestones.filter((m) => m.id !== id) })); return true; }
    return false;
  },
  tools: mockTools,
  mails: mockMails,
  mailTotal: mockMails.length,
  todos: mockTodos,
  fetchMails: async (opts) => {
    const page = opts?.page ?? 1;
    const size = opts?.size ?? 20;
    const res = await api.get<{ items: MailOut[]; total: number }>('/feishu/mails?page=' + page + '&size=' + size);
    if (res.success && res.data) { set({ mails: res.data.items.map(toMail), mailTotal: res.data.total, isOnline: true }); }
    else { set({ isOnline: false }); }
  },
  syncMails: async () => {
    const res = await api.post<{ synced_count: number; new_count: number; demo: boolean }>('/feishu/sync');
    if (res.success && res.data) { await get().fetchMails(); return { synced: res.data.synced_count, fresh: res.data.new_count, demo: res.data.demo }; }
    return null;
  },
  fetchTodos: async () => {
    const res = await api.get<TodoOut[]>('/feishu/todos');
    if (res.success && res.data) { set({ todos: res.data.map(toTodo), isOnline: true }); }
    else { set({ isOnline: false }); }
  },
  toggleTodo: async (id) => {
    const res = await api.post<{ completed: boolean }>('/feishu/todo-toggle', { id });
    if (res.success && res.data) { set((s) => ({ todos: s.todos.map((t) => t.id === id ? { ...t, completed: res.data!.completed } : t) })); return true; }
    return false;
  },
  deliverableCategories: [],
  fetchDeliverableCategories: async () => {
    const res = await api.get<import('@/services/api').DeliverableCategoryOut[]>('/dashboard/deliverable-categories');
    if (res.success && res.data) {
      set({
        deliverableCategories: res.data.map((c) => ({
          id: c.id, name: c.name, icon: c.icon, sortOrder: c.sort_order, isVisible: c.is_visible,
        })),
      });
    }
  },
  createDeliverableCategory: async (data) => {
    const res = await api.post('/dashboard/deliverable-categories', data);
    if (res.success) { await get().fetchDeliverableCategories(); return true; }
    return false;
  },
  dashboardOverview: null,
  fetchDashboardOverview: async () => {
    const res = await api.get<import('@/services/api').DashboardOverviewOut>('/dashboard/overview');
    if (res.success && res.data) {
      set({
        dashboardOverview: {
          totalIssues: res.data.total_issues, openIssues: res.data.open_issues,
          closedRate: res.data.closed_rate, highRiskCount: res.data.high_risk_count,
          newThisWeek: res.data.new_this_week, closedThisWeek: res.data.closed_this_week,
          milestoneProgress: (res.data.milestone_progress ?? []).map((m) => ({
            name: m.name, percentage: m.percentage,
            actualPercentage: m.actual_percentage ?? null,
            targetDate: m.target_date ?? null, actualDate: m.actual_date ?? null,
            category: m.category,
          })),
          completionPie: res.data.completion_pie ?? [],
          departmentBar: res.data.department_bar ?? [],
          trend: res.data.trend, deliverableCounts: res.data.deliverable_counts,
        },
        isOnline: true,
      });
    } else {
      set({ isOnline: false });
    }
  },
  layouts: {},
  fetchLayouts: async (pageKey) => {
    const res = await api.get<import('@/services/api').LayoutCardOut[]>('/dashboard/layouts?page_key=' + pageKey);
    if (res.success && res.data) {
      set((s) => ({
        layouts: {
          ...s.layouts,
          [pageKey]: res.data!.map((c) => ({
            id: c.id, pageKey: c.page_key, cardId: c.card_id, cardType: c.card_type,
            x: c.x, y: c.y, w: c.w, h: c.h, config: c.config ?? undefined,
          })),
        },
      }));
    }
  },
  saveLayouts: async (pageKey, layoutCards) => {
    await api.put('/dashboard/layouts', {
      page_key: pageKey,
      layouts: layoutCards.map((c) => ({ card_id: c.cardId, card_type: c.cardType, x: c.x, y: c.y, w: c.w, h: c.h })),
    });
    set((s) => ({
      layouts: { ...s.layouts, [pageKey]: layoutCards.map((c) => ({ ...c, config: undefined })) },
    }));
  },

  // ---------------------------------------------------------------------------
  // EWO/NCR
  // ---------------------------------------------------------------------------
  ewos: [],
  ewoTotal: 0,
  ewoPage: 1,
  setEwoPage: (p) => set({ ewoPage: p }),
  fetchEwos: async (opts) => {
    const page = opts?.page ?? get().ewoPage;
    const size = opts?.size ?? 20;
    const params = new URLSearchParams({ page: String(page), size: String(size) });
    if (opts?.status) params.set('status', opts.status);
    if (opts?.severity) params.set('severity', opts.severity);
    const res = await api.get<PaginatedData<EWOOut>>('/ewo?' + params);
    if (res.success && res.data) {
      set({ ewos: res.data.items.map(toEWO), ewoTotal: res.data.total, ewoPage: res.data.page, isOnline: true });
    } else { set({ isOnline: false }); }
  },
  createEwo: async (data) => {
    const res = await api.post<EWOOut>('/ewo', data);
    if (res.success && res.data) { set((s) => ({ ewos: [toEWO(res.data!), ...s.ewos] })); return true; }
    return false;
  },
  deleteEwo: async (id) => {
    const res = await api.del('/ewo/' + id);
    if (res.success) { set((s) => ({ ewos: s.ewos.filter((e) => e.id !== id) })); return true; }
    return false;
  },

  // ---------------------------------------------------------------------------
  // TIR
  // ---------------------------------------------------------------------------
  tirs: [],
  tirTotal: 0,
  tirPage: 1,
  setTirPage: (p) => set({ tirPage: p }),
  fetchTirs: async (opts) => {
    const page = opts?.page ?? get().tirPage;
    const size = opts?.size ?? 20;
    const params = new URLSearchParams({ page: String(page), size: String(size) });
    if (opts?.status) params.set('status', opts.status);
    if (opts?.category) params.set('category', opts.category);
    const res = await api.get<PaginatedData<TIROut>>('/tir?' + params);
    if (res.success && res.data) {
      set({ tirs: res.data.items.map(toTIR), tirTotal: res.data.total, tirPage: res.data.page, isOnline: true });
    } else { set({ isOnline: false }); }
  },
  createTir: async (data) => {
    const res = await api.post<TIROut>('/tir', data);
    if (res.success && res.data) { set((s) => ({ tirs: [toTIR(res.data!), ...s.tirs] })); return true; }
    return false;
  },
  deleteTir: async (id) => {
    const res = await api.del('/tir/' + id);
    if (res.success) { set((s) => ({ tirs: s.tirs.filter((t) => t.id !== id) })); return true; }
    return false;
  },
  importTirsExcel: async (file) => {
    const res = await api.importExcel<ExcelImportResult>('/tir/import-excel', file);
    if (res.success && res.data) {
      await get().fetchTirs({ page: 1, size: 20 });
      return res.data;
    }
    return null;
  },

  // ---------------------------------------------------------------------------
  // EWO Excel import
  // ---------------------------------------------------------------------------
  importEwosExcel: async (file) => {
    const res = await api.importExcel<ExcelImportResult>('/ewo/import-excel', file);
    if (res.success && res.data) {
      await get().fetchEwos({ page: 1, size: 20 });
      return res.data;
    }
    return null;
  },

  // ---------------------------------------------------------------------------
  // Settings
  // ---------------------------------------------------------------------------
  settings: {},
  fetchSettings: async () => {
    const res = await api.get<Record<string, string>>('/settings');
    if (res.success && res.data) { set({ settings: res.data, isOnline: true }); }
  },
  updateSetting: async (key, value) => {
    const res = await api.put('/settings/' + key, { value });
    if (res.success) {
      set((s) => ({ settings: { ...s.settings, [key]: value } }));
      return true;
    }
    return false;
  },
  // ---------------------------------------------------------------------------
  // Timeline Nodes
  // ---------------------------------------------------------------------------
  timelineNodes: [],
  fetchTimelineNodes: async () => {
    try {
      const res = await api.get<TimelineNodeOut[]>('/timeline');
      if (res.success && res.data) { set({ timelineNodes: res.data.map(toTimelineNode) }); }
    } catch (e) { console.error('fetchTimelineNodes:', e); }
  },
  createTimelineNode: async (data) => {
    try {
      const body: Record<string, unknown> = {};
      if (data.name !== undefined) body.name = data.name;
      if (data.targetDate !== undefined) body.target_date = data.targetDate;
      if (data.actualDate !== undefined) body.actual_date = data.actualDate;
      if (data.description !== undefined) body.description = data.description;
      if (data.sortOrder !== undefined) body.sort_order = data.sortOrder;
      if (data.status !== undefined) body.status = data.status;
      const res = await api.post<TimelineNodeOut>('/timeline', body);
      if (res.success && res.data) { set((s) => ({ timelineNodes: [...s.timelineNodes, toTimelineNode(res.data!)] })); return true; }
    } catch (e) { console.error('createTimelineNode:', e); }
    return false;
  },
  updateTimelineNode: async (id, data) => {
    try {
      const body: Record<string, unknown> = {};
      if (data.name !== undefined) body.name = data.name;
      if (data.targetDate !== undefined) body.target_date = data.targetDate;
      if (data.actualDate !== undefined) body.actual_date = data.actualDate;
      if (data.description !== undefined) body.description = data.description;
      if (data.sortOrder !== undefined) body.sort_order = data.sortOrder;
      if (data.status !== undefined) body.status = data.status;
      const res = await api.put<TimelineNodeOut>('/timeline/' + id, body);
      if (res.success && res.data) { set((s) => ({ timelineNodes: s.timelineNodes.map((n) => n.id === id ? toTimelineNode(res.data!) : n) })); return true; }
    } catch (e) { console.error('updateTimelineNode:', e); }
    return false;
  },
  deleteTimelineNode: async (id) => {
    try {
      const res = await api.del('/timeline/' + id);
      if (res.success) { set((s) => ({ timelineNodes: s.timelineNodes.filter((n) => n.id !== id) })); return true; }
    } catch (e) { console.error('deleteTimelineNode:', e); }
    return false;
  },

  // ---------------------------------------------------------------------------
  // Milestone Rules
  // ---------------------------------------------------------------------------
  milestoneRules: [],
  fetchMilestoneRules: async (timelineNodeId?) => {
    try {
      const p = timelineNodeId ? '/milestone-rules?timeline_node_id=' + timelineNodeId : '/milestone-rules';
      const res = await api.get<MilestoneRuleOut[]>(p);
      if (res.success && res.data) { set({ milestoneRules: res.data.map(toMilestoneRule) }); }
    } catch (e) { console.error('fetchMilestoneRules:', e); }
  },
  createMilestoneRule: async (data) => {
    try {
      const body: Record<string, unknown> = {};
      if (data.name !== undefined) body.name = data.name;
      if (data.timelineNodeId !== undefined) body.timeline_node_id = data.timelineNodeId;
      if (data.category !== undefined) body.category = data.category;
      if (data.conditionType !== undefined) body.condition_type = data.conditionType;
      if (data.conditionConfig !== undefined) body.condition_config = data.conditionConfig;
      if (data.targetValue !== undefined) body.target_value = data.targetValue;
      if (data.sortOrder !== undefined) body.sort_order = data.sortOrder;
      if (data.isActive !== undefined) body.is_active = data.isActive;
      const res = await api.post<MilestoneRuleOut>('/milestone-rules', body);
      if (res.success && res.data) { set((s) => ({ milestoneRules: [...s.milestoneRules, toMilestoneRule(res.data!)] })); return true; }
    } catch (e) { console.error('createMilestoneRule:', e); }
    return false;
  },
  updateMilestoneRule: async (id, data) => {
    try {
      const body: Record<string, unknown> = {};
      if (data.name !== undefined) body.name = data.name;
      if (data.timelineNodeId !== undefined) body.timeline_node_id = data.timelineNodeId;
      if (data.category !== undefined) body.category = data.category;
      if (data.conditionType !== undefined) body.condition_type = data.conditionType;
      if (data.conditionConfig !== undefined) body.condition_config = data.conditionConfig;
      if (data.targetValue !== undefined) body.target_value = data.targetValue;
      if (data.sortOrder !== undefined) body.sort_order = data.sortOrder;
      if (data.isActive !== undefined) body.is_active = data.isActive;
      const res = await api.put<MilestoneRuleOut>('/milestone-rules/' + id, body);
      if (res.success && res.data) { set((s) => ({ milestoneRules: s.milestoneRules.map((r) => r.id === id ? toMilestoneRule(res.data!) : r) })); return true; }
    } catch (e) { console.error('updateMilestoneRule:', e); }
    return false;
  },
  deleteMilestoneRule: async (id) => {
    try {
      const res = await api.del('/milestone-rules/' + id);
      if (res.success) { set((s) => ({ milestoneRules: s.milestoneRules.filter((r) => r.id !== id) })); return true; }
    } catch (e) { console.error('deleteMilestoneRule:', e); }
    return false;
  },

  // ---------------------------------------------------------------------------
  // Milestone Evaluations
  // ---------------------------------------------------------------------------
  milestoneEvaluations: [],
  fetchMilestoneEvaluations: async (timelineNodeId?) => {
    try {
      const query = timelineNodeId ? '?timeline_node_id=' + timelineNodeId : '';
      const res = await api.get<MilestoneEvaluationOut[]>('/milestone-rules/evaluations' + query);
      if (res.success && res.data) { set({ milestoneEvaluations: res.data.map(toMilestoneEvaluation) }); }
    } catch (e) { console.error('fetchMilestoneEvaluations:', e); }
  },
  refreshMilestoneEvaluations: async (timelineNodeId?) => {
    try {
      await api.post('/milestone-rules/evaluations/refresh');
      const query = timelineNodeId ? '?timeline_node_id=' + timelineNodeId : '';
      const res = await api.get<MilestoneEvaluationOut[]>('/milestone-rules/evaluations' + query);
      if (res.success && res.data) { set({ milestoneEvaluations: res.data.map(toMilestoneEvaluation) }); }
    } catch (e) { console.error('refreshMilestoneEvaluations:', e); }
  },
  updateMilestoneEvaluation: async (id, data) => {
    try {
      const res = await api.put<MilestoneEvaluationOut>('/milestone-rules/evaluations/' + id, data);
      if (res.success && res.data) { set((s) => ({ milestoneEvaluations: s.milestoneEvaluations.map((e) => e.evaluationId === id ? toMilestoneEvaluation(res.data!) : e) })); }
    } catch (e) { console.error('updateMilestoneEvaluation:', e); }
    return false;
  },

  // ---------------------------------------------------------------------------
  // Selected Timeline Node
  // ---------------------------------------------------------------------------
  selectedTimelineNodeId: null,
  setSelectedTimelineNodeId: (id) => set({ selectedTimelineNodeId: id }),
}));