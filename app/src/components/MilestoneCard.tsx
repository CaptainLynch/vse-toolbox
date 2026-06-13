import type { MilestoneEvaluation } from '@/types';

const statusColors: Record<string, string> = {
  not_started: '#8a8f98',
  in_progress: '#d4af37',
  completed: '#4ade80',
  blocked: '#ef4444',
};

const statusLabels: Record<string, string> = {
  not_started: '未开始',
  in_progress: '进行中',
  completed: '已完成',
  blocked: '阻塞',
};

interface MilestoneCardProps {
  evaluation: MilestoneEvaluation;
  onClick?: () => void;
}

export function MilestoneCard({ evaluation, onClick }: MilestoneCardProps) {
  const progress = evaluation.targetValue > 0
    ? Math.round((evaluation.currentValue / evaluation.targetValue) * 100)
    : evaluation.currentValue > 0 ? 100 : 0;

  return (
    <div className="bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] p-4 h-full w-full flex flex-col cursor-pointer hover:border-[#d4af37] transition-colors" onClick={onClick}>
      <div className="flex items-start justify-between mb-2">
        <h4 className="text-sm font-medium text-white leading-tight">{evaluation.ruleName}</h4>
        <span className="text-[10px] px-1.5 py-0.5 rounded-sm font-medium shrink-0 ml-2" style={{ backgroundColor: statusColors[evaluation.status] + '20', color: statusColors[evaluation.status] }}>
          {statusLabels[evaluation.status]}
        </span>
      </div>
      {evaluation.timelineNodeName && (
        <span className="text-[10px] text-[#8a8f98] mb-2">{'关联'}: {evaluation.timelineNodeName}</span>
      )}
      <div className="mt-auto">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px] text-[#8a8f98]">{evaluation.category}</span>
          <span className="text-[11px] text-white font-tabular">{progress}%</span>
        </div>
        <div className="w-full h-1.5 bg-[#1a1a1e] rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-500" style={{ width: Math.min(progress, 100) + '%', backgroundColor: statusColors[evaluation.status] }} />
        </div>
      </div>
      {evaluation.evaluatedAt && (
        <p className="text-[10px] text-[#5a5f68] mt-2">{'评估'}: {evaluation.evaluatedAt.slice(0, 16).replace('T', ' ')}</p>
      )}
    </div>
  );
}
