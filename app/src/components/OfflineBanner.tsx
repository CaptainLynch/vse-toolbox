import { WifiOff } from 'lucide-react';

export function OfflineBanner() {
  return (
    <div className="fixed bottom-0 left-0 right-0 h-10 bg-[#3b1515] border-t border-[#ff4d4d]/30 flex items-center justify-center gap-2 z-50">
      <WifiOff className="w-4 h-4 text-[#ff4d4d]" />
      <span className="text-xs text-[#ff4d4d] font-medium">
        后端服务不可达，当前显示的是模拟数据
      </span>
    </div>
  );
}
