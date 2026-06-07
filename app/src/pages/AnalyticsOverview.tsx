import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { DraggableGrid } from '@/components/DraggableGrid';
import { DraggableCard } from '@/components/DraggableCard';
import { MilestoneStickyCards } from '@/components/MilestoneStickyCards';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, Legend,
} from 'recharts';
import { TrendingUp, TrendingDown, ArrowUpRight, ClipboardList, AlertTriangle, FileText } from 'lucide-react';

interface AnalyticsOverviewProps {
  onNavigate: (page: string) => void;
}

// Extracted tooltip to avoid re-mount on every render
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
  const { dashboardOverview, fetchDashboardOverview, milestones, fetchMilestones } = useAppStore();

  useEffect(() => { fetchDashboardOverview(); fetchMilestones(); }, []);

  const overview = dashboardOverview;

  const kpis = overview ? [
    { label: '未关闭问题总数', value: overview.openIssues, trendGood: 'down' },
    { label: '本周新增', value: overview.newThisWeek, trendGood: null },
    { label: '本周关闭', value: overview.closedThisWeek, trendGood: 'up' },
    { label: '高风险预警', value: overview.highRiskCount, trendGood: 'down' },
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

  const deliverableCards = [
    { key: 'issues', label: '造车问题', count: deliverableCounts.issues ?? 0 },
    { key: 'ewo', label: 'EWO/NCR', count: deliverableCounts.ewo ?? 0 },
    { key: 'tir', label: 'TIR', count: deliverableCounts.tir ?? 0 },
  ];

  const kpiKeys = ['kpi-open', 'kpi-new', 'kpi-closed', 'kpi-risk'];

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white mb-2">项目数据总览</h1>
        <p className="text-[13px] text-[#8a8f98]">多维度展示项目健康度、资源负荷、问题趋势等关键指标</p>
      </div>

      {/* Milestone sticky cards — pinned at top while scrolling */}
      <MilestoneStickyCards milestones={milestoneData} />

      <DraggableGrid pageKey="overview" cols={4} rowHeight={120}>
        {/* KPI Cards */}
        {kpis.map((kpi, i) => (
          <DraggableCard key={kpiKeys[i]} id={kpiKeys[i]} title={kpi.label}>
            <div className="flex flex-col justify-between h-full py-2">
              <span className="text-3xl font-bold text-white font-tabular">{kpi.value}</span>
              <div className="flex items-center gap-1">
                {kpi.trendGood === 'up' && <TrendingUp className="w-3 h-3 text-green-400" />}
                {kpi.trendGood === 'down' && <TrendingDown className="w-3 h-3 text-green-400" />}
                <span className="text-xs text-[#8a8f98]">实时数据</span>
              </div>
            </div>
          </DraggableCard>
        ))}

        {/* Deliverable Navigation */}
        <DraggableCard key="deliverable-nav" id="deliverable-nav" title="交付物导航">
          <div className="grid grid-cols-3 gap-3 h-full py-2">
            {deliverableCards.map((card) => {
              const Icon = deliverableIcons[card.key];
              return (
                <button key={card.key} onClick={() => onNavigate(card.key)}
                  className="group bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] p-4 flex flex-col items-center justify-center gap-2 hover:border-[#d4af37] transition-all">
                  <Icon className="w-6 h-6" style={{ color: deliverableColors[card.key] }} />
                  <span className="text-white text-sm font-semibold">{card.label}</span>
                  <span className="text-lg font-bold font-tabular" style={{ color: deliverableColors[card.key] }}>{card.count}</span>
                  <ArrowUpRight className="w-3 h-3 text-[#8a8f98] group-hover:text-[#d4af37]" />
                </button>
              );
            })}
          </div>
        </DraggableCard>

        {/* Trend Chart */}
        <DraggableCard key="trend-chart" id="trend-chart" title="问题趋势">
          <div className="h-[200px] py-2">
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

        {/* Completion Pie Chart */}
        <DraggableCard key="completion-pie" id="completion-pie" title="问题完成率">
          <div className="h-[200px] py-2 flex items-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={completionPie}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {completionPie.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const d = payload[0].payload;
                      return (
                        <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] px-3 py-2 shadow-lg">
                          <p className="text-white text-xs font-medium">{d.name}: {d.value}</p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  formatter={(value: string) => <span className="text-xs text-[#8a8f98]">{value}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </DraggableCard>

        {/* Department Bar Chart */}
        <DraggableCard key="dept-bar" id="dept-bar" title="各部门问题统计">
          <div className="h-[200px] py-2">
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
      </DraggableGrid>
    </div>
  );
}
