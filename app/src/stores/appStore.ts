import { create } from 'zustand';
import type {
  Issue, IssueStats, Milestone, ToolCard, Mail, Todo,
  DeliverableCategory, LayoutCard, DashboardOverview,
  EWOItem, TIRItem,
} from '@/types';
import type {
  MailOut, TodoOut, PaginatedData, EWOOut, TIROut,
} from '@/services/api';
import { api } from '@/services/api';
import { toIssue, toStats, toMilestone, toMail, toTodo, toEWO, toTIR } from '@/services/converters';

// ---------------------------------------------------------------------------
// 状态接口
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
  createIssue: (data: { priority: string; component: string; description: string; department: string; assignee?: string }) => Promise<boolean>;
  updateIssue: (id: string, data: Partial<Issue>) => Promise<boolean>;
  deleteIssue: (id: string) => Promise<boolean>;

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
}

const mockIssues = [
  { id: 'ISS-2024-001', priority: 'P0' as const, component: '前保险杠', description: '前保险杠与翼子板间隙超差 2.5mm', department: '车身钣金', status: 'open' as const, createdAt: '2024-01-15', assignee: '张伟', updatedAt: '2024-01-15' },
  { id: 'ISS-2024-002', priority: 'P1' as const, component: '仪表板', description: '仪表板表面缩痕明显，需优化注塑工艺', department: '内外饰件', status: 'in_progress' as const, createdAt: '2024-01-14', assignee: '李芳', updatedAt: '2024-01-14' },
  { id: 'ISS-2024-003', priority: 'P2' as const, component: '前大灯', description: 'LED 日行灯色温偏移，与设计确认中', department: '灯具', status: 'open' as const, createdAt: '2024-01-13', assignee: '王磊', updatedAt: '2024-01-13' },
  { id: 'ISS-2024-004', priority: 'P1' as const, component: '车门密封条', description: '密封条压缩负荷不满足防水要求', department: '车身钣金', status: 'resolved' as const, createdAt: '2024-01-12', assignee: '赵敏', updatedAt: '2024-01-12' },
  { id: 'ISS-2024-005', priority: 'P0' as const, component: '后尾灯', description: '尾灯密封失效，进水起雾严重', department: '灯具', status: 'open' as const, createdAt: '2024-01-11', assignee: '孙涛', updatedAt: '2024-01-11' },
  { id: 'ISS-2024-006', priority: 'P3' as const, component: '座椅骨架', description: '座椅调节异响，需加润滑脂', department: '内外饰件', status: 'closed' as const, createdAt: '2024-01-10', assignee: '周琳', updatedAt: '2024-01-10' },
  { id: 'ISS-2024-007', priority: 'P2' as const, component: '引擎盖', description: '引擎盖关闭后与翼子板面差不一致', department: '车身钣金', status: 'in_progress' as const, createdAt: '2024-01-09', assignee: '吴刚', updatedAt: '2024-01-09' },
  { id: 'ISS-2024-008', priority: 'P1' as const, component: '后视镜', description: '后视镜折叠时电机过热保护', department: '内外饰件', status: 'open' as const, createdAt: '2024-01-08', assignee: '郑辉', updatedAt: '2024-01-08' },
  { id: 'ISS-2024-009', priority: 'P2' as const, component: '雾灯', description: '雾灯安装角度与设计不符', department: '灯具', status: 'resolved' as const, createdAt: '2024-01-07', assignee: '陈静', updatedAt: '2024-01-07' },
  { id: 'ISS-2024-010', priority: 'P3' as const, component: '门板饰条', description: '门板饰条安装孔位偏移2mm', department: '车身钣金', status: 'closed' as const, createdAt: '2024-01-06', assignee: '林峰', updatedAt: '2024-01-06' },
];
const mockMilestones = [
  { id: 1, name: '车身钣金合装', percentage: 85, category: '车身钣金', targetDate: null },
  { id: 2, name: '内外饰件匹配', percentage: 62, category: '内外饰件', targetDate: null },
  { id: 3, name: '灯具点亮验证', percentage: 78, category: '灯具', targetDate: null },
  { id: 4, name: '整车密封性测试', percentage: 45, category: '综合', targetDate: null },
  { id: 5, name: 'NVH 性能评估', percentage: 30, category: '综合', targetDate: null },
];
const mockStats = {
  totalOpen: 5, newThisWeek: 5, closedThisWeek: 0, highRiskCount: 2,
  departmentStats: [
    { department: '车身钣金', closedRate: 0, totalIssues: 2 },
    { department: '内外饰件', closedRate: 0, totalIssues: 1 },
    { department: '灯具', closedRate: 0, totalIssues: 1 },
    { department: '总装', closedRate: 0, totalIssues: 0 },
  ],
  trend: Array.from({ length: 15 }, (_, i) => ({ date: '05-' + String(13 + i).padStart(2, '0'), count: 0 })),
};
const mockTools = [
  { id: 'excel-merge', name: 'Excel 批量合并', description: '合并多份交付物表格，自动去重与汇总', icon: 'FileSpreadsheet', category: '数据处理', status: 'ready' as const },
  { id: 'excel-rename', name: 'Excel 批量改名', description: '根据规则批量重命名文件，支持正则', icon: 'FileEdit', category: '数据处理', status: 'ready' as const },
  { id: 'excel-same', name: '同结构合并', description: '多个同结构 Excel 表格纵向拼接', icon: 'FileSpreadsheet', category: '数据处理', status: 'ready' as const },
  { id: 'web-crawler', name: '内网数据爬取', description: '通过浏览器自动抓取内网页面交付物数据', icon: 'Globe', category: '数据采集', status: 'ready' as const },
  { id: 'ppt-weekly', name: '周报 PPT 生成', description: '根据问题数据自动生成周报格式的 PPT', icon: 'Presentation', category: '报告生成', status: 'ready' as const },
  { id: 'ppt-deliverable', name: '交付物 PPT 生成', description: '将交付物数据转化为标准格式 PPT', icon: 'FileStack', category: '报告生成', status: 'ready' as const },
  { id: 'feishu-mail', name: '飞书邮件助手', description: '查看飞书邮件并自动生成待办任务', icon: 'Mail', category: '协作工具', status: 'ready' as const },
  { id: 'task-track', name: '任务派发追踪', description: '批量派发任务并追踪完成状态', icon: 'ListChecks', category: '任务管理', status: 'planned' as const },
  { id: 'risk-warn', name: '风险预警系统', description: '基于节点交付物自动判断风险等级', icon: 'AlertTriangle', category: '智能分析', status: 'beta' as const },
  { id: 'ai-assistant', name: 'AI 智能助手', description: '语音交互，智能问答与数据分析', icon: 'Sparkles', category: '智能分析', status: 'planned' as const },
];
const mockMails = [
  { id: 'M001', sender: '李明 - 车身工程部', subject: '【交付物】车身钣金 DV 试验报告', preview: '附件为车身钣金 DV 试验报告，请查收。', date: '今天 09:30', isRead: false, isStarred: true, hasAttachment: true, category: '交付物' },
  { id: 'M002', sender: '王芳 - 内饰部', subject: '仪表板表面缩痕问题', preview: '经过与供应商沟通，注塑温度调整后缩痕问题已明显改善。', date: '今天 08:15', isRead: false, isStarred: false, hasAttachment: true, category: '问题反馈' },
  { id: 'M003', sender: '张总 - 项目管理部', subject: '【紧急】周五造车评审会议通知', preview: '本周五下午 14:00 召开造车阶段评审会议。', date: '昨天 17:00', isRead: true, isStarred: true, hasAttachment: false, category: '会议通知' },
];
const mockTodos = [
  { id: 'T001', content: '审核车身钣金 DV 试验报告', source: '李明邮件', deadline: '今天', completed: false, createdAt: '' },
  { id: 'T002', content: '确认仪表板缩痕工艺方案', source: '王芳邮件', deadline: '今天', completed: false, createdAt: '' },
  { id: 'T003', content: '准备周五造车评审材料', source: '张总邮件', deadline: '明天', completed: false, createdAt: '' },
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
    if (data.priority) body.priority = data.priority;
    if (data.component) body.component = data.component;
    if (data.description) body.description = data.description;
    if (data.department) body.department = data.department;
    if (data.status) body.status = data.status;
    if (data.assignee !== undefined) body.assignee = data.assignee;
    const res = await api.put<import('@/services/api').IssueOut>('/issues/' + id, body);
    if (res.success && res.data) { set((s) => ({ issues: s.issues.map((i) => i.id === id ? toIssue(res.data!) : i) })); return true; }
    return false;
  },
  deleteIssue: async (id) => {
    const res = await api.del('/issues/' + id);
    if (res.success) { set((s) => ({ issues: s.issues.filter((i) => i.id !== id) })); return true; }
    return false;
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
  },
  createMilestone: async (data) => {
    const res = await api.post<import('@/services/api').MilestoneOut>('/milestones', data);
    if (res.success && res.data) { set((s) => ({ milestones: [...s.milestones, toMilestone(res.data!)] })); return true; }
    return false;
  },
  updateMilestone: async (id, data) => {
    const body: Record<string, unknown> = {};
    if (data.name) body.name = data.name;
    if (data.category) body.category = data.category;
    if (data.percentage !== undefined) body.percentage = data.percentage;
    if (data.targetDate !== undefined) body.target_date = data.targetDate;
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
    const res = await api.get('/feishu/mails?page=' + page + '&size=' + size);
    if (res.success && res.data) { set({ mails: res.data.items.map(toMail), mailTotal: res.data.total, isOnline: true }); }
  },
  syncMails: async () => {
    const res = await api.post('/feishu/sync');
    if (res.success && res.data) { await get().fetchMails(); return { synced: res.data.synced_count, fresh: res.data.new_count, demo: res.data.demo }; }
    return null;
  },
  fetchTodos: async () => {
    const res = await api.get('/feishu/todos');
    if (res.success && res.data) { set({ todos: res.data.map(toTodo), isOnline: true }); }
  },
  toggleTodo: async (id) => {
    const res = await api.post('/feishu/todo-toggle', { id });
    if (res.success && res.data) { set((s) => ({ todos: s.todos.map((t) => t.id === id ? { ...t, completed: res.data.completed } : t) })); return true; }
    return false;
  },
  deliverableCategories: [],
  fetchDeliverableCategories: async () => {
    const res = await api.get('/dashboard/deliverable-categories');
    if (res.success && res.data) { set({ deliverableCategories: res.data.map((c: DeliverableCategory) => ({ id: c.id, name: c.name, icon: c.icon, sortOrder: c.sort_order, isVisible: c.is_visible })) }); }
  },
  createDeliverableCategory: async (data) => {
    const res = await api.post('/dashboard/deliverable-categories', data);
    if (res.success) { await get().fetchDeliverableCategories(); return true; }
    return false;
  },
  dashboardOverview: null,
  fetchDashboardOverview: async () => {
    const res = await api.get('/dashboard/overview');
    if (res.success && res.data) {
      set({
        dashboardOverview: {
          totalIssues: res.data.total_issues, openIssues: res.data.open_issues,
          closedRate: res.data.closed_rate, highRiskCount: res.data.high_risk_count,
          newThisWeek: res.data.new_this_week, closedThisWeek: res.data.closed_this_week,
          milestoneProgress: res.data.milestone_progress, departmentStats: res.data.department_stats,
          trend: res.data.trend, deliverableCounts: res.data.deliverable_counts,
        },
        isOnline: true,
      });
    }
  },
  layouts: {},
  fetchLayouts: async (pageKey) => {
    const res = await api.get('/dashboard/layouts?page_key=' + pageKey);
    if (res.success && res.data) {
      set((s) => ({
        layouts: {
          ...s.layouts,
          [pageKey]: res.data.map((c: import('@/services/api').LayoutCardOut) => ({
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
}));