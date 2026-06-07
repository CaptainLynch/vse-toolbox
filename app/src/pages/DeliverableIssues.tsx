import { useState, useEffect, useCallback, useRef } from 'react';
import { useAppStore } from '@/stores/appStore';
import { cn } from '@/lib/utils';
import { api } from '@/services/api';
import type { ExcelImportResult, PartSystemOut, EngineerOut } from '@/services/api';
import {
  Plus,
  Download,
  Upload,
  Eye,
  Trash2,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

interface CreateIssuePayload {
  priority: string;
  component: string;
  description: string;
  department: string;
  assignee: string;
  part_system: string;
  sub_system: string;
  root_cause: string;
  short_term_action: string;
  long_term_action: string;
  cutoff_point: string;
  action_plan: string;
}

const priorityConfig = {
  P0: { bg: '#3b1515', text: '#ff4d4d', label: '紧急' },
  P1: { bg: '#3b2015', text: '#ff9f4d', label: '高' },
  P2: { bg: '#3b3015', text: '#d4af37', label: '中' },
  P3: { bg: '#222225', text: '#8a8f98', label: '低' },
};

const statusConfig = {
  open: { dot: '#ff4d4d', label: '待处理' },
  in_progress: { dot: '#d4af37', label: '处理中' },
  resolved: { dot: '#4ade80', label: '已解决' },
  closed: { dot: '#8a8f98', label: '已关闭' },
};

// ---------------------------------------------------------------------------
// Auto-suggest hook for lookup
// ---------------------------------------------------------------------------

function useLookup<T>(endpoint: string) {
  const [results, setResults] = useState<T[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => { clearTimeout(timerRef.current); };
  }, []);

  const search = useCallback((q: string) => {
    clearTimeout(timerRef.current);
    if (!q.trim()) { setResults([]); return; }
    timerRef.current = setTimeout(async () => {
      const res = await api.get<T[]>(`${endpoint}?q=${encodeURIComponent(q)}`);
      if (res.success && res.data) setResults(res.data);
    }, 300);
  }, [endpoint]);

  const clear = useCallback(() => {
    clearTimeout(timerRef.current);
    setResults([]);
  }, []);

  return { results, search, clear };
}

// ---------------------------------------------------------------------------
// Create Issue Dialog
// ---------------------------------------------------------------------------

function CreateIssueDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: CreateIssuePayload) => Promise<boolean>;
}) {
  const [form, setForm] = useState({
    priority: 'P1',
    component: '',
    description: '',
    department: '',
    assignee: '',
    part_system: '',
    sub_system: '',
    root_cause: '',
    short_term_action: '',
    long_term_action: '',
    cutoff_point: '',
    action_plan: '',
  });

  const partSystemLookup = useLookup<PartSystemOut>('/lookup/part-system');
  const engineerLookup = useLookup<EngineerOut>('/lookup/engineer');

  const handlePartSystemChange = (value: string) => {
    setForm({ ...form, part_system: value });
    partSystemLookup.search(value);
  };

  const selectPartSystem = (item: PartSystemOut) => {
    setForm({ ...form, part_system: item.part_system, sub_system: item.sub_system });
    partSystemLookup.clear();
  };

  const handleAssigneeChange = (value: string) => {
    setForm({ ...form, assignee: value });
    engineerLookup.search(value);
  };

  const selectEngineer = (item: EngineerOut) => {
    setForm({ ...form, assignee: item.name, department: item.department });
    engineerLookup.clear();
  };

  const handleSubmit = async () => {
    if (!form.component.trim() || !form.description.trim() || !form.department.trim()) {
      toast.error('请填写所有必填字段');
      return;
    }
    const ok = await onSubmit(form);
    if (ok) {
      setForm({
        priority: 'P1', component: '', description: '', department: '', assignee: '',
        part_system: '', sub_system: '', root_cause: '', short_term_action: '',
        long_term_action: '', cutoff_point: '', action_plan: '',
      });
      onClose();
      toast.success('问题创建成功');
    } else {
      toast.error('创建失败，请检查后端连接');
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-2xl max-h-[85vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="text-white">新建问题单</DialogTitle>
          <DialogDescription className="text-[#8a8f98]">
            填写问题基本信息，支持零件总成和工程师自动关联
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-4">
          {/* Row 1: Priority + Component */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">优先级 *</label>
              <select
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
                className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white focus:outline-none focus:border-[#d4af37]"
              >
                <option value="P0">P0 - 紧急</option>
                <option value="P1">P1 - 高</option>
                <option value="P2">P2 - 中</option>
                <option value="P3">P3 - 低</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">零部件/系统 *</label>
              <input
                value={form.component}
                onChange={(e) => setForm({ ...form, component: e.target.value })}
                placeholder="例如：前保险杠"
                className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
              />
            </div>
          </div>

          {/* Part System with auto-suggest */}
          <div className="relative">
            <label className="text-xs text-[#8a8f98] mb-1 block">零件总成</label>
            <input
              value={form.part_system}
              onChange={(e) => handlePartSystemChange(e.target.value)}
              onBlur={() => setTimeout(() => partSystemLookup.clear(), 200)}
              placeholder="输入零件总成名称，自动匹配子系统"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
            {partSystemLookup.results.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-[#141416] border border-[#2a2a2e] rounded-[4px] shadow-lg max-h-40 overflow-auto">
                {partSystemLookup.results.map((item, i) => (
                  <button
                    key={i}
                    onMouseDown={() => selectPartSystem(item)}
                    className="w-full px-3 py-2 text-left text-xs text-white hover:bg-[#1c1c1e] flex items-center justify-between"
                  >
                    <span>{item.part_system}</span>
                    <span className="text-[#8a8f98]">→ {item.sub_system}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Sub System (auto-filled) */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">子系统</label>
            <input
              value={form.sub_system}
              onChange={(e) => setForm({ ...form, sub_system: e.target.value })}
              placeholder="选择零件总成后自动填充"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">问题描述 *</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              placeholder="描述问题现象..."
              className="w-full px-3 py-2 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37] resize-none"
            />
          </div>

          {/* Assignee with auto-suggest (engineer→department) */}
          <div className="relative">
            <label className="text-xs text-[#8a8f98] mb-1 block">负责人</label>
            <input
              value={form.assignee}
              onChange={(e) => handleAssigneeChange(e.target.value)}
              onBlur={() => setTimeout(() => engineerLookup.clear(), 200)}
              placeholder="输入工程师姓名，自动关联科室"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
            {engineerLookup.results.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-[#141416] border border-[#2a2a2e] rounded-[4px] shadow-lg max-h-40 overflow-auto">
                {engineerLookup.results.map((item, i) => (
                  <button
                    key={i}
                    onMouseDown={() => selectEngineer(item)}
                    className="w-full px-3 py-2 text-left text-xs text-white hover:bg-[#1c1c1e] flex items-center justify-between"
                  >
                    <span>{item.name}</span>
                    <span className="text-[#8a8f98]">→ {item.department}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Department (auto-filled from engineer) */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">责任部门 *</label>
            <input
              value={form.department}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
              placeholder="选择负责人后自动填充"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>

          {/* Root Cause */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">根本原因</label>
            <textarea
              value={form.root_cause}
              onChange={(e) => setForm({ ...form, root_cause: e.target.value })}
              rows={2}
              placeholder="分析问题的根本原因"
              className="w-full px-3 py-2 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37] resize-none"
            />
          </div>

          {/* Actions row */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">短期措施</label>
              <input
                value={form.short_term_action}
                onChange={(e) => setForm({ ...form, short_term_action: e.target.value })}
                placeholder="短期对策"
                className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
              />
            </div>
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">长期措施</label>
              <input
                value={form.long_term_action}
                onChange={(e) => setForm({ ...form, long_term_action: e.target.value })}
                placeholder="长期对策"
                className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">截止节点</label>
              <input
                value={form.cutoff_point}
                onChange={(e) => setForm({ ...form, cutoff_point: e.target.value })}
                placeholder="例如：ET 阶段"
                className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
              />
            </div>
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">行动计划</label>
              <input
                value={form.action_plan}
                onChange={(e) => setForm({ ...form, action_plan: e.target.value })}
                placeholder="行动方案概述"
                className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
              />
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              onClick={onClose}
              className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 transition-all"
            >
              提交
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function DeliverableIssues() {
  const {
    issues, issueTotal, issuePage, setIssuePage,
    fetchIssues, createIssue, deleteIssue,
    stats, fetchStats,
    importIssuesExcel,
  } = useAppStore();

  const [showCreate, setShowCreate] = useState(false);
  const [filterPriority, setFilterPriority] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ExcelImportResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const totalPages = Math.max(1, Math.ceil(issueTotal / PAGE_SIZE));

  // Clear selection on page change
  useEffect(() => { setSelectedRows(new Set()); }, [issuePage]);

  // Refetch when filters change
  const refetch = useCallback(() => {
    fetchIssues({
      page: issuePage,
      size: PAGE_SIZE,
      priority: filterPriority || undefined,
      status: filterStatus || undefined,
    });
  }, [issuePage, filterPriority, filterStatus]);

  useEffect(() => { refetch(); }, [refetch]);
  useEffect(() => { fetchStats(); }, []);

  // KPI cards
  const kpis = stats ? [
    { label: '未关闭问题总数', value: stats.totalOpen },
    { label: '本周新增', value: stats.newThisWeek },
    { label: '本周关闭', value: stats.closedThisWeek },
    { label: '高风险预警', value: stats.highRiskCount },
  ] : [];

  const handleCreate = async (data: CreateIssuePayload) => {
    const ok = await createIssue(data);
    if (ok) {
      fetchIssues({ page: 1, size: PAGE_SIZE });
      fetchStats();
    }
    return ok;
  };

  const handleDelete = async (id: string) => {
    const ok = await deleteIssue(id);
    if (ok) {
      toast.success('已删除');
      fetchIssues({ page: issuePage, size: PAGE_SIZE });
      fetchStats();
    } else {
      toast.error('删除失败');
    }
  };

  const handleExportWeekly = async () => {
    const res = await api.post<{ file_path: string; file_name: string }>('/ppt/weekly');
    if (res.success && res.data) {
      api.download(res.data.file_path);
      toast.success(`已生成 ${res.data.file_name}`);
    } else {
      toast.error(res.message || '导出失败');
    }
  };

  const handleImportExcel = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    const result = await importIssuesExcel(file);
    setImporting(false);
    if (result) {
      setImportResult(result);
      toast.success(`导入完成：新增 ${result.created}，更新 ${result.updated}`);
      if (result.errors.length > 0) {
        toast.warning(`${result.errors.length} 条记录导入失败`);
      }
    } else {
      toast.error('导入失败，请检查文件格式');
    }
    // Reset file input
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // Selection
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());
  const toggleRow = (id: string) => {
    const next = new Set(selectedRows);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelectedRows(next);
  };
  const toggleAll = () => {
    setSelectedRows(
      selectedRows.size === issues.length ? new Set() : new Set(issues.map((i) => i.id))
    );
  };

  return (
    <div className="h-[calc(100vh-56px)]">
      {/* Main content */}
      <div className="overflow-auto p-6">
        {/* KPI Cards */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {kpis.map((kpi, i) => {
            const isRisk = kpi.label.includes('风险');
            return (
              <div
                key={i}
                className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5 h-[120px] flex flex-col justify-between"
              >
                <span className="text-[11px] font-medium tracking-[0.5px] uppercase text-[#8a8f98]">
                  {kpi.label}
                </span>
                <span className="text-3xl font-bold text-white font-tabular">{kpi.value}</span>
                <div className="flex items-center gap-1">
                  {isRisk ? (
                    <TrendingDown className="w-3 h-3 text-red-400" />
                  ) : kpi.label.includes('关闭') ? (
                    <TrendingUp className="w-3 h-3 text-green-400" />
                  ) : null}
                  <span className="text-xs text-[#8a8f98]">实时数据</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowCreate(true)}
              className="h-9 px-4 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 transition-all flex items-center gap-2 hover:shadow-[0_0_12px_rgba(212,175,55,0.15)]"
            >
              <Plus className="w-4 h-4" />
              新建问题单
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls"
              onChange={handleImportExcel}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importing}
              className="h-9 px-4 bg-transparent border border-[#2a2a2e] text-white text-sm rounded-[4px] hover:border-[#8a8f98] hover:bg-[#1c1c1e] transition-all flex items-center gap-2 disabled:opacity-50"
            >
              <Upload className="w-4 h-4 text-[#8a8f98]" />
              {importing ? '导入中...' : '导入 Excel'}
            </button>
            <button
              onClick={handleExportWeekly}
              className="h-9 px-4 bg-transparent border border-[#2a2a2e] text-white text-sm rounded-[4px] hover:border-[#8a8f98] hover:bg-[#1c1c1e] transition-all flex items-center gap-2"
            >
              <Download className="w-4 h-4 text-[#8a8f98]" />
              导出周报
            </button>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={filterPriority}
              onChange={(e) => { setFilterPriority(e.target.value); setIssuePage(1); }}
              className="h-7 px-2 bg-[#141416] border border-[#2a2a2e] rounded-[4px] text-xs text-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            >
              <option value="">全部优先级</option>
              <option value="P0">P0 紧急</option>
              <option value="P1">P1 高</option>
              <option value="P2">P2 中</option>
              <option value="P3">P3 低</option>
            </select>
            <select
              value={filterStatus}
              onChange={(e) => { setFilterStatus(e.target.value); setIssuePage(1); }}
              className="h-7 px-2 bg-[#141416] border border-[#2a2a2e] rounded-[4px] text-xs text-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            >
              <option value="">全部状态</option>
              <option value="open">待处理</option>
              <option value="in_progress">处理中</option>
              <option value="resolved">已解决</option>
              <option value="closed">已关闭</option>
            </select>
            <span className="text-xs text-[#8a8f98]">
              共 {issueTotal} 条记录
            </span>
          </div>
        </div>

        {/* Import Result Banner */}
        {importResult && (
          <div className="mb-4 p-3 bg-[#3b3015] border border-[#d4af37]/30 rounded-[4px] flex items-center gap-3">
            <CheckCircle2 className="w-4 h-4 text-[#d4af37] flex-shrink-0" />
            <div className="flex-1 text-xs text-[#d4af37]">
              导入完成：新增 <strong>{importResult.created}</strong> 条，更新 <strong>{importResult.updated}</strong> 条
              {importResult.errors.length > 0 && (
                <span className="ml-2 text-[#ff9f4d]">
                  （{importResult.errors.length} 条失败）
                </span>
              )}
            </div>
            <button onClick={() => setImportResult(null)} className="text-[#8a8f98] hover:text-white text-xs">关闭</button>
          </div>
        )}

        {/* Data Table - 10 columns */}
        <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] overflow-hidden">
          <div className="grid grid-cols-[40px_90px_60px_120px_100px_1fr_100px_80px_80px_70px] gap-0 bg-[#0f0f11] border-b border-[#2a2a2e]">
            <div className="px-2 py-3 flex items-center">
              <input
                type="checkbox"
                checked={selectedRows.size === issues.length && issues.length > 0}
                onChange={toggleAll}
                className="w-3.5 h-3.5 rounded border-[#2a2a2e] bg-transparent accent-[#d4af37]"
              />
            </div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">编号</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">优先级</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">零部件</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">零件总成</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">问题描述</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">责任部门</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">状态</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">负责人</div>
            <div className="px-2 py-3 text-xs text-[#8a8f98] font-medium">操作</div>
          </div>

          {issues.map((issue) => (
            <div
              key={issue.id}
              className={cn(
                'grid grid-cols-[40px_90px_60px_120px_100px_1fr_100px_80px_80px_70px] gap-0 border-b border-[#1e1e20] hover:bg-[#161618] transition-colors',
                selectedRows.has(issue.id) && 'bg-[#161618]'
              )}
            >
              <div className="px-2 py-3 flex items-center">
                <input
                  type="checkbox"
                  checked={selectedRows.has(issue.id)}
                  onChange={() => toggleRow(issue.id)}
                  className="w-3.5 h-3.5 rounded border-[#2a2a2e] bg-transparent accent-[#d4af37]"
                />
              </div>
              <div className="px-2 py-3 text-xs text-[#8a8f98] font-tabular flex items-center truncate">
                {issue.id}
              </div>
              <div className="px-2 py-3 flex items-center">
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded-[4px] text-[10px] font-semibold"
                  style={{
                    backgroundColor: priorityConfig[issue.priority].bg,
                    color: priorityConfig[issue.priority].text,
                  }}
                >
                  {issue.priority}
                </span>
              </div>
              <div className="px-2 py-3 text-xs text-white flex items-center truncate" title={issue.component}>
                {issue.component}
              </div>
              <div className="px-2 py-3 text-xs text-[#8a8f98] flex items-center truncate" title={issue.partSystem ?? ''}>
                {issue.partSystem ?? '—'}
              </div>
              <div className="px-2 py-3 text-xs text-white flex items-center truncate" title={issue.description}>
                <span className="truncate">{issue.description}</span>
              </div>
              <div className="px-2 py-3 text-xs text-[#8a8f98] flex items-center">
                {issue.department}
              </div>
              <div className="px-2 py-3 flex items-center gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: statusConfig[issue.status].dot }}
                />
                <span className="text-[10px] text-[#8a8f98]">{statusConfig[issue.status].label}</span>
              </div>
              <div className="px-2 py-3 text-xs text-[#8a8f98] flex items-center truncate">
                {issue.assignee ?? '—'}
              </div>
              <div className="px-2 py-3 flex items-center gap-1">
                <button className="p-1 text-[#8a8f98] hover:text-white transition-colors">
                  <Eye className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handleDelete(issue.id)}
                  className="p-1 text-[#8a8f98] hover:text-red-400 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}

          {issues.length === 0 && (
            <div className="p-12 text-center text-[#8a8f98] text-sm">
              暂无数据
            </div>
          )}
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-end gap-3 mt-4">
          <div className="flex items-center gap-1">
            <button
              onClick={() => { setIssuePage(Math.max(1, issuePage - 1)); }}
              disabled={issuePage === 1}
              className="p-1.5 text-[#8a8f98] hover:text-white disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
              <button
                key={page}
                onClick={() => setIssuePage(page)}
                className={cn(
                  'w-7 h-7 rounded-[4px] text-xs font-medium transition-colors',
                  page === issuePage
                    ? 'bg-[#d4af37] text-[#0a0a0c]'
                    : 'text-[#8a8f98] hover:text-white hover:bg-[#1c1c1e]'
                )}
              >
                {page}
              </button>
            ))}
            <button
              onClick={() => { setIssuePage(Math.min(totalPages, issuePage + 1)); }}
              disabled={issuePage === totalPages}
              className="p-1.5 text-[#8a8f98] hover:text-white disabled:opacity-30 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Create Issue Dialog */}
      <CreateIssueDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onSubmit={handleCreate}
      />
    </div>
  );
}
