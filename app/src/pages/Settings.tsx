import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/stores/appStore';
import {
  Shield,
  Lock,
  Globe,
  FileKey,
  AlertTriangle,
  CheckCircle2,
  Info,
  Save,
  Server,
  Chrome,
  FileSpreadsheet,
  Presentation,
  Monitor,
  User,
  FolderOpen,
} from 'lucide-react';

interface SecurityConfig {
  fileEncryption: boolean;
  autoBackup: boolean;
  offlineMode: boolean;
  networkCheck: boolean;
  dataScope: 'local' | 'share';
}

const defaultConfig: SecurityConfig = {
  fileEncryption: true,
  autoBackup: true,
  offlineMode: false,
  networkCheck: true,
  dataScope: 'local',
};

const toolStatusList = [
  {
    name: 'Excel 批量合并',
    icon: FileSpreadsheet,
    status: 'ready' as const,
    encryption: true,
    network: false,
    gac: false,
    desc: '纯本地文件操作，无管理员权限需求',
  },
  {
    name: '内网数据爬取',
    icon: Globe,
    status: 'ready' as const,
    encryption: false,
    network: true,
    gac: true,
    desc: '需自带 Chrome/Edge WebDriver，不写入系统目录',
  },
  {
    name: '周报 PPT 生成',
    icon: Presentation,
    status: 'ready' as const,
    encryption: true,
    network: false,
    gac: false,
    desc: '纯本地文件操作，模板内嵌到工具包中',
  },
  {
    name: '飞书邮件助手',
    icon: Globe,
    status: 'planned' as const,
    encryption: false,
    network: true,
    gac: false,
    desc: '通过 Edge 浏览器代理访问飞书白名单域名',
  },
];

const browserPolicy = [
  {
    target: '内网系统（EWO、OTS）',
    browser: 'Google Chrome',
    driver: 'chromedriver.exe',
    reason: '内网应用未在 Edge 白名单中',
  },
  {
    target: '飞书表格 / 飞书 API',
    browser: 'Microsoft Edge',
    driver: 'msedgedriver.exe',
    reason: 'Edge 已通过数篷科技白名单授权',
  },
];

export function Settings() {
  const [config, setConfig] = useState<SecurityConfig>(defaultConfig);
  const [activeTab, setActiveTab] = useState<'security' | 'network' | 'tools' | 'deploy' | 'deliverable'>('security');
  const [saved, setSaved] = useState(false);
  const { settings, fetchSettings, updateSetting } = useAppStore();

  // Deliverable folder paths (controlled inputs)
  const [folderPaths, setFolderPaths] = useState({
    issues_folder: '',
    ewo_folder: '',
    tir_folder: '',
  });

  useEffect(() => { fetchSettings(); }, []);

  // Sync folder paths when settings load from store
  useEffect(() => {
    setFolderPaths({
      issues_folder: settings.issues_folder ?? '',
      ewo_folder: settings.ewo_folder ?? '',
      tir_folder: settings.tir_folder ?? '',
    });
  }, [settings]);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleDeliverableSave = async () => {
    let ok = true;
    for (const [key, value] of Object.entries(folderPaths)) {
      const success = await updateSetting(key, value);
      if (!success) ok = false;
    }
    // Re-fetch to sync local state with store (handles partial failure)
    await fetchSettings();
    if (ok) {
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }
  };

  const tabs = [
    { id: 'security' as const, label: '文件安全', icon: Lock },
    { id: 'network' as const, label: '网络环境', icon: Globe },
    { id: 'tools' as const, label: '工具适配', icon: Shield },
    { id: 'deploy' as const, label: '部署要求', icon: Monitor },
    { id: 'deliverable' as const, label: '交付物配置', icon: FolderOpen },
  ];

  return (
    <div className="p-6 overflow-auto h-[calc(100vh-56px)]">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-white mb-2">环境设置</h1>
        <p className="text-[13px] text-[#8a8f98]">
          配置企业安全环境下的工具箱运行参数
        </p>
      </div>

      {/* Enterprise Notice Banner */}
      <div className="mb-6 p-4 bg-[#3b3015] border border-[#d4af37]/30 rounded-[4px] flex items-start gap-3">
        <Shield className="w-5 h-5 text-[#d4af37] flex-shrink-0 mt-0.5" />
        <div>
          <h3 className="text-sm font-semibold text-[#d4af37] mb-1">企业安全环境约束汇总</h3>
          <div className="text-xs text-[#d4af37]/80 leading-relaxed space-y-1">
            <p>1. 文件自动加密：所有生成文件自动加密，非公司电脑无法打开</p>
            <p>2. 外网白名单：仅白名单应用（Edge）和域名可连接外网，Chrome 无外网权限</p>
            <p>3. 浏览器分离：内网系统走 Chrome，飞书走 Edge</p>
            <p>4. GAC 权限：工具箱需以绿色便携模式运行，不触发管理员权限申请</p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 mb-6">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-[4px] text-sm font-medium transition-all',
                activeTab === tab.id
                  ? 'bg-[#d4af37] text-[#0a0a0c]'
                  : 'bg-[#141416] text-[#8a8f98] border border-[#2a2a2e] hover:border-[#8a8f98]'
              )}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Security Tab */}
      {activeTab === 'security' && (
        <div className="space-y-4 max-w-[720px]">
          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <FileKey className="w-4 h-4 text-[#d4af37]" />
              <h3 className="text-white text-sm font-semibold">文件加密策略</h3>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between py-3 border-b border-[#1e1e20]">
                <div>
                  <div className="text-sm text-white mb-0.5">生成文件自动加密</div>
                  <div className="text-xs text-[#8a8f98]">
                    由公司加密系统自动处理，工具箱无需干预
                  </div>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-1 bg-[#3b3015] rounded-[4px]">
                  <CheckCircle2 className="w-3 h-3 text-[#d4af37]" />
                  <span className="text-[10px] text-[#d4af37] font-medium">系统级已启用</span>
                </div>
              </div>

              <div className="flex items-center justify-between py-3 border-b border-[#1e1e20]">
                <div>
                  <div className="text-sm text-white mb-0.5">自动备份到本地</div>
                  <div className="text-xs text-[#8a8f98]">
                    处理前自动备份原始文件到 ./backup 目录（仅用户目录）
                  </div>
                </div>
                <button
                  onClick={() => setConfig({ ...config, autoBackup: !config.autoBackup })}
                  className={cn(
                    'w-11 h-6 rounded-full transition-colors relative',
                    config.autoBackup ? 'bg-[#d4af37]' : 'bg-[#2a2a2e]'
                  )}
                >
                  <div
                    className={cn(
                      'absolute top-1 w-4 h-4 rounded-full bg-white transition-transform',
                      config.autoBackup ? 'left-6' : 'left-1'
                    )}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between py-3">
                <div>
                  <div className="text-sm text-white mb-0.5">数据作用域</div>
                  <div className="text-xs text-[#8a8f98]">
                    控制处理后的数据是否可在团队内共享
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setConfig({ ...config, dataScope: 'local' })}
                    className={cn(
                      'px-3 py-1.5 rounded-[4px] text-xs font-medium transition-all',
                      config.dataScope === 'local'
                        ? 'bg-[#d4af37] text-[#0a0a0c]'
                        : 'bg-[#1c1c1e] text-[#8a8f98] border border-[#2a2a2e]'
                    )}
                  >
                    仅本机
                  </button>
                  <button
                    onClick={() => setConfig({ ...config, dataScope: 'share' })}
                    className={cn(
                      'px-3 py-1.5 rounded-[4px] text-xs font-medium transition-all',
                      config.dataScope === 'share'
                        ? 'bg-[#d4af37] text-[#0a0a0c]'
                        : 'bg-[#1c1c1e] text-[#8a8f98] border border-[#2a2a2e]'
                    )}
                  >
                    团队共享
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Info className="w-4 h-4 text-[#8a8f98]" />
              <h3 className="text-white text-sm font-semibold">加密说明</h3>
            </div>
            <div className="space-y-3 text-xs text-[#8a8f98] leading-relaxed">
              <div className="flex items-start gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />
                <span>公司电脑上的加密文件可以正常打开和编辑（加密对应用透明）</span>
              </div>
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-[#ff9f4d] flex-shrink-0 mt-0.5" />
                <span>文件复制到非公司电脑后将无法打开（自动加密策略）</span>
              </div>
              <div className="p-3 bg-[#3b3015]/30 border border-[#d4af37]/20 rounded-[4px] mt-3">
                <span className="text-[#d4af37]">
                  注意：pandas/openpyxl/python-pptx 等库读写文件时无需感知加密，
                  公司加密系统在文件系统层自动处理。工具箱代码按标准文件 I/O 开发即可。
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Network Tab */}
      {activeTab === 'network' && (
        <div className="space-y-4 max-w-[720px]">
          {/* Browser Policy - New */}
          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Chrome className="w-4 h-4 text-[#d4af37]" />
              <h3 className="text-white text-sm font-semibold">浏览器分流策略</h3>
            </div>
            <p className="text-xs text-[#8a8f98] mb-4">
              不同目标系统使用不同浏览器，以适配内外网隔离策略
            </p>

            <div className="space-y-3">
              {browserPolicy.map((item, i) => (
                <div key={i} className="p-4 bg-[#0f0f11] rounded-[4px] border border-[#1e1e20]">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-white font-medium">{item.target}</span>
                    <span className="px-2 py-0.5 rounded-[4px] text-[10px] font-medium bg-[#3b3015] text-[#d4af37]">
                      {item.browser}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-[#8a8f98]">
                    <span>WebDriver: {item.driver}</span>
                    <span className="text-[#2a2a2e]">|</span>
                    <span>{item.reason}</span>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 p-3 bg-[#3b1515]/50 border border-[#ff4d4d]/20 rounded-[4px]">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-[#ff4d4d] flex-shrink-0 mt-0.5" />
                <div className="text-xs text-[#ff9f4d] leading-relaxed">
                  <span className="font-medium">重要：</span>
                  Chrome 无白名单权限，任何通过 Chrome 的外网请求都会被防火墙拦截。
                  飞书相关操作必须通过 Edge 浏览器执行。工具箱将自动根据 URL 选择对应浏览器。
                </div>
              </div>
            </div>
          </div>

          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Server className="w-4 h-4 text-[#d4af37]" />
              <h3 className="text-white text-sm font-semibold">网络环境配置</h3>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between py-3 border-b border-[#1e1e20]">
                <div>
                  <div className="text-sm text-white mb-0.5">网络连通性检测</div>
                  <div className="text-xs text-[#8a8f98]">
                    使用前自动检测目标域名是否可达，避免无效请求
                  </div>
                </div>
                <button
                  onClick={() => setConfig({ ...config, networkCheck: !config.networkCheck })}
                  className={cn(
                    'w-11 h-6 rounded-full transition-colors relative',
                    config.networkCheck ? 'bg-[#d4af37]' : 'bg-[#2a2a2e]'
                  )}
                >
                  <div
                    className={cn(
                      'absolute top-1 w-4 h-4 rounded-full bg-white transition-transform',
                      config.networkCheck ? 'left-6' : 'left-1'
                    )}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between py-3">
                <div>
                  <div className="text-sm text-white mb-0.5">离线工作模式</div>
                  <div className="text-xs text-[#8a8f98]">
                    仅使用本地缓存数据，禁止任何网络请求
                  </div>
                </div>
                <button
                  onClick={() => setConfig({ ...config, offlineMode: !config.offlineMode })}
                  className={cn(
                    'w-11 h-6 rounded-full transition-colors relative',
                    config.offlineMode ? 'bg-[#ff9f4d]' : 'bg-[#2a2a2e]'
                  )}
                >
                  <div
                    className={cn(
                      'absolute top-1 w-4 h-4 rounded-full bg-white transition-transform',
                      config.offlineMode ? 'left-6' : 'left-1'
                    )}
                  />
                </button>
              </div>
            </div>
          </div>

          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Info className="w-4 h-4 text-[#8a8f98]" />
              <h3 className="text-white text-sm font-semibold">Python 网络请求限制</h3>
            </div>
            <div className="p-3 bg-[#0f0f11] rounded-[4px]">
              <div className="space-y-2 text-xs text-[#8a8f98]">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-[#ff9f4d] flex-shrink-0 mt-0.5" />
                  <span>Python 的 requests/urllib 直接发起的 HTTP 请求<span className="text-[#ff4d4d] font-medium">不会</span>走白名单通道，会被防火墙拦截</span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />
                  <span>内网请求（EWO、OTS）用 Chrome WebDriver 执行，不受白名单限制</span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />
                  <span>飞书外网请求用 Edge WebDriver 执行，利用 Edge 的白名单权限</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tools Tab */}
      {activeTab === 'tools' && (
        <div className="space-y-4 max-w-[720px]">
          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Shield className="w-4 h-4 text-[#d4af37]" />
              <h3 className="text-white text-sm font-semibold">工具安全适配状态</h3>
            </div>

            <div className="space-y-3">
              {toolStatusList.map((tool) => {
                const Icon = tool.icon;
                return (
                  <div key={tool.name} className="p-4 bg-[#0f0f11] rounded-[4px] border border-[#1e1e20]">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-[#1c1c1e] rounded-[4px] flex items-center justify-center">
                          <Icon className="w-4 h-4 text-[#d4af37]" />
                        </div>
                        <div>
                          <div className="text-sm text-white font-medium flex items-center gap-2">
                            {tool.name}
                            <span className={cn(
                              'px-1.5 py-0.5 rounded-[3px] text-[10px] font-medium',
                              tool.status === 'ready' ? 'bg-[#3b3015] text-[#d4af37]' : 'bg-[#222225] text-[#8a8f98]'
                            )}>
                              {tool.status === 'ready' ? '已适配' : '规划中'}
                            </span>
                          </div>
                          <p className="text-xs text-[#8a8f98] mt-0.5">{tool.desc}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 flex-shrink-0">
                        {tool.gac && (
                          <div className="flex items-center gap-1 text-[10px] text-[#ff9f4d]">
                            <User className="w-3 h-3" />
                            需规避GAC
                          </div>
                        )}
                        {tool.encryption && (
                          <div className="flex items-center gap-1 text-[10px] text-[#d4af37]">
                            <Lock className="w-3 h-3" />
                            加密
                          </div>
                        )}
                        {tool.network && (
                          <div className="flex items-center gap-1 text-[10px] text-[#ff9f4d]">
                            <Globe className="w-3 h-3" />
                            需网络
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Deploy Tab - New */}
      {activeTab === 'deploy' && (
        <div className="space-y-4 max-w-[720px]">
          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Monitor className="w-4 h-4 text-[#d4af37]" />
              <h3 className="text-white text-sm font-semibold">绿色便携部署方案</h3>
            </div>
            <p className="text-xs text-[#8a8f98] mb-4">
              为规避 GAC 权限限制，工具箱采用绿色便携模式，解压即用
            </p>

            <div className="p-3 bg-[#0f0f11] rounded-[4px] font-mono text-xs text-[#8a8f98] leading-relaxed mb-4">
              {`VSE_TOOLBOX/                          ← 可放在任意用户目录
├── VSE_TOOLBOX.exe                   ← PyInstaller 打包的单文件
├── config/
│   └── settings.json                ← 用户配置
├── data/
│   ├── VSE_TOOLBOX.db               ← SQLite 数据库
│   └── backup/                     ← 自动备份
├── drivers/                         ← 自带浏览器驱动
│   ├── chromedriver.exe            ← Chrome 驱动（内网用）
│   └── msedgedriver.exe            ← Edge 驱动（飞书用）
├── templates/                       ← PPT 模板
│   ├── weekly_report.pptx
│   └── deliverable.pptx
├── temp/                           ← 临时文件（自动清理）
└── logs/                           ← 运行日志`}
            </div>

            <div className="space-y-3">
              <div className="flex items-start gap-3 p-3 bg-[#0f0f11] rounded-[4px]">
                <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-white font-medium mb-1">不依赖系统级 Python</div>
                  <p className="text-xs text-[#8a8f98]">
                    使用 python-embedded 或 PyInstaller 内置解释器，无需安装 Python，
                    不写入注册表，不添加到 PATH
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-[#0f0f11] rounded-[4px]">
                <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-white font-medium mb-1">不写入系统目录</div>
                  <p className="text-xs text-[#8a8f98]">
                    所有文件操作限定在工具箱目录和 %USERPROFILE% 下，
                    不写入 Program Files、Windows 等系统目录
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-[#0f0f11] rounded-[4px]">
                <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-white font-medium mb-1">不修改注册表</div>
                  <p className="text-xs text-[#8a8f98]">
                    WebDriver 从 tools/drivers/ 目录直接加载，不添加到系统 PATH，
                    不注册 COM 组件
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-[#0f0f11] rounded-[4px]">
                <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-white font-medium mb-1">无需管理员权限</div>
                  <p className="text-xs text-[#8a8f98]">
                    双击 exe 直接运行，不触发 UAC 提升请求。
                    若被拦截，添加为杀毒软件信任即可
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <AlertTriangle className="w-4 h-4 text-[#ff9f4d]" />
              <h3 className="text-white text-sm font-semibold">GAC 规避检查清单</h3>
            </div>
            <div className="space-y-2">
              {[
                { item: '程序安装路径', risk: '低', status: '用户目录，无风险' },
                { item: '注册表写入', risk: '中', status: '不写注册表，完全规避' },
                { item: '系统环境变量', risk: '中', status: '不修改 PATH，自带驱动' },
                { item: 'Windows 服务', risk: '高', status: '不安装任何服务' },
                { item: '计划任务', risk: '高', status: '不创建计划任务' },
                { item: '防火墙规则', risk: '高', status: '不修改防火墙配置' },
                { item: '浏览器扩展', risk: '中', status: '不安装浏览器插件' },
              ].map((check) => (
                <div key={check.item} className="flex items-center justify-between py-2 border-b border-[#1e1e20] last:border-0">
                  <span className="text-xs text-white">{check.item}</span>
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      'px-1.5 py-0.5 rounded-[3px] text-[10px] font-medium',
                      check.risk === '高' ? 'bg-[#3b1515] text-[#ff4d4d]' : 
                      check.risk === '中' ? 'bg-[#3b3015] text-[#ff9f4d]' : 'bg-[#222225] text-[#8a8f98]'
                    )}>
                      风险{check.risk}
                    </span>
                    <span className="text-xs text-green-400">{check.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Deliverable Config Tab */}
      {activeTab === 'deliverable' && (
        <div className="space-y-4 max-w-[720px]">
          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <FolderOpen className="w-4 h-4 text-[#d4af37]" />
              <h3 className="text-white text-sm font-semibold">交付物默认文件夹</h3>
            </div>
            <p className="text-xs text-[#8a8f98] mb-4">
              设置各交付物 Excel 文件的默认存放路径，导入时将优先从对应文件夹读取
            </p>

            <div className="space-y-4">
              {[
                { key: 'issues_folder' as const, label: '造车问题清单', placeholder: '例如：D:\\交付物\\造车问题' },
                { key: 'ewo_folder' as const, label: 'EWO/NCR 文件夹', placeholder: '例如：D:\\交付物\\EWO_NCR' },
                { key: 'tir_folder' as const, label: 'TIR 文件夹', placeholder: '例如：D:\\交付物\\TIR' },
              ].map((item) => (
                <div key={item.key} className="flex items-center justify-between py-3 border-b border-[#1e1e20] last:border-0">
                  <div className="flex-1">
                    <div className="text-sm text-white mb-0.5">{item.label}</div>
                    <div className="text-xs text-[#8a8f98]">
                      {item.key === 'issues_folder' && '飞书多维表格导出的造车问题 Excel 存放位置'}
                      {item.key === 'ewo_folder' && '公司内网 EWO/NCR 系统导出的 Excel 存放位置'}
                      {item.key === 'tir_folder' && '公司内网 TIR 系统导出的 Excel 存放位置'}
                    </div>
                  </div>
                  <input
                    value={folderPaths[item.key]}
                    onChange={(e) => setFolderPaths({ ...folderPaths, [item.key]: e.target.value })}
                    placeholder={item.placeholder}
                    className="w-[320px] h-9 px-3 bg-[#0f0f11] border border-[#2a2a2e] rounded-[4px] text-sm text-white placeholder-[#8a8f98] focus:outline-none focus:border-[#d4af37]"
                  />
                </div>
              ))}
            </div>

            <div className="mt-4 p-3 bg-[#3b3015]/30 border border-[#d4af37]/20 rounded-[4px]">
              <div className="flex items-start gap-2">
                <Info className="w-3.5 h-3.5 text-[#d4af37] flex-shrink-0 mt-0.5" />
                <span className="text-xs text-[#d4af37]">
                  配置后，在各交付物子页面点击「导入 Excel」时将自动定位到对应文件夹。
                  路径支持 Windows 格式（如 D:\folder）和 UNC 路径（如 \\server\share）。
                </span>
              </div>
            </div>
          </div>

          <div className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Info className="w-4 h-4 text-[#8a8f98]" />
              <h3 className="text-white text-sm font-semibold">导入说明</h3>
            </div>
            <div className="space-y-2 text-xs text-[#8a8f98] leading-relaxed">
              <div className="flex items-start gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />
                <span>造车问题：支持从飞书多维表格导出的 Excel，自动识别列名并映射到对应字段</span>
              </div>
              <div className="flex items-start gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />
                <span>EWO/NCR：支持从公司内网 EWO 系统导出的 Excel，自动匹配类型和严重度</span>
              </div>
              <div className="flex items-start gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />
                <span>TIR：支持从公司内网 TIR 系统导出的 Excel，自动匹配试验类型和状态</span>
              </div>
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-[#ff9f4d] flex-shrink-0 mt-0.5" />
                <span>导入时已存在的记录（按编号匹配）将自动更新，新记录将创建</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Save Button */}
      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={activeTab === 'deliverable' ? handleDeliverableSave : handleSave}
          className="h-9 px-6 bg-[#d4af37] text-[#0a0a0c] text-sm font-semibold rounded-[4px] hover:brightness-110 transition-all flex items-center gap-2"
        >
          <Save className="w-4 h-4" />
          {saved ? '已保存' : '保存配置'}
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-green-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            配置已保存到本地
          </span>
        )}
      </div>
    </div>
  );
}
