import { Target, Calendar, CheckCircle2 } from 'lucide-react';

interface MilestoneStickyCardsProps {
  milestones: {
    name: string;
    percentage: number;
    actualPercentage: number | null;
    targetDate: string | null;
    actualDate: string | null;
    category: string;
  }[];
}

/**
 * Horizontal scrolling sticky card row for milestones.
 * Uses CSS `position: sticky` to remain visible at the top of the scroll container.
 */
export function MilestoneStickyCards({ milestones }: MilestoneStickyCardsProps) {
  if (milestones.length === 0) {
    return (
      <div className="sticky top-0 z-10 bg-[#0a0a0c] pt-2 pb-3">
        <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] px-4 py-3 text-center">
          <p className="text-[#8a8f98] text-sm">暂无里程碑数据</p>
        </div>
      </div>
    );
  }

  return (
    <div className="sticky top-0 z-10 bg-[#0a0a0c] pt-2 pb-3">
      <div className="flex gap-3 overflow-x-auto pb-1 scrollbar-thin">
        {milestones.map((m, i) => {
          const pct = m.percentage;
          const barColor =
            pct >= 100 ? '#4ade80' : pct >= 50 ? '#d4af37' : '#ef4444';
          const isDone = pct >= 100;

          return (
            <div
              key={i}
              className="min-w-[200px] max-w-[240px] flex-shrink-0 bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-4 flex flex-col gap-2"
            >
              {/* Header: name + badge + percentage */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm font-medium truncate">
                    {m.name}
                  </p>
                  <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded bg-[#222225] text-[#8a8f98]">
                    {m.category}
                  </span>
                </div>
                <span
                  className="text-lg font-bold font-tabular flex-shrink-0"
                  style={{ color: barColor }}
                >
                  {pct}%
                </span>
              </div>

              {/* Progress bar */}
              <div className="w-full h-1.5 bg-[#2a2a2e] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min(pct, 100)}%`,
                    backgroundColor: barColor,
                  }}
                />
              </div>

              {/* Dates */}
              <div className="flex flex-col gap-1 text-[11px] text-[#8a8f98]">
                <div className="flex items-center gap-1">
                  <Target className="w-3 h-3 text-[#d4af37]" />
                  <span>计划: {m.targetDate ?? '—'}</span>
                </div>
                <div className="flex items-center gap-1">
                  {isDone ? (
                    <CheckCircle2 className="w-3 h-3 text-[#4ade80]" />
                  ) : (
                    <Calendar className="w-3 h-3 text-[#4ade80]" />
                  )}
                  <span>
                    {isDone ? '完成' : '实际'}: {m.actualDate ?? '—'}
                  </span>
                </div>
                {m.actualPercentage != null && (
                  <span className="text-[#4ade80]">
                    实际完成: {m.actualPercentage}%
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
