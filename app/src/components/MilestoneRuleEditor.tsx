import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import type { MilestoneEvaluation } from '@/types';

interface MilestoneRuleEditorProps {
  evaluation: MilestoneEvaluation;
  onClose: () => void;
}

export function MilestoneRuleEditor({ evaluation, onClose }: MilestoneRuleEditorProps) {
  const { updateMilestoneEvaluation } = useAppStore();
  const [notes, setNotes] = useState(evaluation.notes ?? '');
  const [status, setStatus] = useState(evaluation.status);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await updateMilestoneEvaluation(evaluation.evaluationId, { notes: notes || undefined, status });
    setSaving(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-[#141416] border border-[#2a2a2e] rounded-[6px] p-6 w-[400px] shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-white font-semibold mb-1">{'编辑里程碑'}</h3>
        <p className="text-xs text-[#8a8f98] mb-4">{evaluation.ruleName}</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">{'状态'}</label>
            <select value={status} onChange={(e) => setStatus(e.target.value as MilestoneEvaluation['status'])}
              className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37]">
              <option value="not_started">{'未开始'}</option>
              <option value="in_progress">{'进行中'}</option>
              <option value="completed">{'已完成'}</option>
              <option value="blocked">{'阻塞'}</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">{'备注'}</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
              className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37] resize-none"
              placeholder={'添加备注...'} />
          </div>
          <div className="bg-[#0a0a0c] rounded-[4px] p-3 text-xs">
            <div className="flex justify-between mb-1">
              <span className="text-[#8a8f98]">{'当前值'}</span>
              <span className="text-white font-tabular">{(evaluation.currentValue * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#8a8f98]">{'目标值'}</span>
              <span className="text-white font-tabular">{evaluation.targetValue}%</span>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-1.5 text-xs bg-[#1a1a1e] border border-[#2a2a2e] rounded-[4px] text-[#8a8f98] hover:text-white">{'取消'}</button>
          <button onClick={handleSave} disabled={saving}
            className="px-4 py-1.5 text-xs bg-[#d4af37] rounded-[4px] text-black font-medium hover:bg-[#c4a030] disabled:opacity-50">
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}
