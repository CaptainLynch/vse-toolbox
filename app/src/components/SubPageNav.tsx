import { useState } from 'react';
import { BarChart3, ClipboardList, AlertTriangle, FileText, Plus } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { cn } from '@/lib/utils';

interface SubPageNavProps {
  pages: Record<string, { label: string }>;
  active: string;
  onChange: (key: string) => void;
}

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  overview: BarChart3,
  issues: ClipboardList,
  ewo: AlertTriangle,
  tir: FileText,
};

export function SubPageNav({ pages, active, onChange }: SubPageNavProps) {
  const { createDeliverableCategory } = useAppStore();
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newCategory, setNewCategory] = useState({ id: '', name: '', icon: '' });

  const handleAddCategory = async () => {
    if (newCategory.id && newCategory.name) {
      await createDeliverableCategory(newCategory);
      setNewCategory({ id: '', name: '', icon: '' });
      setShowAddDialog(false);
    }
  };

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-[#2a2a2e]">
      {Object.entries(pages).map(([key, { label }]) => {
        const Icon = iconMap[key];
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              active === key
                ? 'bg-[#d4af37] text-black'
                : 'bg-[#1c1c1e] text-[#8a8f98] hover:text-white'
            )}
          >
            {Icon && <Icon className="w-4 h-4" />}
            <span>{label}</span>
          </button>
        );
      })}
      <button
        onClick={() => setShowAddDialog(true)}
        className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-medium text-[#8a8f98] hover:text-white transition-colors"
      >
        <Plus className="w-4 h-4" />
        <span>添加</span>
      </button>

      {showAddDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-[#141416] border border-[#2a2a2e] rounded-lg p-6 w-96">
            <h3 className="text-white text-lg font-semibold mb-4">添加交付物分类</h3>
            <div className="space-y-4">
              <div>
                <label className="text-[#8a8f98] text-sm mb-1 block">ID</label>
                <input
                  type="text"
                  value={newCategory.id}
                  onChange={(e) => setNewCategory({ ...newCategory, id: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0a0a0c] border border-[#2a2a2e] rounded-lg text-white text-sm"
                  placeholder="例如: new-type"
                />
              </div>
              <div>
                <label className="text-[#8a8f98] text-sm mb-1 block">名称</label>
                <input
                  type="text"
                  value={newCategory.name}
                  onChange={(e) => setNewCategory({ ...newCategory, name: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0a0a0c] border border-[#2a2a2e] rounded-lg text-white text-sm"
                  placeholder="例如: 新交付物类型"
                />
              </div>
              <div>
                <label className="text-[#8a8f98] text-sm mb-1 block">图标</label>
                <input
                  type="text"
                  value={newCategory.icon}
                  onChange={(e) => setNewCategory({ ...newCategory, icon: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0a0a0c] border border-[#2a2a2e] rounded-lg text-white text-sm"
                  placeholder="例如: 📋"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setShowAddDialog(false)}
                className="px-4 py-2 text-sm text-[#8a8f98] hover:text-white transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleAddCategory}
                className="px-4 py-2 bg-[#d4af37] text-black text-sm font-medium rounded-lg hover:brightness-110 transition-all"
              >
                添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}