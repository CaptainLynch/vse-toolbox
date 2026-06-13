import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import type { TimelineNode } from '@/types';

interface TimelineNodeEditorProps {
  node: TimelineNode | null;
  onClose: () => void;
  onSaved: () => void;
}

export function TimelineNodeEditor({ node, onClose, onSaved }: TimelineNodeEditorProps) {
  const { createTimelineNode, updateTimelineNode, deleteTimelineNode } = useAppStore();
  const [name, setName] = useState(node?.name ?? '');
  const [targetDate, setTargetDate] = useState(node?.targetDate ?? '');
  const [actualDate, setActualDate] = useState(node?.actualDate ?? '');
  const [description, setDescription] = useState(node?.description ?? '');
  const [status, setStatus] = useState<TimelineNode['status']>(node?.status ?? 'pending');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    const data = { name: name.trim(), targetDate: targetDate || null, actualDate: actualDate || null, description: description || null, status };
    if (node) { await updateTimelineNode(node.id, data); } else { await createTimelineNode(data); }
    setSaving(false);
    onSaved();
  };

  const handleDelete = async () => {
    if (node && confirm('确定删除该时间节点？关联的里程碑规则也将被删除。')) {
      await deleteTimelineNode(node.id);
      onSaved();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-[#141416] border border-[#2a2a2e] rounded-[6px] p-6 w-[400px] shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-white font-semibold mb-4">{node ? '编辑时间节点' : '新建时间节点'}</h3>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">{'名称'} *</label>
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37]"
              placeholder={'如: OTS, SOP'} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">{'计划日期'}</label>
              <input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)}
                className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37]" />
            </div>
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">{'实际日期'}</label>
              <input type="date" value={actualDate} onChange={(e) => setActualDate(e.target.value)}
                className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37]" />
            </div>
          </div>
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">{'状态'}</label>
            <select value={status} onChange={(e) => setStatus(e.target.value as TimelineNode['status'])}
              className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37]">
              <option value="pending">{'待开始'}</option>
              <option value="in_progress">{'进行中'}</option>
              <option value="completed">{'已完成'}</option>
              <option value="delayed">{'延期'}</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">{'描述'}</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
              className="w-full bg-[#0a0a0c] border border-[#2a2a2e] rounded-[4px] px-3 py-2 text-sm text-white outline-none focus:border-[#d4af37] resize-none" />
          </div>
        </div>
        <div className="flex justify-between mt-5">
          {node ? (
            <button onClick={handleDelete} className="px-3 py-1.5 text-xs text-red-400 hover:text-red-300">{'删除'}</button>
          ) : <div />}
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-1.5 text-xs bg-[#1a1a1e] border border-[#2a2a2e] rounded-[4px] text-[#8a8f98] hover:text-white">{'取消'}</button>
            <button onClick={handleSave} disabled={saving || !name.trim()}
              className="px-4 py-1.5 text-xs bg-[#d4af37] rounded-[4px] text-black font-medium hover:bg-[#c4a030] disabled:opacity-50">
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
