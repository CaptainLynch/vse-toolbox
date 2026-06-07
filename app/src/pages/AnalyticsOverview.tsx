import React from 'react';
import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { DraggableGrid } from '@/components/DraggableGrid';
import { DraggableCard } from '@/components/DraggableCard';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { TrendingUp, TrendingDown, ArrowUpRight, ClipboardList, AlertTriangle, FileText } from 'lucide-react';

interface AnalyticsOverviewProps {
  onNavigate: (page: string) => void;
}

const deliverableIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  issues: ClipboardList, ewo: AlertTriangle, tir: FileText,
};
const deliverableColors: Record<string, string> = {
  issues: '#d4af37', ewo: '#ff9f4d', tir: '#4ade80',
};

export function AnalyticsOverview({ onNavigate }: AnalyticsOverviewProps) {
  const { stats, fetchStats, milestones, fetchMilestones } = useAppStore();

  useEffect(() => { fetchStats(); fetchMilestones(); }, []);

  const kpis = stats ? [
    { label: '未关闭问题总数', value: stats.totalOpen, trend: 'up' },
    { label: '本周新增', value: stats.newThisWeek, trend: 'up' },
    { label: '本周关闭', value: stats.closedThisWeek, trend: 'down' },
    { label: '高风险预警', value: stats.highRiskCount, trend: 'up' },
  ] : [];

  const trendData = stats?.trend ?? [];
  const deliverableCards = [
    { key: 'issues', label: '造车问题', count: stats ? stats.totalOpen : 0 },
    { key: 'ewo', label: 'EWO/NCR', count: 8 },
    { key: 'tir', label: 'TIR', count: 15 },
  ];

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

  const kpiKeys = ['kpi-open', 'kpi-new', 'kpi-closed', 'kpi-risk'];

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white mb-2">项目数据总览</h1>
        <p className="text-[13px] text-[#8a8f98]">多维度展示项目健康度、资源负荷、问题趋势等关键指标</p>
      </div>

      <DraggableGrid pageKey="overview" cols={4} rowHeight={120}>
        {kpis.map((kpi, i) => (
          <DraggableCard key={kpiKeys[i]} id={kpiKeys[i]} title={kpi.label}>
            <div className="flex flex-col justify-between h-full py-2">
              <span className="text-3xl font-bold text-white font-tabular">{kpi.value}</span>
              <div className="flex items-center gap-1">
                {kpi.trend === 'up' ? <TrendingUp className="w-3 h-3 text-green-400" /> : <TrendingDown className="w-3 h-3 text-red-400" />}
                <span className="text-xs text-[#8a8f98]">实时数据</span>
              </div>
            </div>
          </DraggableCard>
        ))}

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

        <DraggableCard key="milestones" id="milestones" title="里程碑进度">
          <div className="space-y-3 overflow-auto py-2">
            {milestones.map((m) => (
              <div key={m.id} className="p-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-white text-sm">{m.name}</span>
                  <span className="text-[#d4af37] text-sm font-bold font-tabular">{m.percentage}%</span>
                </div>
                <div className="w-full h-1.5 bg-[#2a2a2e] rounded-full overflow-hidden">
                  <div className="h-full bg-[#d4af37] rounded-full transition-all" style={{ width: `${m.percentage}%` }} />
                </div>
              </div>
            ))}
          </div>
        </DraggableCard>

        <DraggableCard key="dept-stats" id="dept-stats" title="各部门问题统计">
          <div className="py-2">
            {stats && stats.departmentStats.length > 0 ? (
              <div className="grid grid-cols-[1fr_1fr_1fr] gap-0">
                <div className="px-4 py-2 text-[11px] text-[#8a8f98] font-medium border-b border-[#2a2a2e]">部门</div>
                <div className="px-4 py-2 text-[11px] text-[#8a8f98] font-medium border-b border-[#2a2a2e]">总问题数</div>
                <div className="px-4 py-2 text-[11px] text-[#8a8f98] font-medium border-b border-[#2a2a2e]">关闭率</div>
                {stats.departmentStats.map((ds) => (
                  <React.Fragment key={ds.department}>
                    <div className="px-4 py-2 text-xs text-white border-b border-[#1e1e20]">{ds.department}</div>
                    <div className="px-4 py-2 text-xs text-white font-tabular border-b border-[#1e1e20]">{ds.totalIssues}</div>
                    <div className="px-4 py-2 border-b border-[#1e1e20]">
                      <div className="flex items-center gap-2">
                        <div className="w-full h-1.5 bg-[#2a2a2e] rounded-full overflow-hidden max-w-[80px]">
                          <div className="h-full rounded-full" style={{ width: `${ds.closedRate}%`, backgroundColor: ds.closedRate >= 80 ? '#4ade80' : ds.closedRate >= 50 ? '#d4af37' : '#8a8f98' }} />
                        </div>
                        <span className="text-xs text-white font-tabular">{ds.closedRate}%</span>
                      </div>
                    </div>
                  </React.Fragment>
                ))}
              </div>
            ) : (
              <p className="text-[#8a8f98] text-sm text-center py-4">暂无数据</p>
            )}
          </div>
        </DraggableCard>
      </DraggableGrid>
    </div>
  );
}