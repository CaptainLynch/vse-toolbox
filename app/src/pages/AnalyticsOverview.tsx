import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { DraggableGrid } from '@/components/DraggableGrid';
import { DraggableCard } from '@/components/DraggableCard';
import { MilestoneStickyCards } from '@/components/MilestoneStickyCards';
import { ProjectTimeline } from '@/components/ProjectTimeline';
import { MilestoneCardGrid } from '@/components/MilestoneCardGrid';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, Legend,
} from 'recharts';
import { TrendingUp, TrendingDown, ArrowUpRight, ClipboardList, AlertTriangle, FileText, Plus } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { defaultLayouts } from '@/config/defaultLayouts';

interface AnalyticsOverviewProps {
  onNavigate: (page: string) => void;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] px-3 py-2 shadow-lg">
        <p className="text-[#8a8f98] text-[11px] mb-1">{label}</p>
        {payload.map((entry: any, i: number) => (
          <p key={i} className="text-white text-xs font-medium" style={{ color: entry.color }}>{entry.name}: {entry.value}</p>
        ))}
      </div>
    );
  }
  return null;
};

const deliverableIcons: Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>> = {
  issues: ClipboardList, ewo: AlertTriangle, tir: FileText,
};
const deliverableColors: Record<string, string> = {
  issues: '#d4af37', ewo: '#ff9f4d', tir: '#4ade80',
};

export function AnalyticsOverview({ onNavigate }: AnalyticsOverviewProps) {
  const { dashboardOverview, fetchDashboardOverview, milestones, fetchMilestones, fetchTimelineNodes, fetchMilestoneEvaluations, layouts, saveLayouts, fetchLayouts } = useAppStore();
  const [showAddDialog, setShowAddDialog] = useState(false);

  useEffect(() => { 
    fetchDashboardOverview(); fetchMilestones(); fetchTimelineNodes(); fetchMilestoneEvaluations(); fetchLayouts('overview'); 
  }, []);

  const overview = dashboardOverview;
  const currentLayout = layouts['overview'] && layouts['overview'].length > 0 ? layouts['overview'] : (defaultLayouts['overview'] ?? []);

  const kpis = overview ? [
    { id: 'kpi-open', label: '未关闭问题总数', value: overview.openIssues, trendGood: 'down' },
    { id: 'kpi-new', label: '本周新增', value: overview.newThisWeek, trendGood: null },
    { id: 'kpi-closed', label: '本周关闭', value: overview.closedThisWeek, trendGood: 'up' },
    { id: 'kpi-risk', label: '高风险预警', value: overview.highRiskCount, trendGood: 'down' },
  ] : [];

  const trendData = overview?.trend ?? [];
  const completionPie = overview?.completionPie ?? [];
  const departmentBar = overview?.departmentBar ?? [];
  const milestoneData = milestones.length > 0
    ? milestones.map(m => ({
        name: m.name,
        percentage: m.percentage,
        actualPercentage: m.actualPercentage,
        targetDate: m.targetDate,
        actualDate: m.actualDate,
        category: m.category,
      }))
    : (overview?.milestoneProgress ?? []);
  const deliverableCounts = overview?.deliverableCounts ?? {};

  const deliverableCardsInfo = [
    { key: 'del-issues', label: '造车问题', count: deliverableCounts.issues ?? 0, type: 'issues' },
    { key: 'del-ewo', label: 'EWO/NCR', count: deliverableCounts.ewo ?? 0, type: 'ewo' },
    { key: 'del-tir', label: 'TIR', count: deliverableCounts.tir ?? 0, type: 'tir' },
  ];

  const allWidgets = [
    { id: 'kpi-open', title: 'KPI: 未关闭问题总数', type: 'kpi' },
    { id: 'kpi-new', title: 'KPI: 本周新增', type: 'kpi' },
    { id: 'kpi-closed', title: 'KPI: 本周关闭', type: 'kpi' },
    { id: 'kpi-risk', title: 'KPI: 高风险预警', type: 'kpi' },
    { id: 'del-issues', title: '交付物状态: 造车问题', type: 'deliverable' },
    { id: 'del-ewo', title: '交付物状态: EWO/NCR', type: 'deliverable' },
    { id: 'del-tir', title: '交付物状态: TIR', type: 'deliverable' },
    { id: 'trend-chart', title: '图表: 问题趋势', type: 'area' },
    { id: 'completion-pie', title: '图表: 问题完成率', type: 'pie' },
    { id: 'dept-bar', title: '图表: 各部门问题统计', type: 'bar' },
  ];

  const availableWidgets = allWidgets.filter(w => !currentLayout.some(c => c.cardId === w.id));
  const isVisible = (id: string) => currentLayout.some(c => c.cardId === id);

  const handleRemoveCard = async (cardId: string) => {
    const updated = currentLayout.filter(c => c.cardId !== cardId);
    await saveLayouts('overview', updated);
  };

  const handleAddCard = async (cardId: string, cardType: string) => {
    const newCard = { pageKey: 'overview', cardId, cardType, x: 0, y: Infinity, w: 2, h: 2 };
    if (cardType === 'kpi' || cardType === 'deliverable') { newCard.w = 1; newCard.h = 1; }
    await saveLayouts('overview', [...currentLayout, newCard]);
    setShowAddDialog(false);
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-2">项目数据总览</h1>
          <p className="text-[13px] text-[#8a8f98]">多维度展示项目健康度、资源负荷、问题趋势等关键指标</p>
        </div>
        <button onClick={() => setShowAddDialog(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#d4af37] text-black font-semibold rounded-[4px] hover:brightness-110 transition-all shadow-lg hover:shadow-[0_0_12px_rgba(212,175,55,0.3)]">
          <Plus className="w-4 h-4" />
          添加分析组件
        </button>
      </div>

      <MilestoneStickyCards milestones={milestoneData} />
      <ProjectTimeline />
      <MilestoneCardGrid />

      {currentLayout.length === 0 ? (
        <div className="bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] p-12 text-center flex flex-col items-center justify-center mt-6">
          <p className="text-[#8a8f98] text-sm">暂无展示的组件（含交付物状态）</p>
          <p className="text-[#5a5f68] text-xs mt-1 mb-4">初始状态为空白，请点击上方按钮逐个添加各个交付物状态或图表</p>
          <button onClick={() => setShowAddDialog(true)} className="flex items-center gap-1.5 px-4 py-2 text-xs bg-[#d4af37] text-black font-semibold rounded-[4px] hover:brightness-110 transition-all hover:shadow-[0_0_12px_rgba(212,175,55,0.15)]">
            <Plus className="w-3.5 h-3.5" />
            添加组件
          </button>
        </div>
      ) : (
        <DraggableGrid pageKey="overview" cols={4} rowHeight={120}>
          {kpis.map((kpi) => isVisible(kpi.id) && (
            <DraggableCard key={kpi.id} id={kpi.id} title={kpi.label} onRemove={() => handleRemoveCard(kpi.id)}>
              <div className="flex flex-col justify-between h-full py-2 px-4">
                <span className="text-3xl font-bold text-white font-tabular">{kpi.value}</span>
                <div className="flex items-center gap-1 mt-auto">
                  {kpi.trendGood === 'up' && <TrendingUp className="w-3 h-3 text-green-400" />}
                  {kpi.trendGood === 'down' && <TrendingDown className="w-3 h-3 text-green-400" />}
                  <span className="text-xs text-[#8a8f98]">实时数据</span>
                </div>
              </div>
            </DraggableCard>
          ))}

          {deliverableCardsInfo.map((card) => {
            if (!isVisible(card.key)) return null;
            const Icon = deliverableIcons[card.type];
            return (
              <DraggableCard key={card.key} id={card.key} title={`交付物: ${card.label}`} onRemove={() => handleRemoveCard(card.key)}>
                <button onClick={() => onNavigate(card.type)} className="w-full h-full group bg-[#0f0f11] flex flex-col items-center justify-center gap-2 hover:bg-[#1a1a1e] transition-all relative overflow-hidden">
                  <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <ArrowUpRight className="w-3.5 h-3.5 text-[#d4af37]" />
                  </div>
                  <Icon className="w-7 h-7" style={{ color: deliverableColors[card.type] }} />
                  <span className="text-white text-sm font-semibold">{card.label}</span>
                  <span className="text-2xl font-bold font-tabular" style={{ color: deliverableColors[card.type] }}>{card.count}</span>
                </button>
              </DraggableCard>
            );
          })}

          {isVisible('trend-chart') && (
            <DraggableCard key="trend-chart" id="trend-chart" title="问题趋势" onRemove={() => handleRemoveCard('trend-chart')}>
              <div className="h-full py-2 px-2 no-drag">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trendData} margin={{ top: 10, right: 10 }}>
                    <defs>
                      <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#d4af37" stopOpacity={0.2} />
                        <stop offset="100%" stopColor="#d4af37" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e1e20" vertical={false} />
                    <XAxis dataKey="date" tick={{ fill: '#8a8f98', fontSize: 11 }} axisLine={{ stroke: '#2a2a2e' }} tickLine={false} />
                    <YAxis tick={{ fill: '#8a8f98', fontSize: 11 }} axisLine={{ stroke: '#2a2a2e' }} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Area type="monotone" dataKey="count" name="新增问题" stroke="#d4af37" strokeWidth={2} fill="url(#trendGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </DraggableCard>
          )}

          {isVisible('completion-pie') && (
            <DraggableCard key="completion-pie" id="completion-pie" title="问题完成率" onRemove={() => handleRemoveCard('completion-pie')}>
              <div className="h-full py-2 flex items-center justify-center no-drag">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={completionPie} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value">
                      {completionPie.map((entry, index) => <Cell key={`cell-${index}`} fill={entry.color} />)}
                    </Pie>
                    <Tooltip content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const d = payload[0].payload;
                        return (
                          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] px-3 py-2 shadow-lg">
                            <p className="text-white text-xs font-medium">{d.name}: {d.value}</p>
                          </div>
                        );
                      }
                      return null;
                    }} />
                    <Legend verticalAlign="bottom" formatter={(value: string) => <span className="text-xs text-[#8a8f98]">{value}</span>} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </DraggableCard>
          )}

          {isVisible('dept-bar') && (
            <DraggableCard key="dept-bar" id="dept-bar" title="各部门问题统计" onRemove={() => handleRemoveCard('dept-bar')}>
              <div className="h-full py-2 px-2 no-drag">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={departmentBar} margin={{ top: 10, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e1e20" vertical={false} />
                    <XAxis dataKey="department" tick={{ fill: '#8a8f98', fontSize: 10 }} axisLine={{ stroke: '#2a2a2e' }} tickLine={false} />
                    <YAxis tick={{ fill: '#8a8f98', fontSize: 11 }} axisLine={{ stroke: '#2a2a2e' }} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="total" name="总问题" fill="#8a8f98" radius={[2, 2, 0, 0]} />
                    <Bar dataKey="closed" name="已关闭" fill="#4ade80" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </DraggableCard>
          )}
        </DraggableGrid>
      )}

      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white">添加分析组件 / 交付物状态</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 mt-4 max-h-[300px] overflow-y-auto pr-1">
            {availableWidgets.length === 0 ? (
              <p className="text-xs text-[#8a8f98] text-center py-4">所有组件已添加</p>
            ) : (
              availableWidgets.map((w) => (
                <div key={w.id} className="flex items-center justify-between p-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] hover:border-[#d4af37] transition-all">
                  <div className="text-sm text-white font-medium">{w.title}</div>
                  <button onClick={() => handleAddCard(w.id, w.type)} className="h-7 px-3 bg-[#d4af37] hover:brightness-110 text-black text-xs font-semibold rounded-[4px] transition-all flex items-center gap-1">
                    <Plus className="w-3.5 h-3.5" />
                    添加
                  </button>
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
