import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { cn } from '@/lib/utils';
import { api } from '@/services/api';
import {
  FileSpreadsheet,
  FileEdit,
  Globe,
  Presentation,
  FileStack,
  Mail,
  Bot,
  AlertTriangle,
  ListChecks,
  Database,
  Sparkles,
  Newspaper,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  FlaskConical,
  Lock,
  Shield,
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
// Icon map
// ---------------------------------------------------------------------------

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  FileSpreadsheet,
  FileEdit,
  Globe,
  Presentation,
  FileStack,
  Mail,
  Bot,
  AlertTriangle,
  ListChecks,
  Database,
  Sparkles,
  Newspaper,
};

const statusConfig = {
  ready: { icon: CheckCircle2, label: '可用', color: '#4ade80' },
  planned: { icon: Clock, label: '规划中', color: '#8a8f98' },
  beta: { icon: FlaskConical, label: '测试中', color: '#d4af37' },
};

const categories = ['全部', '数据处理', '数据采集', '报告生成', '协作工具', '任务管理', '智能分析'];

// ---------------------------------------------------------------------------
// 工具对话框组件
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
          {/* Drop zone */}
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

          {/* File list */}
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

          {/* Result */}
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

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white">
              关闭
            </button>
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

/** PPT 生成 */
function PPTDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [type, setType] = useState<'weekly' | 'deliverable'>('weekly');
  const [weekStart, setWeekStart] = useState('');
  const [projectName, setProjectName] = useState('');
  const [deliverableName, setDeliverableName] = useState('');
  const [responsible, setResponsible] = useState('');
  const [loading, setLoading] = useState(false);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      let res;
      if (type === 'weekly') {
        res = await api.post<{ file_path: string; file_name: string }>('/ppt/weekly', {
          week_start: weekStart || undefined,
          project_name: projectName || undefined,
        });
      } else {
        res = await api.post<{ file_path: string; file_name: string }>('/ppt/deliverable', {
          deliverable_name: deliverableName,
          responsible: responsible || undefined,
        });
      }
      if (res.success && res.data) {
        api.download(res.data.file_path);
        toast.success(`已生成 ${res.data.file_name}`);
        onClose();
      } else {
        toast.error(res.message || '生成失败');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-white">生成 PPT</DialogTitle>
          <DialogDescription className="text-[#8a8f98]">选择模板并填写参数，自动生成 PowerPoint</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-4">
          {/* Type selector */}
          <div className="flex gap-2">
            <button
              onClick={() => setType('weekly')}
              className={cn(
                'flex-1 h-10 rounded-[4px] text-sm font-medium transition-all',
                type === 'weekly' ? 'bg-[#d4af37] text-[#0a0a0c]' : 'bg-[#1c1c1e] text-[#8a8f98] border border-[#2a2a2e]'
              )}
            >
              周报 PPT
            </button>
            <button
              onClick={() => setType('deliverable')}
              className={cn(
                'flex-1 h-10 rounded-[4px] text-sm font-medium transition-all',
                type === 'deliverable' ? 'bg-[#d4af37] text-[#0a0a0c]' : 'bg-[#1c1c1e] text-[#8a8f98] border border-[#2a2a2e]'
              )}
            >
              交付物 PPT
            </button>
          </div>

          {type === 'weekly' ? (
            <>
              <div>
                <label className="text-xs text-[#8a8f98] mb-1 block">周报起始日期</label>
                <input
                  type="date"
                  value={weekStart}
                  onChange={(e) => setWeekStart(e.target.value)}
                  className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white focus:outline-none focus:border-[#d4af37]"
                />
              </div>
              <div>
                <label className="text-xs text-[#8a8f98] mb-1 block">项目名称</label>
                <input
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="可选"
                  className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
                />
              </div>
            </>
          ) : (
            <>
              <div>
                <label className="text-xs text-[#8a8f98] mb-1 block">交付物名称 *</label>
                <input
                  value={deliverableName}
                  onChange={(e) => setDeliverableName(e.target.value)}
                  placeholder="例如：车身钣金 DV 试验报告"
                  className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
                />
              </div>
              <div>
                <label className="text-xs text-[#8a8f98] mb-1 block">负责人</label>
                <input
                  value={responsible}
                  onChange={(e) => setResponsible(e.target.value)}
                  placeholder="可选"
                  className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
                />
              </div>
            </>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white">关闭</button>
            <button
              onClick={handleGenerate}
              disabled={(type === 'deliverable' && !deliverableName.trim()) || loading}
              className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 disabled:opacity-40 flex items-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading ? '生成中...' : '生成 PPT'}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 网页爬取 */
function CrawlerDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [url, setUrl] = useState('');
  const [xpath, setXpath] = useState('');
  const [mode, setMode] = useState<'fetch' | 'table'>('fetch');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ title?: string; content?: string; headers?: string[]; rows?: string[][]; rowCount?: number } | null>(null);

  const handleFetch = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      if (mode === 'fetch') {
        const res = await api.post<{ url: string; title: string; content: string; browser_used: string }>('/crawler/fetch', { url });
        if (res.success && res.data) {
          setResult({ title: res.data.title, content: res.data.content });
          toast.success('抓取成功');
        } else {
          toast.error(res.message || '抓取失败');
        }
      } else {
        const body: Record<string, string> = { url };
        if (xpath.trim()) body.xpath = xpath;
        const res = await api.post<{ headers: string[]; rows: string[][]; row_count: number }>('/crawler/table', body);
        if (res.success && res.data) {
          setResult({ headers: res.data.headers, rows: res.data.rows, rowCount: res.data.row_count });
          toast.success(`提取 ${res.data.row_count} 行数据`);
        } else {
          toast.error(res.message || '表格提取失败');
        }
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="bg-[#141416] border border-[#2a2a2e] text-white max-w-2xl max-h-[80vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="text-white">网页数据爬取</DialogTitle>
          <DialogDescription className="text-[#8a8f98]">通过浏览器自动抓取页面内容或表格</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-4">
          <div className="flex gap-2">
            <button onClick={() => setMode('fetch')} className={cn('flex-1 h-9 rounded-[4px] text-sm font-medium', mode === 'fetch' ? 'bg-[#d4af37] text-[#0a0a0c]' : 'bg-[#1c1c1e] text-[#8a8f98] border border-[#2a2a2e]')}>抓取页面</button>
            <button onClick={() => setMode('table')} className={cn('flex-1 h-9 rounded-[4px] text-sm font-medium', mode === 'table' ? 'bg-[#d4af37] text-[#0a0a0c]' : 'bg-[#1c1c1e] text-[#8a8f98] border border-[#2a2a2e]')}>提取表格</button>
          </div>
          <div>
            <label className="text-xs text-[#8a8f98] mb-1 block">URL *</label>
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]" />
          </div>
          {mode === 'table' && (
            <div>
              <label className="text-xs text-[#8a8f98] mb-1 block">XPath（可选）</label>
              <input value={xpath} onChange={(e) => setXpath(e.target.value)} placeholder="//table" className="w-full h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]" />
            </div>
          )}

          {result && mode === 'fetch' && (
            <div className="p-4 bg-[#0f0f11] border border-[#d4af37]/30 rounded-[4px] space-y-2 max-h-60 overflow-auto">
              {result.title && <div className="text-sm text-white font-medium">{result.title}</div>}
              <div className="text-xs text-[#8a8f98] whitespace-pre-wrap">{result.content}</div>
            </div>
          )}

          {result && mode === 'table' && result.headers && (
            <div className="p-4 bg-[#0f0f11] border border-[#d4af37]/30 rounded-[4px] overflow-auto max-h-60">
              <div className="text-xs text-[#8a8f98] mb-2">共 {result.rowCount} 行</div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[#2a2a2e]">
                    {result.headers.map((h, i) => <th key={i} className="text-left px-2 py-1 text-[#d4af37]">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {result.rows?.slice(0, 20).map((row, i) => (
                    <tr key={i} className="border-b border-[#1e1e20]">
                      {row.map((cell, j) => <td key={j} className="px-2 py-1 text-[#8a8f98]">{cell}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="h-9 px-4 text-sm text-[#8a8f98] hover:text-white">关闭</button>
            <button onClick={handleFetch} disabled={!url.trim() || loading} className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 disabled:opacity-40 flex items-center gap-2">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading ? '抓取中...' : '开始抓取'}
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

export function Toolbox() {
  const { tools, syncMails } = useAppStore();
  const [activeCategory, setActiveCategory] = useState('全部');
  const [activeDialog, setActiveDialog] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const filteredTools = activeCategory === '全部'
    ? tools
    : tools.filter((t) => t.category === activeCategory);

  const handleToolClick = (toolId: string) => {
    switch (toolId) {
      case 'excel-merge':
        setActiveDialog('excel-merge');
        break;
      case 'excel-same':
        setActiveDialog('excel-same');
        break;
      case 'excel-rename':
        setActiveDialog('excel-rename');
        break;
      case 'ppt-weekly':
      case 'ppt-deliverable':
        setActiveDialog('ppt');
        break;
      case 'web-crawler':
        setActiveDialog('crawler');
        break;
      case 'feishu-mail':
        setSyncing(true);
        syncMails().then((res) => {
          setSyncing(false);
          if (res) toast.success(`同步完成：共 ${res.synced} 封邮件，${res.fresh} 封新增`);
          else toast.error('同步失败');
        });
        break;
      default:
        toast.info('该功能尚在开发中');
    }
  };

  return (
    <div className="p-6 overflow-auto h-[calc(100vh-56px)]">
      {/* Page Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-white mb-2">效率工具箱</h1>
        <p className="text-[13px] text-[#8a8f98]">
          集成 Excel 处理、数据爬取、报告生成、飞书协作等模块，提升项目管理效率
        </p>
      </div>

      {/* Security Notice */}
      <div className="mb-6 p-3 bg-[#1c1c1e] border border-[#2a2a2e] rounded-[4px] flex items-center gap-3">
        <Shield className="w-4 h-4 text-[#d4af37] flex-shrink-0" />
        <div className="flex-1 flex items-center gap-4">
          <span className="text-xs text-[#8a8f98]">文件自动加密已启用</span>
          <span className="text-[#2a2a2e]">|</span>
          <span className="text-xs text-[#8a8f98]">外网访问通过 Edge 代理</span>
          <span className="text-[#2a2a2e]">|</span>
          <span className="text-xs text-[#8a8f98]">白名单域名控制中</span>
        </div>
        <Lock className="w-3.5 h-3.5 text-[#8a8f98]" />
      </div>

      {/* Category Filter */}
      <div className="flex items-center gap-2 mb-6 flex-wrap">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn(
              'px-3 py-1.5 rounded-[4px] text-xs font-medium transition-all duration-150',
              activeCategory === cat
                ? 'bg-[#d4af37] text-[#0a0a0c]'
                : 'bg-[#141416] text-[#8a8f98] border border-[#2a2a2e] hover:border-[#8a8f98] hover:text-white'
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Tool Grid */}
      <div className="grid grid-cols-4 gap-4">
        {filteredTools.map((tool) => {
          const IconComp = iconMap[tool.icon] || FileSpreadsheet;
          const StatusIcon = statusConfig[tool.status].icon;
          return (
            <button
              key={tool.id}
              onClick={() => handleToolClick(tool.id)}
              disabled={tool.status === 'planned'}
              className="group relative bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-6 h-[160px] text-left hover:border-[#d4af37] hover:-translate-y-0.5 transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-[#2a2a2e] disabled:hover:translate-y-0"
            >
              <div className="absolute top-4 right-4 flex items-center gap-1">
                <StatusIcon className="w-3 h-3" style={{ color: statusConfig[tool.status].color }} />
                <span className="text-[10px] font-medium" style={{ color: statusConfig[tool.status].color }}>
                  {statusConfig[tool.status].label}
                </span>
              </div>
              <div className="w-10 h-10 bg-[#1c1c1e] rounded-[6px] flex items-center justify-center mb-4 group-hover:bg-[#d4af37] transition-colors duration-200">
                <IconComp className="w-5 h-5 text-[#d4af37] group-hover:text-[#0a0a0c] transition-colors duration-200" />
              </div>
              <ArrowUpRight className="absolute bottom-4 right-4 w-4 h-4 text-[#8a8f98] group-hover:text-[#d4af37] transition-colors" />
              <div className="absolute bottom-4 left-6 right-10">
                <h3 className="text-white text-sm font-semibold mb-1">{tool.name}</h3>
                <p className="text-[11px] text-[#8a8f98] leading-relaxed line-clamp-2">{tool.description}</p>
              </div>
            </button>
          );
        })}
      </div>

      {/* 同步中提示 */}
      {syncing && (
        <div className="fixed bottom-6 right-6 bg-[#141416] border border-[#d4af37]/30 rounded-[4px] px-4 py-3 flex items-center gap-2 shadow-lg z-50">
          <Loader2 className="w-4 h-4 text-[#d4af37] animate-spin" />
          <span className="text-sm text-white">正在同步飞书邮件...</span>
        </div>
      )}

      {/* Dialogs */}
      <FileUploadDialog open={activeDialog === 'excel-merge'} onClose={() => setActiveDialog(null)} title="Excel 多文件合并" mode="merge" />
      <FileUploadDialog open={activeDialog === 'excel-same'} onClose={() => setActiveDialog(null)} title="同结构表格合并" mode="merge-same" />
      <RenameDialog open={activeDialog === 'excel-rename'} onClose={() => setActiveDialog(null)} />
      <PPTDialog open={activeDialog === 'ppt'} onClose={() => setActiveDialog(null)} />
      <CrawlerDialog open={activeDialog === 'crawler'} onClose={() => setActiveDialog(null)} />
    </div>
  );
}
