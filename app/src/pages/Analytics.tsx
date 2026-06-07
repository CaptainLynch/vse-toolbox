import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts';

export function Analytics() {
  const { stats, fetchStats, milestones, fetchMilestones } = useAppStore();

  useEffect(() => {
    fetchStats();
    fetchMilestones();
  }, []);

  // Donut chart: 从 stats 计算总关闭率
  const totalIssues = stats
    ? stats.departmentStats.reduce((sum, d) => sum + d.totalIssues, 0)
    : 0;
  const closedIssues = stats
    ? stats.departmentStats.reduce((sum, d) => sum + Math.round(d.totalIssues * d.closedRate / 100), 0)
    : 0;
  const closeRate = totalIssues > 0 ? Math.round((closedIssues / totalIssues) * 100) : 0;

  // Milestone donut data from real milestones
  const milestoneDonutData = milestones.map((m) => ({
    name: m.name,
    value: m.percentage,
  }));

  // Combined chart: department stats
  const barData = stats?.departmentStats.map((d) => ({
    department: d.department,
    closedRate: d.closedRate,
    totalIssues: d.totalIssues,
  })) ?? [];

  // Trend data from stats
  const trendData = stats?.trend ?? [];

  // Tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] px-3 py-2 shadow-lg">
          <p className="text-[#8a8f98] text-[11px] mb-1">{label}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className="text-white text-xs font-medium" style={{ color: entry.color }}>
              {entry.name}: {entry.value}
              {entry.name.includes('率') || entry.name.includes('达成') ? '%' : ''}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  // Milestone breakdown table from department stats
  const breakdownRows = stats?.departmentStats.map((d) => ({
    name: d.department,
    closedRate: d.closedRate,
    totalIssues: d.totalIssues,
  })) ?? [];

  return (
    <div className="p-6 overflow-auto h-[calc(100vh-56px)]">
      {/* Page Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white mb-2">项目数据分析</h1>
        <p className="text-[13px] text-[#8a8f98]">
          多维度展示项目健康度、资源负荷、问题趋势等关键指标
        </p>
      </div>

      {/* Donut Chart: 总关闭率 + 各里程碑达成率 */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {/* 总关闭率 */}
        <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-6 h-[280px] flex flex-col items-center">
          <h3 className="text-white text-sm font-semibold mb-4 self-start">问题总关闭率</h3>
          <div className="relative w-[160px] h-[160px] flex-shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={[{ value: closeRate }, { value: 100 - closeRate }]}
                  cx="50%"
                  cy="50%"
                  innerRadius={58}
                  outerRadius={74}
                  startAngle={90}
                  endAngle={-270}
                  dataKey="value"
                  stroke="none"
                  cornerRadius={4}
                >
                  <Cell fill="#d4af37" />
                  <Cell fill="#1c1c1e" />
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-bold text-white font-tabular">{closeRate}%</span>
            </div>
          </div>
          <div className="flex items-center gap-4 mt-4 self-start">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-[#d4af37]" />
              <span className="text-[11px] text-[#8a8f98]">已关闭</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-[#1c1c1e]" />
              <span className="text-[11px] text-[#8a8f98]">未关闭</span>
            </div>
          </div>
        </div>

        {/* 里程碑达成率 */}
        {milestoneDonutData.slice(0, 3).map((item) => {
          const remaining = 100 - item.value;
          return (
            <div key={item.name} className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-6 h-[280px] flex flex-col items-center">
              <h3 className="text-white text-sm font-semibold mb-4 self-start">{item.name}</h3>
              <div className="relative w-[160px] h-[160px] flex-shrink-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={[{ value: item.value }, { value: remaining }]}
                      cx="50%"
                      cy="50%"
                      innerRadius={58}
                      outerRadius={74}
                      startAngle={90}
                      endAngle={-270}
                      dataKey="value"
                      stroke="none"
                      cornerRadius={4}
                    >
                      <Cell fill="#d4af37" />
                      <Cell fill="#1c1c1e" />
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-3xl font-bold text-white font-tabular">{item.value}%</span>
                </div>
              </div>
              <div className="flex items-center gap-4 mt-4 self-start">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-[#d4af37]" />
                  <span className="text-[11px] text-[#8a8f98]">已完成</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-[#1c1c1e]" />
                  <span className="text-[11px] text-[#8a8f98]">未完成</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Combined Chart Section */}
      <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-6 h-[420px] mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white text-sm font-semibold">问题统计与趋势分析</h3>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-[#d4af37]" />
              <span className="text-[11px] text-[#8a8f98]">关闭率</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-[#d4af37] opacity-40" />
              <span className="text-[11px] text-[#8a8f98]">新增趋势</span>
            </div>
          </div>
        </div>
        <div className="flex gap-6 h-[340px]">
          {/* Bar Chart */}
          <div className="w-[55%] h-full">
            <h4 className="text-[11px] text-[#8a8f98] mb-2 tracking-[0.5px] uppercase">各部门问题关闭率</h4>
            <ResponsiveContainer width="100%" height="95%">
              <BarChart data={barData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e1e20" horizontal={false} />
                <XAxis
                  type="number"
                  domain={[0, 100]}
                  tick={{ fill: '#8a8f98', fontSize: 11 }}
                  axisLine={{ stroke: '#2a2a2e' }}
                  tickLine={false}
                />
                <YAxis
                  dataKey="department"
                  type="category"
                  tick={{ fill: '#8a8f98', fontSize: 12 }}
                  axisLine={{ stroke: '#2a2a2e' }}
                  tickLine={false}
                  width={70}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="closedRate" name="关闭率" radius={[0, 4, 4, 0]} maxBarSize={24}>
                  {barData.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={entry.closedRate >= 80 ? '#d4af37' : '#2a2a2e'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Divider */}
          <div className="w-px bg-[#2a2a2e] flex-shrink-0" />

          {/* Area Chart - Trend */}
          <div className="w-[45%] h-full">
            <h4 className="text-[11px] text-[#8a8f98] mb-2 tracking-[0.5px] uppercase">近 14 天问题新增趋势</h4>
            <ResponsiveContainer width="100%" height="95%">
              <AreaChart data={trendData} margin={{ top: 10, right: 10 }}>
                <defs>
                  <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#d4af37" stopOpacity={0.2} />
                    <stop offset="100%" stopColor="#d4af37" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e1e20" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: '#8a8f98', fontSize: 11 }}
                  axisLine={{ stroke: '#2a2a2e' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#8a8f98', fontSize: 11 }}
                  axisLine={{ stroke: '#2a2a2e' }}
                  tickLine={false}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="count"
                  name="新增问题数"
                  stroke="#d4af37"
                  strokeWidth={2}
                  fill="url(#trendGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Bottom Row - Department Breakdown */}
      <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-6">
        <h3 className="text-white text-sm font-semibold mb-4">各部门问题统计明细</h3>
        <div className="grid grid-cols-[1fr_1fr_1fr] gap-0">
          {/* Header */}
          <div className="px-4 py-3 text-[11px] text-[#8a8f98] font-medium border-b border-[#2a2a2e]">部门</div>
          <div className="px-4 py-3 text-[11px] text-[#8a8f98] font-medium border-b border-[#2a2a2e]">总问题数</div>
          <div className="px-4 py-3 text-[11px] text-[#8a8f98] font-medium border-b border-[#2a2a2e]">关闭率</div>

          {breakdownRows.map((row) => (
            <>
              <div key={`${row.name}-label`} className="px-4 py-3 text-xs text-white border-b border-[#1e1e20]">
                {row.name}
              </div>
              <div key={`${row.name}-total`} className="px-4 py-3 text-xs text-white font-tabular border-b border-[#1e1e20]">
                {row.totalIssues}
              </div>
              <div key={`${row.name}-rate`} className="px-4 py-3 border-b border-[#1e1e20]">
                <div className="flex items-center gap-2">
                  <div className="w-full h-1.5 bg-[#2a2a2e] rounded-full overflow-hidden max-w-[80px]">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${row.closedRate}%`,
                        backgroundColor: row.closedRate >= 80 ? '#4ade80' : row.closedRate >= 50 ? '#d4af37' : '#8a8f98',
                      }}
                    />
                  </div>
                  <span className="text-xs text-white font-tabular">{row.closedRate}%</span>
                </div>
              </div>
            </>
          ))}
        </div>
      </div>
    </div>
  );
}
