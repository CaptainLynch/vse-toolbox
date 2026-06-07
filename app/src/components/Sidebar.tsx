import { useAppStore } from '@/stores/appStore';
import {
  BarChart3,
  Mail,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Box,
  Wrench,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const menuItems = [
  { id: 'analytics', label: '数据分析看板', icon: BarChart3, category: 'analytics' },
  { id: 'toolbox', label: '工具矩阵', icon: Wrench, category: 'tool' },
  { id: 'feishu', label: '飞书邮件助手', icon: Mail, category: 'mail' },
];

export function Sidebar() {
  const { currentPage, setCurrentPage, isSidebarOpen, toggleSidebar } = useAppStore();
  const isSettingsActive = currentPage === 'settings';

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-screen bg-[#141416] border-r border-[#2a2a2e] flex flex-col z-50 transition-all duration-200',
        isSidebarOpen ? 'w-[240px]' : 'w-[64px]'
      )}
    >
      {/* Logo */}
      <div className="h-14 flex items-center px-4 border-b border-[#2a2a2e] relative">
        {isSidebarOpen ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-[3px]">
              <Box className="w-5 h-5 text-[#d4af37]" />
              <div className="flex flex-col gap-[2px]">
                <div className="w-[6px] h-[6px] bg-[#d4af37] rounded-[1px]" />
                <div className="w-[6px] h-[6px] bg-[#d4af37] rounded-[1px]" />
              </div>
            </div>
            <span className="text-[#d4af37] text-sm font-bold tracking-wide">VSE TOOLBOX</span>
          </div>
        ) : (
          <div className="flex items-center justify-center w-full">
            <Box className="w-6 h-6 text-[#d4af37]" />
          </div>
        )}
        <button
          onClick={toggleSidebar}
          className="absolute -right-3 top-1/2 -translate-y-1/2 w-6 h-6 bg-[#2a2a2e] border border-[#3a3a3e] rounded-full flex items-center justify-center hover:bg-[#3a3a3e] transition-colors"
        >
          {isSidebarOpen ? (
            <ChevronLeft className="w-3 h-3 text-[#8a8f98]" />
          ) : (
            <ChevronRight className="w-3 h-3 text-[#8a8f98]" />
          )}
        </button>
      </div>

      {/* Main nav */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentPage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setCurrentPage(item.id)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-[4px] text-sm font-medium transition-all duration-150 relative group',
                isActive
                  ? 'bg-[#1c1c1e] text-white'
                  : 'text-[#8a8f98] hover:text-white hover:bg-[#1c1c1e]'
              )}
            >
              {isActive && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-[#d4af37] rounded-r-full" />
              )}
              <Icon className={cn('w-[18px] h-[18px] flex-shrink-0', isActive && 'text-[#d4af37]')} />
              {isSidebarOpen && <span className="truncate">{item.label}</span>}
              {!isSidebarOpen && (
                <div className="absolute left-full ml-2 px-2 py-1 bg-[#2a2a2e] text-white text-xs rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50">
                  {item.label}
                </div>
              )}
            </button>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div className="p-3 border-t border-[#2a2a2e] space-y-1">
        <button
          onClick={() => setCurrentPage('settings')}
          className={cn(
            'w-full flex items-center gap-3 px-3 py-2.5 rounded-[4px] text-sm font-medium transition-all duration-150 relative group',
            isSettingsActive
              ? 'bg-[#1c1c1e] text-white'
              : 'text-[#8a8f98] hover:text-white hover:bg-[#1c1c1e]'
          )}
        >
          {isSettingsActive && (
            <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-[#d4af37] rounded-r-full" />
          )}
          <Settings className={cn('w-[18px] h-[18px] flex-shrink-0', isSettingsActive && 'text-[#d4af37]')} />
          {isSidebarOpen && <span>设置</span>}
          {!isSidebarOpen && (
            <div className="absolute left-full ml-2 px-2 py-1 bg-[#2a2a2e] text-white text-xs rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50">
              设置
            </div>
          )}
        </button>

        {/* User */}
        <div className={cn('flex items-center gap-2 mt-3 pt-3 border-t border-[#2a2a2e]', !isSidebarOpen && 'justify-center')}>          
          <div className="w-8 h-8 rounded-full bg-[#d4af37] flex items-center justify-center flex-shrink-0">
            <span className="text-[#0a0a0c] text-xs font-bold">VS</span>
          </div>
          {isSidebarOpen && (
            <div className="flex-1 min-w-0">
              <div className="text-white text-sm font-medium truncate">项目经理</div>
              <div className="text-[#8a8f98] text-xs truncate">pm@company.com</div>
            </div>
          )}
          <button className="p-1 text-[#8a8f98] hover:text-white transition-colors flex-shrink-0">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
