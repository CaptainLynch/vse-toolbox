import { useState, useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { cn } from '@/lib/utils';
import {
  Mail,
  MailOpen,
  Send,
  Inbox,
  Star,
  Trash2,
  Search,
  RefreshCw,
  Paperclip,
  Clock,
  CheckCircle2,
  AlertCircle,
  Globe,
  Wifi,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';

const mailCategories = [
  { id: 'all', label: '全部邮件', icon: Inbox },
  { id: 'unread', label: '未读', icon: Mail },
  { id: 'starred', label: '星标', icon: Star },
  { id: 'sent', label: '已发送', icon: Send },
  { id: 'trash', label: '回收站', icon: Trash2 },
];

export function FeishuMail() {
  const {
    mails, todos,
    fetchMails, syncMails, fetchTodos, toggleTodo,
  } = useAppStore();

  const [activeCategory, setActiveCategory] = useState('all');
  const [selectedMail, setSelectedMail] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  // 加载数据
  useEffect(() => {
    fetchMails();
    fetchTodos();
  }, []);

  // 筛选
  const filteredMails = activeCategory === 'all'
    ? mails
    : activeCategory === 'unread'
    ? mails.filter((m) => !m.isRead)
    : activeCategory === 'starred'
    ? mails.filter((m) => m.isStarred)
    : mails;

  const categoryCounts = {
    all: mails.length,
    unread: mails.filter((m) => !m.isRead).length,
    starred: mails.filter((m) => m.isStarred).length,
    sent: 0,
    trash: 0,
  };

  const currentMail = mails.find((m) => m.id === selectedMail);

  // 同步
  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await syncMails();
      if (res) {
        toast.success(`同步完成：共 ${res.synced} 封，${res.fresh} 封新增${res.demo ? ' (Demo)' : ''}`);
      } else {
        toast.error('同步失败，请检查网络连接');
      }
    } finally {
      setSyncing(false);
    }
  };

  // 切换待办
  const handleToggle = async (id: string) => {
    const ok = await toggleTodo(id);
    if (!ok) toast.error('操作失败');
  };

  return (
    <div className="flex h-[calc(100vh-56px)] pt-8">
      {/* Network Status Bar */}
      <div className="absolute top-14 left-0 right-0 h-8 bg-[#141416] border-b border-[#2a2a2e] flex items-center px-4 gap-4 z-30">
        <div className="flex items-center gap-1.5">
          <Wifi className="w-3 h-3 text-green-400" />
          <span className="text-[11px] text-green-400">内网已连接</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Globe className="w-3 h-3 text-[#ff9f4d]" />
          <span className="text-[11px] text-[#ff9f4d]">外网受限（仅 Edge 白名单）</span>
        </div>
        <div className="flex-1" />
        <span className="text-[11px] text-[#8a8f98]">
          飞书域名 open.feishu.cn 需确认在白名单内
        </span>
      </div>

      {/* Left: Mail List */}
      <div className="w-[400px] border-r border-[#2a2a2e] bg-[#141416] flex flex-col">
        {/* Category Tabs */}
        <div className="flex items-center gap-1 p-3 border-b border-[#2a2a2e]">
          {mailCategories.map((cat) => {
            const Icon = cat.icon;
            const count = categoryCounts[cat.id as keyof typeof categoryCounts];
            return (
              <button
                key={cat.id}
                onClick={() => setActiveCategory(cat.id)}
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1.5 rounded-[4px] text-[11px] font-medium transition-all',
                  activeCategory === cat.id
                    ? 'bg-[#1c1c1e] text-white'
                    : 'text-[#8a8f98] hover:text-white hover:bg-[#1c1c1e]'
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                {cat.label}
                {count > 0 && (
                  <span className={cn(
                    'ml-0.5 px-1 py-0 rounded-full text-[10px] font-bold',
                    activeCategory === cat.id ? 'bg-[#d4af37] text-[#0a0a0c]' : 'bg-[#2a2a2e] text-[#8a8f98]'
                  )}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Search + Sync */}
        <div className="px-3 py-2 border-b border-[#2a2a2e] flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#8a8f98]" />
            <input
              type="text"
              placeholder="搜索邮件..."
              className="w-full h-8 pl-9 pr-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-xs text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
            />
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="h-8 px-3 bg-[#d4af37] text-[#0a0a0c] text-xs font-semibold rounded-[4px] hover:brightness-110 disabled:opacity-40 flex items-center gap-1.5"
          >
            {syncing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            同步
          </button>
        </div>

        {/* Mail List */}
        <div className="flex-1 overflow-auto">
          {filteredMails.map((mail) => (
            <button
              key={mail.id}
              onClick={() => setSelectedMail(mail.id)}
              className={cn(
                'w-full text-left px-4 py-3 border-b border-[#1e1e20] hover:bg-[#161618] transition-colors',
                selectedMail === mail.id && 'bg-[#161618] border-l-[3px] border-l-[#d4af37]',
                !mail.isRead && selectedMail !== mail.id && 'border-l-[3px] border-l-[#d4af37]'
              )}
            >
              <div className="flex items-start justify-between mb-1">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {!mail.isRead && <div className="w-1.5 h-1.5 rounded-full bg-[#d4af37] flex-shrink-0" />}
                  <span className={cn('text-xs truncate', !mail.isRead ? 'text-white font-semibold' : 'text-[#8a8f98]')}>
                    {mail.sender}
                  </span>
                </div>
                <span className="text-[10px] text-[#8a8f98] flex-shrink-0 ml-2">{mail.date}</span>
              </div>
              <div className={cn('text-xs mb-1 truncate', !mail.isRead ? 'text-white font-medium' : 'text-[#8a8f98]')}>
                {mail.subject}
              </div>
              <div className="text-[11px] text-[#8a8f98] truncate">{mail.preview}</div>
              <div className="flex items-center gap-2 mt-1.5">
                {mail.isStarred && <Star className="w-3 h-3 text-[#d4af37] fill-[#d4af37]" />}
                {mail.hasAttachment && <Paperclip className="w-3 h-3 text-[#8a8f98]" />}
                {mail.category && (
                  <span className="px-1.5 py-0.5 bg-[#1c1c1e] rounded-[3px] text-[10px] text-[#8a8f98]">
                    {mail.category}
                  </span>
                )}
              </div>
            </button>
          ))}
          {filteredMails.length === 0 && (
            <div className="p-8 text-center text-[#8a8f98] text-sm">
              暂无邮件
            </div>
          )}
        </div>
      </div>

      {/* Middle: Mail Detail */}
      <div className="flex-1 border-r border-[#2a2a2e] bg-[#0a0a0c] overflow-auto">
        {currentMail ? (
          <div className="p-6">
            <div className="flex items-start justify-between mb-6">
              <div>
                <h2 className="text-lg font-semibold text-white mb-2">{currentMail.subject}</h2>
                <div className="flex items-center gap-3 text-xs text-[#8a8f98]">
                  <span className="text-white font-medium">{currentMail.sender}</span>
                  <span>{currentMail.date}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="p-2 text-[#8a8f98] hover:text-[#d4af37] transition-colors">
                  <Star className={cn('w-4 h-4', currentMail.isStarred && 'fill-[#d4af37] text-[#d4af37]')} />
                </button>
                <button className="p-2 text-[#8a8f98] hover:text-white transition-colors">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5 mb-6">
              <p className="text-[13px] text-[#8a8f98] leading-relaxed whitespace-pre-line">
                {currentMail.preview}
                {'\n\n'}此邮件来自飞书系统，如需查看更多详情，请登录飞书邮箱。
                {currentMail.hasAttachment && '\n\n【附件】相关文件'}
              </p>
            </div>

            {currentMail.hasAttachment && (
              <div className="mb-6">
                <h3 className="text-xs text-[#8a8f98] font-medium mb-2 tracking-[0.5px] uppercase">附件</h3>
                <div className="flex items-center gap-3 p-3 bg-[#141416] border border-[#2a2a2e] rounded-[4px]">
                  <div className="w-10 h-10 bg-[#1c1c1e] rounded-[4px] flex items-center justify-center">
                    <Paperclip className="w-4 h-4 text-[#d4af37]" />
                  </div>
                  <div className="flex-1">
                    <div className="text-xs text-white">相关文件</div>
                  </div>
                  <button className="px-3 py-1.5 text-[11px] text-[#d4af37] border border-[#d4af37] rounded-[4px] hover:bg-[#d4af37] hover:text-[#0a0a0c] transition-all">
                    下载
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-[#8a8f98]">
            <MailOpen className="w-12 h-12 mb-4 opacity-30" />
            <p className="text-sm">选择一封邮件查看详情</p>
          </div>
        )}
      </div>

      {/* Right: Todo Panel */}
      <div className="w-[300px] bg-[#141416] flex flex-col">
        <div className="p-4 border-b border-[#2a2a2e]">
          <div className="flex items-center justify-between">
            <h3 className="text-white text-sm font-semibold flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-[#d4af37]" />
              待办任务
            </h3>
            <span className="text-[11px] text-[#8a8f98]">
              {todos.filter((t) => !t.completed).length} 待完成
            </span>
          </div>
          <p className="text-[11px] text-[#8a8f98] mt-1">根据邮件自动生成</p>
        </div>

        <div className="flex-1 overflow-auto p-3 space-y-2">
          {todos.map((todo) => (
            <div
              key={todo.id}
              className={cn(
                'p-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] hover:bg-[#161618] transition-colors',
                todo.completed && 'opacity-50'
              )}
            >
              <div className="flex items-start gap-2">
                <button
                  onClick={() => handleToggle(todo.id)}
                  className={cn(
                    'mt-0.5 w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 transition-all',
                    todo.completed
                      ? 'bg-[#d4af37] border-[#d4af37]'
                      : 'border-[#8a8f98] hover:border-[#d4af37]'
                  )}
                >
                  {todo.completed && <CheckCircle2 className="w-3 h-3 text-[#0a0a0c]" />}
                </button>
                <div className="flex-1 min-w-0">
                  <p className={cn('text-xs text-white leading-relaxed', todo.completed && 'line-through text-[#8a8f98]')}>
                    {todo.content}
                  </p>
                  <div className="flex items-center gap-2 mt-1.5">
                    <span className="text-[10px] text-[#8a8f98]">{todo.source}</span>
                    {todo.deadline && (
                      <span className="flex items-center gap-0.5 text-[10px] text-[#d4af37]">
                        <Clock className="w-2.5 h-2.5" />
                        {todo.deadline}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
          {todos.length === 0 && (
            <div className="p-6 text-center text-[#8a8f98] text-sm">暂无待办</div>
          )}
        </div>

        {/* AI Suggestion */}
        <div className="p-4 border-t border-[#2a2a2e]">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="w-3.5 h-3.5 text-[#d4af37]" />
            <span className="text-[11px] text-[#d4af37] font-medium">AI 智能提醒</span>
          </div>
          <p className="text-[11px] text-[#8a8f98] leading-relaxed">
            基于邮件内容自动提取待办任务，点击同步按钮更新邮件列表。
          </p>
        </div>
      </div>
    </div>
  );
}
