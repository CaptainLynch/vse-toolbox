import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { LoadingScreen } from '@/components/LoadingScreen';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { OfflineBanner } from '@/components/OfflineBanner';
import { AnalyticsLayout } from '@/pages/AnalyticsLayout';
import { ExcelToolbox } from '@/pages/ExcelToolbox';
import { Toolbox } from '@/pages/Toolbox';
import { FeishuMail } from '@/pages/FeishuMail';
import { Settings } from '@/pages/Settings';
import { cn } from '@/lib/utils';
import { Toaster } from 'sonner';

function App() {
  const { isLoading, setIsLoading, isOnline, setOnline, currentPage, isSidebarOpen } = useAppStore();

  // 启动动画 + 后端健康检查
  useEffect(() => {
    const timer = setTimeout(() => {
      setIsLoading(false);
    }, 1800);
    return () => clearTimeout(timer);
  }, []);

  // 首次加载时检查后端
  useEffect(() => {
    if (!isLoading) {
      import('@/services/api').then(({ api }) => {
        api.healthCheck().then((ok) => setOnline(ok));
      });
    }
  }, [isLoading]);

          const renderPage = () => {
    switch (currentPage) {
      case 'analytics':
        return <AnalyticsLayout />;
      case 'excel':
        return <ExcelToolbox />;
      case 'toolbox':
        return <Toolbox />;
      case 'feishu':
        return <FeishuMail />;
      case 'settings':
        return <Settings />;
      default:
        return <AnalyticsLayout />;
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0c]">
      {isLoading && <LoadingScreen />}

      {!isLoading && (
        <div className="flex">
          <Sidebar />
          <main
            className={cn(
              'flex-1 min-h-screen transition-all duration-200',
              isSidebarOpen ? 'ml-[240px]' : 'ml-[64px]'
            )}
          >
            <TopBar />
            {renderPage()}
          </main>
        </div>
      )}

      {!isOnline && !isLoading && <OfflineBanner />}

      <Toaster
        theme="dark"
        position="top-right"
        toastOptions={{
          style: {
            background: '#141416',
            border: '1px solid #2a2a2e',
            color: '#ffffff',
            fontSize: '13px',
          },
        }}
      />
    </div>
  );
}

export default App;