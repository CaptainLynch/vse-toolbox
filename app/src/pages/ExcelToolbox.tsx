import { useState } from 'react';
import { cn } from '@/lib/utils';
import { api } from '@/services/api';
import {
  FileSpreadsheet,
  FileEdit,
  Layers,
  ClipboardCheck,
  Database,
  GitCompareArrows,
  BarChart3,
  Palette,
  Scissors,
  FileText,
  CalendarClock,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  FlaskConical,
  Shield,
  Lock,
  X,
  Upload,
  Loader2,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';

// ---------------------------------------------------------------------------
// 模块配置
// ---------------------------------------------------------------------------

interface ExcelModule {
  id: string;
  name: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  status: 'ready' | 'planned' | 'beta';
}

const excelModules: ExcelModule[] = [
  { id: 'merge', name: '批量合并', description: '合并多份交付物表格，自动去重与汇总', icon: FileSpreadsheet, status: 'ready' },
  { id: 'merge-same', name: '同结构合并', description: '多个同结构 Excel 表格纵向拼接', icon: Layers, status: 'ready' },
  { id: 'rename', name: '批量改名', description: '根据规则批量重命名文件，支持正则', icon: FileEdit, status: 'ready' },
  { id: 'ledger', name: '交付物台账生成', description: '从多个 Excel 自动提取交付物清单，生成汇总台账', icon: ClipboardCheck, status: 'planned' },
  { id: 'validate', name: '数据校验与清洗', description: '检查空值、重复项、格式错误，自动标记或修复', icon: Database, status: 'planned' },
  { id: 'milestone', name: '里程碑进度表', description: '输入节点数据，自动生成里程碑甘特图/进度表', icon: CalendarClock, status: 'planned' },
  { id: 'issue-io', name: '问题清单导入导出', description: '与问题追踪联动 — Excel 导入批量 Issue 或导出筛选结果', icon: FileText, status: 'planned' },
  { id: 'compare', name: '跨表数据比对', description: '两份 Excel 按关键列比对差异（BOM 比对、版本比对）', icon: GitCompareArrows, status: 'planned' },
  { id: 'report', name: '统计报表模板', description: '按部门/优先级/状态自动生成统计汇总表', icon: BarChart3, status: 'planned' },
  { id: 'format', name: '条件格式化', description: '按规则自动标红超期项、高亮 P0 问题、着色风险等级', icon: Palette, status: 'planned' },
  { id: 'split', name: '多 Sheet 拆分', description: '按某列值将一个工作簿拆分为多个独立文件', icon: Scissors, status: 'planned' },
];

const statusConfig = {
  ready: { icon: CheckCircle2, label: '可用', color: '#4ade80' },
  planned: { icon: Clock, label: '规划中', color: '#8a8f98' },
  beta: { icon: FlaskConical, label: '测试中', color: '#d4af37' },
};

// ---------------------------------------------------------------------------
// 对话框组件
// ---------------------------------------------------------------------------

/** Excel 合并 / 同结构合并 */
function FileUploadDialog({
  open,
  onClose,
  title,
  mode,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  mode: 'merge' | 'merge-same';
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ name: string; path: string } | null>(null);

  const handleUpload = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append('files', f));
      const endpoint = mode === 'merge' ? '/excel/merge' : '/excel/merge-same';
      const res = await api.upload<{ file_path: string; file_name: string }>(endpoint, fd);
      if (res.success && res.data) {
        setResult({ name: res.data.file_name, path: res.data.file_path });
        toast.success('文件合并成功');
      } else {
        toast.error(res.message || '合并失败');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (result) api.download(result.path);
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-white">{title}</DialogTitle>
          <DialogDescription className="text-[#8a8f98]">
            上传多个 Excel 文件，系统将自动处理
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 mt-4">
          <label className="block border-2 border-dashed border-[#2a2a2e] rounded-[4px] p-8 text-center cursor-pointer hover:border-[#d4af37] transition-colors">
            <Upload className="w-8 h-8 text-[#8a8f98] mx-auto mb-2" />
            <p className="text-sm text-[#8a8f98]">点击或拖拽文件到此处</p>
            <p className="text-[11px] text-[#8a8f98] mt-1">支持 .xlsx / .xls 格式</p>
            <input
              type="file"
              multiple
              accept=".xlsx,.xls"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="hidden"
            />
          </label>

          {files.length > 0 && (
            <div className="space-y-1">
              {files.map((f, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 bg-[#0f0f11] rounded-[4px]">
                  <span className="text-xs text-white truncate">{f.name}</span>
                  <button onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-[#8a8f98] hover:text-red-400">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {result && (
            <div className="p-3 bg-[#0f0f11] border border-[#d4af37]/30 rounded-[4px]">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-[#d4af37] font-medium flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" />
                    生成成功
                  </div>
                  <div className="text-[11px] text-[#8a8f98] mt-1">{result.name}</div>
                </div>
                <button
                  onClick={handleDownload}
                  className="h-8 px-3 bg-[#d4af37] text-[#0a0a0c] text-xs font-semibold rounded-[4px] hover:brightness-110"
                >
                  下载
                </button>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white">关闭</button>
            <button
              onClick={handleUpload}
              disabled={files.length === 0 || loading}
              className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 disabled:opacity-40 flex items-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading ? '处理中...' : '开始合并'}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 批量改名 */
function RenameDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [folder, setFolder] = useState('');
  const [pattern, setPattern] = useState('');
  const [replacement, setReplacement] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ renamed: { old: string; new: string }[]; skipped: string[] } | null>(null);

  const handleSubmit = async () => {
    if (!folder.trim() || !pattern.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post<{ renamed_files: { old: string; new: string }[]; skipped_files: string[]; count: number }>(
        '/excel/rename',
        { folder, pattern, replacement }
      );
      if (res.success && res.data) {
        setResult({ renamed: res.data.renamed_files, skipped: res.data.skipped_files });
        toast.success(`重命名 ${res.data.count} 个文件`);
      } else {
        toast.error(res.message || '重命名失败');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-white">批量文件改名</DialogTitle>
          <DialogDescription className="text-[#8a8f98]">使用正则表达式批量重命名目录下的文件</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-4">
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">目录路径 *</label>
            <input
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder="例如：C:\\Users\\pm\\Documents\\交付物"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">匹配模式 (正则) *</label>
            <input
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              placeholder="例如：报告"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">替换为</label>
            <input
              value={replacement}
              onChange={(e) => setReplacement(e.target.value)}
              placeholder="例如：报表"
              className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>

          {result && (
            <div className="p-3 bg-[#0f0f11] border border-[#d4af37]/30 rounded-[4px] space-y-2">
              <div className="text-xs text-[#d4af37] font-medium flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                已重命名 {result.renamed.length} 个文件
              </div>
              {result.renamed.map((r, i) => (
                <div key={i} className="text-[11px] text-[#8a8f98]">
                  {r.old} → <span className="text-white">{r.new}</span>
                </div>
              ))}
              {result.skipped.length > 0 && (
                <div className="text-[11px] text-[#8a8f98]">
                  跳过: {result.skipped.join(', ')}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white">关闭</button>
            <button
              onClick={handleSubmit}
              disabled={!folder.trim() || !pattern.trim() || loading}
              className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 disabled:opacity-40 flex items-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading ? '处理中...' : '开始改名'}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export function ExcelToolbox() {
  const [activeDialog, setActiveDialog] = useState<string | null>(null);

  const handleModuleClick = (mod: ExcelModule) => {
    if (mod.status === 'planned') {
      toast.info('该功能尚在开发中');
      return;
    }
    setActiveDialog(mod.id);
  };

  return (
    <div className="p-6 overflow-auto h-[calc(100vh-56px)]">
      {/* Page Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-white mb-2">Excel 工具箱</h1>
        <p className="text-[13px] text-[#8a8f98]">
          项目管理常用 Excel 处理工具，覆盖合并、校验、比对、报表等场景
        </p>
      </div>

      {/* Security Notice */}
      <div className="mb-6 p-3 bg-[#1c1c1e] border border-[#2a2a2e] rounded-[4px] flex items-center gap-3">
        <Shield className="w-4 h-4 text-[#d4af37] flex-shrink-0" />
        <div className="flex-1 flex items-center gap-4">
          <span className="text-xs text-[#8a8f98]">文件处理在本地完成</span>
          <span className="text-[#2a2a2e]">|</span>
          <span className="text-xs text-[#8a8f98]">不上传至外部服务器</span>
        </div>
        <Lock className="w-3.5 h-3.5 text-[#8a8f98]" />
      </div>

      {/* Module Grid */}
      <div className="grid grid-cols-4 gap-4">
        {excelModules.map((mod) => {
          const IconComp = mod.icon;
          const StatusIcon = statusConfig[mod.status].icon;
          return (
            <button
              key={mod.id}
              onClick={() => handleModuleClick(mod)}
              disabled={mod.status === 'planned'}
              className="group relative bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-6 h-[160px] text-left hover:border-[#d4af37] hover:-translate-y-0.5 transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-[#2a2a2e] disabled:hover:translate-y-0"
            >
              <div className="absolute top-4 right-4 flex items-center gap-1">
                <StatusIcon className="w-3 h-3" style={{ color: statusConfig[mod.status].color }} />
                <span className="text-[10px] font-medium" style={{ color: statusConfig[mod.status].color }}>
                  {statusConfig[mod.status].label}
                </span>
              </div>
              <div className="w-10 h-10 bg-[#1c1c1e] rounded-[6px] flex items-center justify-center mb-4 group-hover:bg-[#d4af37] transition-colors duration-200">
                <IconComp className="w-5 h-5 text-[#d4af37] group-hover:text-[#0a0a0c] transition-colors duration-200" />
              </div>
              <ArrowUpRight className="absolute bottom-4 right-4 w-4 h-4 text-[#8a8f98] group-hover:text-[#d4af37] transition-colors" />
              <div className="absolute bottom-4 left-6 right-10">
                <h3 className="text-white text-sm font-semibold mb-1">{mod.name}</h3>
                <p className="text-[11px] text-[#8a8f98] leading-relaxed line-clamp-2">{mod.description}</p>
              </div>
            </button>
          );
        })}
      </div>

      {/* Dialogs */}
      <FileUploadDialog open={activeDialog === 'merge'} onClose={() => setActiveDialog(null)} title="Excel 多文件合并" mode="merge" />
      <FileUploadDialog open={activeDialog === 'merge-same'} onClose={() => setActiveDialog(null)} title="同结构表格合并" mode="merge-same" />
      <RenameDialog open={activeDialog === 'rename'} onClose={() => setActiveDialog(null)} />
    </div>
  );
}
