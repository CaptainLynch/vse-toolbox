import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/stores/appStore';
import { cn } from '@/lib/utils';
import { api } from '@/services/api';
import {
  Plus,
  Download,
  MoreHorizontal,
  Eye,
  Pencil,
  Trash2,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
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
// 常量
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

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
// 创建问题对话框
// ---------------------------------------------------------------------------

function CreateIssueDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: {
    priority: string;
    component: string;
    description: string;
    department: string;
    assignee: string;
  }) => Promise<boolean>;
}) {
  const [form, setForm] = useState({
    priority: 'P1',
    component: '',
    description: '',
    department: '',
    assignee: '',
  });

  const handleSubmit = async () => {
    if (!form.component.trim() || !form.description.trim() || !form.department.trim()) {
      toast.error('请填写所有必填字段');
      return;
    }
    const ok = await onSubmit(form);
    if (ok) {
      setForm({ priority: 'P1', component: '', description: '', department: '', assignee: '' });
      onClose();
      toast.success('问题创建成功');
    } else {
      toast.error('创建失败，请检查后端连接');
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-white">新建问题单</DialogTitle>
          <DialogDescription className="text-[#8a8f98]">
            填写问题基本信息，提交后自动分配编号
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-4">
          {/* Priority */}
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
          {/* Component */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">零部件/系统 *</label>
            <input
              value={form.component}
              onChange={(e) => setForm({ ...form, component: e.target.value })}
              placeholder="例如：前保险杠"
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
          {/* Department */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">责任部门 *</label>
            <input
              value={form.department}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
              placeholder="例如：车身钣金"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>
          {/* Assignee */}
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">负责人</label>
            <input
              value={form.assignee}
              onChange={(e) => setForm({ ...form, assignee: e.target.value })}
              placeholder="选填"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
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
// 主组件
// ---------------------------------------------------------------------------

export function DeliverableIssues() {
  const {
    issues, issueTotal, issuePage, setIssuePage,
    fetchIssues, createIssue, deleteIssue,
    stats, fetchStats,
    milestones, fetchMilestones,
  } = useAppStore();

  const [showCreate, setShowCreate] = useState(false);
  const [filterPriority, setFilterPriority] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  const totalPages = Math.max(1, Math.ceil(issueTotal / PAGE_SIZE));

  // 筛选变化时重新拉取
  const refetch = useCallback(() => {
    fetchIssues({
      page: issuePage,
      size: PAGE_SIZE,
      priority: filterPriority || undefined,
      status: filterStatus || undefined,
    });
  }, [issuePage, filterPriority, filterStatus]);

  useEffect(() => { refetch(); }, [refetch]);

  // 加载 stats 和 milestones（非筛选依赖）
  useEffect(() => {
    fetchStats();
    fetchMilestones();
  }, []);

  // KPI 卡片数据（从 stats 计算）
  const kpis = stats ? [
    { label: '未关闭问题总数', value: stats.totalOpen },
    { label: '本周新增', value: stats.newThisWeek },
    { label: '本周关闭', value: stats.closedThisWeek },
    { label: '高风险预警', value: stats.highRiskCount },
  ] : [];

  const handleCreate = async (data: { priority: string; component: string; description: string; department: string; assignee: string }) => {
    const ok = await createIssue({ ...data, assignee: data.assignee || undefined });
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

  // 选中行
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
    <div className="flex h-[calc(100vh-56px)]">
      {/* Main content */}
      <div className="flex-1 overflow-auto p-6">
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
            <button
              onClick={handleExportWeekly}
              className="h-9 px-4 bg-transparent border border-[#2a2a2e] text-white text-sm rounded-[4px] hover:border-[#8a8f98] hover:bg-[#1c1c1e] transition-all flex items-center gap-2"
            >
              <Download className="w-4 h-4 text-[#8a8f98]" />
              导出周报
            </button>
            <button className="h-9 px-4 bg-transparent border border-[#2a2a2e] text-white text-sm rounded-[4px] hover:border-[#8a8f98] hover:bg-[#1c1c1e] transition-all flex items-center gap-2">
              <MoreHorizontal className="w-4 h-4 text-[#8a8f98]" />
              批量操作
            </button>
          </div>
          <div className="flex items-center gap-3">
            {/* Filters */}
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

        {/* Data Table */}
        <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] overflow-hidden">
          <div className="grid grid-cols-[40px_100px_80px_1fr_100px_90px_100px_100px] gap-0 bg-[#0f0f11] border-b border-[#2a2a2e]">
            <div className="px-3 py-3 flex items-center">
              <input
                type="checkbox"
                checked={selectedRows.size === issues.length && issues.length > 0}
                onChange={toggleAll}
                className="w-3.5 h-3.5 rounded border-[#2a2a2e] bg-transparent accent-[#d4af37]"
              />
            </div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">编号</div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">优先级</div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">问题描述</div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">责任部门</div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">状态</div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">提出日期</div>
            <div className="px-3 py-3 text-xs text-[#8a8f98] font-medium">操作</div>
          </div>

          {issues.map((issue) => (
            <div
              key={issue.id}
              className={cn(
                'grid grid-cols-[40px_100px_80px_1fr_100px_90px_100px_100px] gap-0 border-b border-[#1e1e20] hover:bg-[#161618] transition-colors',
                selectedRows.has(issue.id) && 'bg-[#161618]'
              )}
            >
              <div className="px-3 py-3 flex items-center">
                <input
                  type="checkbox"
                  checked={selectedRows.has(issue.id)}
                  onChange={() => toggleRow(issue.id)}
                  className="w-3.5 h-3.5 rounded border-[#2a2a2e] bg-transparent accent-[#d4af37]"
                />
              </div>
              <div className="px-3 py-3 text-xs text-[#8a8f98] font-tabular flex items-center truncate">
                {issue.id}
              </div>
              <div className="px-3 py-3 flex items-center">
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-[4px] text-[11px] font-semibold"
                  style={{
                    backgroundColor: priorityConfig[issue.priority].bg,
                    color: priorityConfig[issue.priority].text,
                  }}
                >
                  {issue.priority}
                </span>
              </div>
              <div className="px-3 py-3 text-xs text-white flex items-center truncate" title={issue.description}>
                <span className="truncate">{issue.description}</span>
              </div>
              <div className="px-3 py-3 text-xs text-[#8a8f98] flex items-center">
                {issue.department}
              </div>
              <div className="px-3 py-3 flex items-center gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: statusConfig[issue.status].dot }}
                />
                <span className="text-xs text-[#8a8f98]">{statusConfig[issue.status].label}</span>
              </div>
              <div className="px-3 py-3 text-xs text-[#8a8f98] font-tabular flex items-center">
                {issue.createdAt}
              </div>
              <div className="px-3 py-3 flex items-center gap-2">
                <button className="p-1 text-[#8a8f98] hover:text-white transition-colors">
                  <Eye className="w-3.5 h-3.5" />
                </button>
                <button className="p-1 text-[#8a8f98] hover:text-white transition-colors">
                  <Pencil className="w-3.5 h-3.5" />
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

      {/* Right Progress Panel */}
      <aside className="w-[320px] border-l border-[#2a2a2e] bg-[#141416] p-6 overflow-auto">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-1 h-4 bg-[#d4af37] rounded-full" />
          <h2 className="text-white text-base font-semibold">项目里程碑</h2>
        </div>

        <div className="space-y-4">
          {milestones.map((milestone) => (
            <div
              key={milestone.id}
              className="group p-4 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] hover:bg-[#161618] hover:border-[#3a3a3e] transition-all duration-200"
            >
              <div className="flex items-center justify-between mb-3">
                <div>
                  <div className="text-white text-sm font-medium">{milestone.name}</div>
                  <div className="text-[#8a8f98] text-[11px] mt-0.5">{milestone.category}</div>
                </div>
                <span className="text-[#d4af37] text-lg font-bold font-tabular">
                  {milestone.percentage}%
                </span>
              </div>
              <div className="w-full h-1 bg-[#2a2a2e] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#d4af37] rounded-full transition-all duration-500"
                  style={{ width: `${milestone.percentage}%` }}
                />
              </div>
              <button className="mt-3 text-[11px] text-[#8a8f98] hover:text-[#d4af37] transition-colors opacity-0 group-hover:opacity-100 flex items-center gap-1">
                查看详情
                <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>

        {/* Quick Stats */}
        {stats && stats.departmentStats.length > 0 && (
          <div className="mt-6 pt-6 border-t border-[#2a2a2e]">
            <h3 className="text-[#8a8f98] text-[11px] font-medium tracking-[0.5px] uppercase mb-4">
              各部门问题数
            </h3>
            <div className="space-y-3">
              {stats.departmentStats.map((ds) => (
                <div key={ds.department} className="flex items-center gap-3">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-[#8a8f98]">{ds.department}</span>
                      <span className="text-xs text-white font-tabular">{ds.totalIssues}</span>
                    </div>
                    <div className="w-full h-1 bg-[#2a2a2e] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[#8a8f98] rounded-full"
                        style={{ width: `${Math.min(100, (ds.totalIssues / Math.max(1, issueTotal)) * 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>

      {/* Create Issue Dialog */}
      <CreateIssueDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onSubmit={handleCreate}
      />
    </div>
  );
}
