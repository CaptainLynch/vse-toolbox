import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { TimelineNodeEditor } from '@/components/TimelineNodeEditor';
import type { TimelineNode } from '@/types';
import { Plus } from 'lucide-react';

const statusColors: Record<string, string> = {
  pending: '#8a8f98',
  in_progress: '#d4af37',
  completed: '#4ade80',
  delayed: '#ef4444',
};

const statusLabels: Record<string, string> = {
  pending: '待开始',
  in_progress: '进行中',
  completed: '已完成',
  delayed: '延期',
};

function getNodeVisual(node: TimelineNode): { color: string; label: string } {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

  if (node.actualDate) {
    if (node.targetDate && node.actualDate > node.targetDate) {
      return { color: '#d4af37', label: '超期完成' };
    }
    return { color: '#4ade80', label: '按时完成' };
  }

  if (node.targetDate && node.targetDate < today) {
    return { color: '#ef4444', label: '已超期' };
  }

  return { color: statusColors[node.status], label: statusLabels[node.status] };
}

export function ProjectTimeline() {
  const { timelineNodes, fetchTimelineNodes, selectedTimelineNodeId, setSelectedTimelineNodeId } = useAppStore();
  const [editingNode, setEditingNode] = useState<TimelineNode | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const handleEdit = (node: TimelineNode) => {
    const newId = node.id === selectedTimelineNodeId ? null : node.id;
    setSelectedTimelineNodeId(newId);
    setEditingNode(node);
  };
  const handleClose = () => { setEditingNode(null); setIsCreating(false); };

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-white">项目计划时间轴</h2>
        <button
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs bg-[#1a1a1e] border border-[#2a2a2e] rounded-[4px] text-[#d4af37] hover:border-[#d4af37] transition-colors"
        >
          <Plus className="w-3 h-3" />
          添加节点
        </button>
      </div>

      <div className="relative bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] p-6 overflow-x-auto">
        <div className="absolute top-1/2 left-6 right-6 h-px bg-[#2a2a2e]" style={{ transform: 'translateY(-50%)' }} />
        <div className="flex items-center justify-between min-w-[600px] relative">
          {timelineNodes.map((node, i) => {
            const visual = getNodeVisual(node);
            return (
              <div key={node.id} className="flex flex-col items-center relative z-10" style={{ flex: 1 }}>
                <button
                  onClick={() => handleEdit(node)}
                  className="w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all hover:scale-110 cursor-pointer"
                  style={{ borderColor: visual.color, backgroundColor: node.actualDate ? visual.color : '#0f0f11' }}
                  title={node.name + ' - ' + visual.label}
                >
                  {node.actualDate && (
                    <svg className="w-4 h-4 text-black" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </button>
                <div className="mt-3 text-center">
                  <p className="text-sm font-medium text-white">{node.name}</p>
                  {node.targetDate && <p className="text-[11px] text-[#8a8f98] mt-0.5">{node.targetDate}</p>}
                  {node.actualDate && <p className="text-[11px] text-[#4ade80] mt-0.5">{'实际'}: {node.actualDate}</p>}
                  <p className="text-[10px] mt-1" style={{ color: visual.color }}>{visual.label}</p>
                </div>
                {i < timelineNodes.length - 1 && (
                  <div className="absolute top-4 left-1/2 w-full h-px" style={{ backgroundColor: '#2a2a2e' }} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {(editingNode || isCreating) && (
        <TimelineNodeEditor node={editingNode} onClose={handleClose} onSaved={() => { fetchTimelineNodes(); handleClose(); }} />
      )}
    </div>
  );
}
