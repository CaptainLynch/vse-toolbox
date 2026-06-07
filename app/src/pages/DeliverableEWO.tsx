import { useRef, useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { cn } from '@/lib/utils';
import { DraggableGrid } from '@/components/DraggableGrid';
import { DraggableCard } from '@/components/DraggableCard';
import type { ExcelImportResult } from '@/services/api';
import { Plus, Trash2, Upload, CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';

const severityConfig: Record<string, { bg: string; text: string; label: string }> = {
  critical: { bg: '#3b1515', text: '#ff4d4d', label: '严重' },
  major: { bg: '#3b2015', text: '#ff9f4d', label: '重大' },
  minor: { bg: '#222225', text: '#8a8f98', label: '轻微' },
};

const statusConfig: Record<string, { dot: string; label: string }> = {
  open: { dot: '#ff4d4d', label: '待处理' },
  investigating: { dot: '#d4af37', label: '调查中' },
  resolved: { dot: '#4ade80', label: '已解决' },
  closed: { dot: '#8a8f98', label: '已关闭' },
};

const PAGE_SIZE = 20;

export function DeliverableEWO() {
  const { ewos, ewoTotal, ewoPage, setEwoPage, fetchEwos, createEwo, deleteEwo, importEwosExcel } = useAppStore();
  const [showCreate, setShowCreate] = useState(false);
  const defaultForm = { type: 'EWO', title: '', description: '', severity: 'minor', department: '', assignee: '' };
  const [form, setForm] = useState(defaultForm);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ExcelImportResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const totalPages = Math.max(1, Math.ceil(ewoTotal / PAGE_SIZE));

  useEffect(() => { fetchEwos(); }, [ewoPage]);

  const handleImportExcel = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    const result = await importEwosExcel(file);
    setImporting(false);
    if (result) {
      setImportResult(result);
      toast.success(`导入完成：新增 ${result.created}，更新 ${result.updated}`);
      if (result.errors.length > 0) toast.warning(`${result.errors.length} 条记录导入失败`);
    } else {
      toast.error('导入失败，请检查文件格式');
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleCloseCreate = () => {
    setShowCreate(false);
    setForm(defaultForm);
  };

  const handleCreate = async () => {
    if (!form.title.trim()) { toast.error('请填写标题'); return; }
    const ok = await createEwo(form);
    if (ok) { handleCloseCreate(); toast.success('创建成功'); }
    else { toast.error('创建失败'); }
  };

  const handleDelete = async (id: string) => {
    const ok = await deleteEwo(id);
    if (ok) toast.success('已删除'); else toast.error('删除失败');
  };

  const kpis = [
    { label: 'EWO/NCR 总数', value: ewoTotal },
    { label: '待处理', value: ewos.filter(e => e.status === 'open' || e.status === 'investigating').length },
    { label: '严重风险', value: ewos.filter(e => e.severity === 'critical' && e.status !== 'closed').length },
  ];

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-2">EWO/NCR</h1>
          <p className="text-[13px] text-[#8a8f98]">EWO/NCR 交付物管理</p>
        </div>
        <div className="flex items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={handleImportExcel}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
            className="h-9 px-4 bg-transparent border border-[#2a2a2e] text-white text-sm rounded-[4px] hover:border-[#8a8f98] hover:bg-[#1c1c1e] transition-all flex items-center gap-2 disabled:opacity-50"
          >
            <Upload className="w-4 h-4 text-[#8a8f98]" />
            {importing ? '导入中...' : '导入 Excel'}
          </button>
          <button onClick={() => setShowCreate(true)} className="h-9 px-4 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 flex items-center gap-2">
            <Plus className="w-4 h-4" /> 新建
          </button>
        </div>
      </div>

      {/* Import Result Banner */}
      {importResult && (
        <div className="mb-4 p-3 bg-[#3b3015] border border-[#d4af37]/30 rounded-[4px] flex items-center gap-3">
          <CheckCircle2 className="w-4 h-4 text-[#d4af37] flex-shrink-0" />
          <div className="flex-1 text-xs text-[#d4af37]">
            导入完成：新增 <strong>{importResult.created}</strong> 条，更新 <strong>{importResult.updated}</strong> 条
            {importResult.errors.length > 0 && (
              <span className="ml-2 text-[#ff9f4d]">（{importResult.errors.length} 条失败）</span>
            )}
          </div>
          <button onClick={() => setImportResult(null)} className="text-[#8a8f98] hover:text-white text-xs">关闭</button>
        </div>
      )}

      <DraggableGrid pageKey="ewo" cols={4} rowHeight={120}>
        <DraggableCard key="ewo-kpi" id="ewo-kpi" title="EWO/NCR 概览">
          <div className="grid grid-cols-3 gap-4 py-2">
            {kpis.map((kpi, i) => (
              <div key={i} className="text-center">
                <div className="text-2xl font-bold text-white font-tabular">{kpi.value}</div>
                <div className="text-[11px] text-[#8a8f98] mt-1">{kpi.label}</div>
              </div>
            ))}
          </div>
        </DraggableCard>

        <DraggableCard key="ewo-table" id="ewo-table" title="EWO/NCR 列表">
          <div className="overflow-auto py-2">
            {ewos.length === 0 ? (
              <p className="text-[#8a8f98] text-sm text-center py-8">暂无数据，点击右上角新建</p>
            ) : (
              <div className="space-y-2">
                {ewos.map((ewo) => (
                  <div key={ewo.id} className="flex items-center gap-3 p-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] hover:bg-[#161618] transition-colors">
                    <span className="text-xs text-[#8a8f98] font-tabular w-[160px] truncate">{ewo.id}</span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold" style={{ backgroundColor: severityConfig[ewo.severity]?.bg, color: severityConfig[ewo.severity]?.text }}>{ewo.severity}</span>
                    <span className="text-xs text-white flex-1 truncate">{ewo.title}</span>
                    <div className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusConfig[ewo.status]?.dot }} />
                      <span className="text-xs text-[#8a8f98]">{statusConfig[ewo.status]?.label}</span>
                    </div>
                    <button onClick={() => handleDelete(ewo.id)} className="p-1 text-[#8a8f98] hover:text-red-400"><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DraggableCard>
      </DraggableGrid>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-3 mt-4">
          <div className="flex items-center gap-1">
            <button onClick={() => setEwoPage(Math.max(1, ewoPage - 1))} disabled={ewoPage === 1}
              className="p-1.5 text-[#8a8f98] hover:text-white disabled:opacity-30 transition-colors">
              <ChevronLeft className="w-4 h-4" />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
              <button key={page} onClick={() => setEwoPage(page)}
                className={cn('w-7 h-7 rounded-[4px] text-xs font-medium transition-colors',
                  page === ewoPage ? 'bg-[#d4af37] text-[#0a0a0c]' : 'text-[#8a8f98] hover:text-white hover:bg-[#1c1c1e]')}>
                {page}
              </button>
            ))}
            <button onClick={() => setEwoPage(Math.min(totalPages, ewoPage + 1))} disabled={ewoPage === totalPages}
              className="p-1.5 text-[#8a8f98] hover:text-white disabled:opacity-30 transition-colors">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={handleCloseCreate}>
          <div className="bg-[#141416] border border-[#2a2a2e] rounded p-6 w-[480px]" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-white text-lg font-semibold mb-4">新建 EWO/NCR</h2>
            <div className="space-y-3">
              <div className="flex gap-3">
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded text-sm text-white flex-1">
                  <option value="EWO">EWO</option><option value="NCR">NCR</option>
                </select>
                <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} className="h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded text-sm text-white flex-1">
                  <option value="minor">轻微</option><option value="major">重大</option><option value="critical">严重</option>
                </select>
              </div>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="标题 *" className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded text-sm text-white" />
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="描述" rows={3} className="w-full px-3 py-2 bg-[#0f0f11] border border-[#2a2a2e] rounded text-sm text-white resize-none" />
              <div className="flex gap-3">
                <input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} placeholder="责任部门" className="h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded text-sm text-white flex-1" />
                <input value={form.assignee} onChange={(e) => setForm({ ...form, assignee: e.target.value })} placeholder="负责人" className="h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded text-sm text-white flex-1" />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button onClick={handleCloseCreate} className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white">取消</button>
                <button onClick={handleCreate} className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded hover:brightness-110">提交</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}