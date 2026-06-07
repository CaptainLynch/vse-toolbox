import { useAppStore } from '@/stores/appStore';
import { Search, Bell, Settings, ChevronRight } from 'lucide-react';

const pageTitles: Record<string, { title: string; breadcrumb: string }> = {
  dashboard: { title: '造车问题追踪', breadcrumb: '车身钣金 / 外板件' },
  excel: { title: 'Excel 工具箱', breadcrumb: '数据处理 / 全部模块' },
  toolbox: { title: '工具矩阵', breadcrumb: '效率工具 / 全部' },
  analytics: { title: '数据分析看板', breadcrumb: '项目健康度 / 总览' },
  feishu: { title: '飞书邮件助手', breadcrumb: '邮件管理 / 待办生成' },
  settings: { title: '设置', breadcrumb: '系统 / 配置' },
};

export function TopBar() {
  const { currentPage, setCurrentPage } = useAppStore();
  const pageInfo = pageTitles[currentPage] || { title: '', breadcrumb: '' };

  return (
    <header className="sticky top-0 z-40 h-14 flex items-center justify-between px-6 bg-[#0a0a0c]/80 backdrop-blur-md border-b border-[#2a2a2e]">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2">
        <span className="text-white text-sm font-medium">{pageInfo.title}</span>
        <ChevronRight className="w-3.5 h-3.5 text-[#8a8f98]" />
        <span className="text-[#8a8f98] text-xs">{pageInfo.breadcrumb}</span>
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#8a8f98]" />
          <input
            type="text"
            placeholder="全局搜索..."
            className="w-[200px] h-8 pl-9 pr-3 bg-[#141416] border border-[#2a2a2e] rounded-[4px] text-xs text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37] transition-colors"
          />
        </div>
        <button className="relative p-2 text-[#8a8f98] hover:text-white transition-colors">
          <Bell className="w-[18px] h-[18px]" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
        </button>
        <button
          onClick={() => setCurrentPage('settings')}
          className="p-2 text-[#8a8f98] hover:text-white transition-colors"
        >
          <Settings className="w-[18px] h-[18px]" />
        </button>
      </div>
    </header>
  );
}
