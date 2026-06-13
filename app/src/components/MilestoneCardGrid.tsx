import { useState, useEffect } from 'react';
import { DraggableGrid } from '@/components/DraggableGrid';
import { DraggableCard } from '@/components/DraggableCard';
import { MilestoneCard } from '@/components/MilestoneCard';
import { MilestoneRuleEditor } from '@/components/MilestoneRuleEditor';
import { useAppStore } from '@/stores/appStore';
import type { MilestoneEvaluation } from '@/types';
import { RefreshCw, Plus } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export function MilestoneCardGrid() {
  const {
    milestoneEvaluations,
    selectedTimelineNodeId,
    fetchMilestoneEvaluations,
    refreshMilestoneEvaluations,
    layouts,
    fetchLayouts,
    saveLayouts
  } = useAppStore();

  const [editingEval, setEditingEval] = useState<MilestoneEvaluation | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);

  // Fetch initial milestones layout and evaluations
  useEffect(() => {
    fetchLayouts('milestones');
  }, []);

  useEffect(() => {
    fetchMilestoneEvaluations(selectedTimelineNodeId ?? undefined);
  }, [selectedTimelineNodeId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await refreshMilestoneEvaluations(selectedTimelineNodeId ?? undefined);
    setRefreshing(false);
  };

  const currentLayout = layouts['milestones'] ?? [];
  
  // Filter evaluations that are present in the layout
  const visibleEvaluations = milestoneEvaluations.filter(ev =>
    currentLayout.some(c => c.cardId === 'ms-' + ev.evaluationId)
  );

  // Filter evaluations that are NOT present in the layout (available to be added)
  const availableEvaluations = milestoneEvaluations.filter(ev =>
    !currentLayout.some(c => c.cardId === 'ms-' + ev.evaluationId)
  );

  const handleAddCard = async (evalId: number) => {
    const cardId = 'ms-' + evalId;
    const x = currentLayout.length % 3;
    const y = Math.floor(currentLayout.length / 3);
    const newCard = {
      pageKey: 'milestones',
      cardId,
      cardType: 'milestone',
      x,
      y,
      w: 1,
      h: 1,
    };
    await saveLayouts('milestones', [...currentLayout, newCard]);
    setShowAddDialog(false);
  };

  const handleRemoveCard = async (evalId: number) => {
    const updated = currentLayout.filter(c => c.cardId !== 'ms-' + evalId);
    // Snap positions to 3 columns without gaps
    const repositioned = updated.map((card, index) => ({
      ...card,
      x: index % 3,
      y: Math.floor(index / 3),
    }));
    await saveLayouts('milestones', repositioned);
  };

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-white">{'里程碑状态'}</h2>
        <div className="flex items-center gap-2">
          {milestoneEvaluations.length > 0 && (
            <button
              onClick={() => setShowAddDialog(true)}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-[#1a1a1e] border border-[#2a2a2e] rounded-[4px] text-[#d4af37] hover:border-[#d4af37] transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              添加状态
            </button>
          )}
          <button onClick={handleRefresh} disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#1a1a1e] border border-[#2a2a2e] rounded-[4px] text-[#d4af37] hover:border-[#d4af37] transition-colors disabled:opacity-50">
            <RefreshCw className={'w-3 h-3' + (refreshing ? ' animate-spin' : '')} />
            {refreshing ? '刷新中...' : '刷新评估'}
          </button>
        </div>
      </div>

      {milestoneEvaluations.length === 0 ? (
        <div className="bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] p-8 text-center">
          <p className="text-[#8a8f98] text-sm">{'暂无里程碑规则'}</p>
          <p className="text-[#5a5f68] text-xs mt-1">{'请在「设置 → 里程碑配置」中添加规则'}</p>
        </div>
      ) : visibleEvaluations.length === 0 ? (
        <div className="bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] p-12 text-center flex flex-col items-center justify-center">
          <p className="text-[#8a8f98] text-sm">{'暂无已添加的里程碑状态'}</p>
          <p className="text-[#5a5f68] text-xs mt-1 mb-4">{'点击上方「添加状态」按钮，选择并展示关心的里程碑状态'}</p>
          <button onClick={() => setShowAddDialog(true)}
            className="flex items-center gap-1.5 px-4 py-2 text-xs bg-[#d4af37] text-black font-semibold rounded-[4px] hover:brightness-110 transition-all hover:shadow-[0_0_12px_rgba(212,175,55,0.15)]">
            <Plus className="w-3.5 h-3.5" />
            添加状态
          </button>
        </div>
      ) : (
        <DraggableGrid pageKey="milestones" cols={3} rowHeight={160}>
          {visibleEvaluations.map((ev) => (
            <DraggableCard
              key={'ms-' + ev.evaluationId}
              id={'ms-' + ev.evaluationId}
              title={ev.ruleName}
              onRemove={() => handleRemoveCard(ev.evaluationId)}
            >
              <div className="w-full h-full">
                <MilestoneCard evaluation={ev} onClick={() => setEditingEval(ev)} />
              </div>
            </DraggableCard>
          ))}
        </DraggableGrid>
      )}

      {editingEval && <MilestoneRuleEditor evaluation={editingEval} onClose={() => setEditingEval(null)} />}

      {/* Add Milestone Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white">添加里程碑状态卡片</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 mt-4 max-h-[300px] overflow-y-auto pr-1">
            {availableEvaluations.length === 0 ? (
              <p className="text-xs text-[#8a8f98] text-center py-4">所有里程碑状态已添加</p>
            ) : (
              availableEvaluations.map((ev) => (
                <div
                  key={ev.evaluationId}
                  className="flex items-center justify-between p-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] hover:border-[#d4af37] transition-all"
                >
                  <div className="flex-1 min-w-0 mr-3">
                    <div className="text-xs text-white font-medium truncate">{ev.ruleName}</div>
                    <div className="text-[10px] text-[#8a8f98] mt-0.5 truncate">{ev.category} | 关联: {ev.timelineNodeName ?? '无'}</div>
                  </div>
                  <button
                    onClick={() => handleAddCard(ev.evaluationId)}
                    className="h-7 px-3 bg-[#d4af37] hover:brightness-110 text-black text-xs font-semibold rounded-[4px] transition-all flex items-center gap-1 shrink-0"
                  >
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