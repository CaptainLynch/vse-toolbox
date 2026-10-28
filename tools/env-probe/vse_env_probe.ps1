<#
VSE Toolbox v2 重构 —— 生产环境只读采集脚本（probe 1.0）

用途：为 v2 重构收集"办公电脑实际环境"的事实（见 docs/refactor-v2/ARCHITECTURE.md §8 M0）。
约束：普通用户权限即可；不需要 Python；兼容 Windows PowerShell 5.1 与受限语言模式。

不会采集：密码、Cookie、令牌、凭据库内容、数据库文件、业务数据正文、日志正文。
会做的写操作（可用 -NoWriteTest 关闭）：在 %LOCALAPPDATA% 与 HKCU 下各建一个临时项并立即删除；
复制系统自带的 whoami.exe 到临时目录运行一次（检测用户目录能否运行程序）后删除。
#>
param(
    [int]$Port = 0,
    [string]$VsePath = "",
    [switch]$NoWriteTest,
    [switch]$NoExcelTest,
    [switch]$NoNetworkTest
)

$ErrorActionPreference = "Stop"
$ProbeVersion = "1.1"
$R = [ordered]@{}
$Errors = New-Object System.Collections.ArrayList
$Started = Get-Date

function Step($title) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $title) -ForegroundColor Cyan }
function Note-Error($section, $err) { [void]$Errors.Add([ordered]@{ section = $section; error = ("" + $err).Split("`n")[0] }) }
function Try-Section($name, [scriptblock]$block) {
    try { $R[$name] = & $block } catch { Note-Error $name $_; $R[$name] = [ordered]@{ failed = $true } }
}
function RegVal($path, $name) {
    try { (Get-ItemProperty -Path $path -Name $name -ErrorAction Stop).$name } catch { $null }
}
function FileVer($path) {
    try { if ($path -and (Test-Path -LiteralPath $path)) { (Get-Item -LiteralPath $path).VersionInfo.ProductVersion } else { $null } } catch { $null }
}
function Desktop-Dir {
    try { $d = [Environment]::GetFolderPath("Desktop"); if ($d) { return $d } } catch {}
    $d = RegVal "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" "Desktop"
    if ($d) { return $d }
    return (Join-Path $env:USERPROFILE "Desktop")
}
function Rx-Escape($s) { return ($s -replace '([\\\.\[\]\(\)\*\+\?\^\$\|\{\}])', '\$1') }
# PowerShell 5.1 默认可能只开 TLS 1.0，内网 https 会握手失败
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch {}
function SizeMB($path) {
    try {
        if (-not (Test-Path -LiteralPath $path)) { return $null }
        $s = (Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        if ($null -eq $s) { 0 } else { [int]($s / 1MB) }
    } catch { $null }
}

Write-Host ""
Write-Host "VSE Toolbox 环境采集 $ProbeVersion —— 只读，大约 1 分钟" -ForegroundColor Green
Write-Host ""

# ── 1. 采集元信息 ─────────────────────────────────────────────
Step "1/12 采集脚本运行环境"
Try-Section "meta" {
    [ordered]@{
        probeVersion   = $ProbeVersion
        collectedAt    = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        psVersion      = "" + $PSVersionTable.PSVersion
        languageMode   = "" + $ExecutionContext.SessionState.LanguageMode
        executionPolicy = @(Get-ExecutionPolicy -List | ForEach-Object { "{0}={1}" -f $_.Scope, $_.ExecutionPolicy })
        options        = [ordered]@{ writeTest = -not $NoWriteTest; excelTest = -not $NoExcelTest; networkTest = -not $NoNetworkTest }
    }
}

# ── 2. 操作系统 ───────────────────────────────────────────────
Step "2/12 操作系统与区域设置"
Try-Section "os" {
    $nt = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    $os = $null; try { $os = Get-CimInstance Win32_OperatingSystem } catch {}
    $cs = $null; try { $cs = Get-CimInstance Win32_ComputerSystem } catch {}
    [ordered]@{
        productName   = RegVal $nt "ProductName"
        displayVersion = RegVal $nt "DisplayVersion"
        build         = "{0}.{1}" -f (RegVal $nt "CurrentBuild"), (RegVal $nt "UBR")
        architecture  = if ($os) { $os.OSArchitecture } else { $env:PROCESSOR_ARCHITECTURE }
        memoryGB      = if ($cs) { [int]($cs.TotalPhysicalMemory / 1GB) } else { $null }
        cpuThreads    = $env:NUMBER_OF_PROCESSORS
        domainJoined  = if ($cs) { [bool]$cs.PartOfDomain } else { $null }
        culture       = "" + (Get-Culture).Name
        uiCulture     = "" + (Get-UICulture).Name
        ansiCodePage  = RegVal "HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage" "ACP"
        utf8Beta      = ((RegVal "HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage" "ACP") -eq "65001")
        timeZone      = $(try { (Get-TimeZone).Id } catch { $null })
        longPaths     = RegVal "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" "LongPathsEnabled"
    }
}

# ── 3. 用户与权限 ─────────────────────────────────────────────
Step "3/12 用户权限与常用文件夹"
Try-Section "user" {
    $groups = ""; try { $groups = (whoami /groups /fo csv) -join "`n" } catch {}
    $adminLine = ($groups -split "`n" | Where-Object { $_ -match "S-1-5-32-544" }) -join ""
    $shell = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    $downloads = RegVal $shell "{374DE290-123F-4565-9164-39C4925E467B}"
    if ($downloads) { $downloads = $downloads -replace "%USERPROFILE%", $env:USERPROFILE }
    $desktop = Desktop-Dir
    $docs = RegVal "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" "Personal"
    if (-not $docs) { $docs = Join-Path $env:USERPROFILE "Documents" }
    $drive = (Split-Path -Qualifier $env:LOCALAPPDATA)
    $free = $null; try { $free = [int]((Get-PSDrive -Name $drive.TrimEnd(":")).Free / 1GB) } catch {}
    [ordered]@{
        inAdministratorsGroup = [bool]$adminLine
        adminEnabledInToken   = ($adminLine -match "Enabled group" -or $adminLine -match "已启用的组") -and -not ($adminLine -match "deny only" -or $adminLine -match "拒绝")
        localAppData          = $env:LOCALAPPDATA
        localAppDataFreeGB    = $free
        desktop               = $desktop
        desktopOnOneDrive     = ($desktop -match "OneDrive")
        documents             = $docs
        downloads             = $downloads
        roamingProfileHint    = ($env:APPDATA -like "\\*")
        chatReceiveFoldersExist = [ordered]@{
            downloads        = [bool]($downloads -and (Test-Path -LiteralPath $downloads))
            qqTencentFiles   = Test-Path -LiteralPath (Join-Path $docs "Tencent Files")
            wechatFiles      = (Test-Path -LiteralPath (Join-Path $docs "WeChat Files")) -or (Test-Path -LiteralPath (Join-Path $docs "xwechat_files"))
            feishuDocuments  = (Test-Path -LiteralPath (Join-Path $docs "Feishu")) -or (Test-Path -LiteralPath (Join-Path $docs "Lark"))
        }
    }
}

# ── 4. 写入与运行测试（免管理员能力验证） ─────────────────────
Step "4/12 免管理员安装能力测试"
Try-Section "writeTests" {
    if ($NoWriteTest) { return [ordered]@{ skipped = $true } }
    $out = [ordered]@{}
    $dir = Join-Path $env:LOCALAPPDATA "VSE-Probe-tmp"
    try {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content -LiteralPath (Join-Path $dir "t.txt") -Value "probe" -Encoding ASCII
        $out.localAppDataWritable = $true
    } catch { $out.localAppDataWritable = $false; $out.localAppDataError = ("" + $_).Split("`n")[0] }
    # 用户目录里能否运行 exe（AppLocker / 软件限制策略 / 杀软拦截都会在这里暴露）
    try {
        $exe = Join-Path $dir "probe-run.exe"
        Copy-Item -LiteralPath "$env:WINDIR\System32\whoami.exe" -Destination $exe -Force
        $o = & $exe 2>&1
        $out.exeRunsFromLocalAppData = ($LASTEXITCODE -eq 0)
    } catch { $out.exeRunsFromLocalAppData = $false; $out.exeRunError = ("" + $_).Split("`n")[0] }
    try { Remove-Item -LiteralPath $dir -Recurse -Force } catch {}
    # HKCU 注册表：文件关联（Software\Classes）与开机自启（Run）都只需要 HKCU
    $k = "HKCU:\Software\Classes\.vseprobe-tmp"
    try { New-Item -Path $k -Force | Out-Null; Remove-Item -Path $k -Recurse -Force; $out.hkcuClassesWritable = $true }
    catch { $out.hkcuClassesWritable = $false }
    $run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    try { New-ItemProperty -Path $run -Name "VSE-Probe-tmp" -Value "probe" -PropertyType String -Force | Out-Null; Remove-ItemProperty -Path $run -Name "VSE-Probe-tmp" -Force; $out.hkcuRunWritable = $true }
    catch { $out.hkcuRunWritable = $false }
    $startup = RegVal "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" "Startup"
    $out.startupFolderExists = [bool]($startup -and (Test-Path -LiteralPath $startup))
    $out
}

# ── 5. 组策略与安全软件 ───────────────────────────────────────
Step "5/12 安全软件与策略"
Try-Section "security" {
    $av = @()
    try { $av = @(Get-CimInstance -Namespace "root/SecurityCenter2" -ClassName AntiVirusProduct | ForEach-Object { [ordered]@{ name = $_.displayName; state = ("0x{0:X}" -f $_.productState) } }) } catch {}
    $applocker = $null
    try { $p = Get-AppLockerPolicy -Effective -ErrorAction Stop; $applocker = [ordered]@{ ruleCollections = @($p.RuleCollections | ForEach-Object { "{0}:{1}rules" -f $_.RuleCollectionType, @($_).Count }) } } catch { $applocker = "unavailable" }
    [ordered]@{
        antivirus         = $av
        appLocker         = $applocker
        saferPolicyExists = Test-Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Safer\CodeIdentifiers"
        smartScreenPolicy = RegVal "HKLM:\SOFTWARE\Policies\Microsoft\Windows\System" "EnableSmartScreen"
        psExecPolicyGPO   = RegVal "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell" "ExecutionPolicy"
        webView2PolicyExists = Test-Path "HKLM:\SOFTWARE\Policies\Microsoft\Edge\WebView2"
        edgePolicyExists  = Test-Path "HKLM:\SOFTWARE\Policies\Microsoft\Edge"
    }
}

# ── 6. 运行库、浏览器与 WebView2 ─────────────────────────────
Step "6/12 运行库、浏览器与 WebView2"
Try-Section "runtimes" {
    $wv = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $edgeExe = RegVal "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe" "(default)"
    if (-not $edgeExe) { $edgeExe = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" }
    $py = $null; try { $py = (Get-Command python -ErrorAction Stop).Source } catch {}
    [ordered]@{
        webView2Machine = RegVal "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$wv" "pv"
        webView2User    = RegVal "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$wv" "pv"
        edgeVersion     = FileVer $edgeExe
        defaultBrowser  = RegVal "HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice" "ProgId"
        vcRedistX64     = RegVal "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Version"
        vcruntime140    = FileVer "$env:WINDIR\System32\vcruntime140.dll"
        ucrtbase        = FileVer "$env:WINDIR\System32\ucrtbase.dll"
        dotNetFxRelease = RegVal "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" "Release"
        pythonOnPath    = $py
        pythonLauncher  = [bool](Test-Path "$env:WINDIR\py.exe")
    }
}

# ── 7. Office / Excel / Outlook ───────────────────────────────
Step "7/12 Office 与 Excel（COM 测试会在后台短暂启动 Excel）"
Try-Section "office" {
    $c2r = "HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration"
    $excelExe = RegVal "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe" "(default)"
    $outlookExe = RegVal "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE" "(default)"
    $o = [ordered]@{
        excelPath        = if ($excelExe) { Split-Path -Leaf $excelExe } else { $null }
        excelVersion     = FileVer $excelExe
        clickToRun       = [bool](Test-Path $c2r)
        platform         = RegVal $c2r "Platform"
        c2rVersion       = RegVal $c2r "VersionToReport"
        productIds       = RegVal $c2r "ProductReleaseIds"
        updateChannel    = RegVal $c2r "CDNBaseUrl"
        excelComProgId   = RegVal "Registry::HKEY_CLASSES_ROOT\Excel.Application\CurVer" "(default)"
        outlookInstalled = [bool]$outlookExe
        outlookVersion   = FileVer $outlookExe
        emlHandler       = RegVal "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.eml\UserChoice" "ProgId"
        excelRunningBefore = [bool](Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
    }
    if ($NoExcelTest) { $o.comTest = "skipped" }
    elseif ($o.excelRunningBefore) { $o.comTest = "skipped: Excel 正在运行，关闭 Excel 后重跑可完成此项" }
    elseif (-not $o.excelComProgId) { $o.comTest = "skipped: 未注册 Excel.Application" }
    else {
        $t0 = Get-Date
        $t = Measure-Command {
            $xl = $null; $wbs = $null; $wb = $null; $ws = $null; $rg = $null
            try {
                $xl = New-Object -ComObject Excel.Application
                $xl.Visible = $false; $xl.DisplayAlerts = $false
                $o.comVersion = "" + $xl.Version
                $o.comBuild = "" + $xl.Build
                # 每一层 COM 对象都要单独持有并释放，否则 EXCEL.EXE 会留在后台（probe 1.0 的教训）
                $wbs = $xl.Workbooks; $wb = $wbs.Add(); $ws = $wb.Worksheets.Item(1); $rg = $ws.Range("A1")
                $rg.Value2 = 42
                $o.comWorkbookOk = ($rg.Value2 -eq 42)
                $wb.Close($false); $xl.Quit()
                $o.comTest = "ok"
            } catch { $o.comTest = "failed: " + ("" + $_).Split("`n")[0] }
            foreach ($c in @($rg, $ws, $wb, $wbs, $xl)) { if ($c) { try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($c) } catch {} } }
            $rg = $null; $ws = $null; $wb = $null; $wbs = $null; $xl = $null
            try { [GC]::Collect(); [GC]::WaitForPendingFinalizers(); [GC]::Collect() } catch {}
        }
        $o.comSeconds = [int]$t.TotalSeconds
        Start-Sleep -Seconds 3
        $left = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Where-Object { try { $_.StartTime -ge $t0 } catch { $false } })
        $o.excelLeftRunningAfterRelease = ($left.Count -gt 0)
        # 测试前没有 Excel 在运行，测试后新出现的 EXCEL.EXE 一定是本脚本启动的，直接结束它
        if ($left.Count) { $left | ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch {} } }
        $o.excelLeftRunning = [bool](Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Where-Object { try { $_.StartTime -ge $t0 } catch { $false } })
    }
    $o
}

# ── 8. 显示 ───────────────────────────────────────────────────
Step "8/12 屏幕分辨率与缩放"
Try-Section "display" {
    $v = @(); try { $v = @(Get-CimInstance Win32_VideoController | Where-Object { $_.CurrentHorizontalResolution } | ForEach-Object { "{0}x{1}" -f $_.CurrentHorizontalResolution, $_.CurrentVerticalResolution }) } catch {}
    [ordered]@{
        resolutions = $v
        appliedDpi  = RegVal "HKCU:\Control Panel\Desktop\WindowMetrics" "AppliedDPI"
        logPixels   = RegVal "HKCU:\Control Panel\Desktop" "LogPixels"
        darkApps    = ((RegVal "HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" "AppsUseLightTheme") -eq 0)
    }
}

# ── 9. 网络（只做连通性，不登录） ─────────────────────────────
Step "9/12 内网系统连通性（不登录，只测能否连上）"
Try-Section "network" {
    $is = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $n = [ordered]@{
        proxyEnable   = RegVal $is "ProxyEnable"
        proxyServer   = RegVal $is "ProxyServer"
        autoConfigURL = RegVal $is "AutoConfigURL"
        winhttpProxy  = $(try { ((netsh winhttp show proxy) | Where-Object { $_ -match "\S" } | Select-Object -Last 2) -join " | " } catch { $null })
        loopback5000InUse = [bool](netstat -ano | Select-String -Pattern "127\.0\.0\.1:5000\s+.*LISTENING")
    }
    if ($NoNetworkTest) { $n.targets = "skipped"; return $n }
    $targets = @(
        @{ name = "统一身份认证"; url = "https://account.sgmw.com.cn/" },
        @{ name = "Aras ECM";     url = "http://ecm.sgmw.com.cn/innovatorserver/" },
        @{ name = "TDC";          url = "https://tdc.sgmw.com.cn/" },
        @{ name = "帆软报表(TIR)"; url = "https://report.sgmw.com.cn/" }
    )
    $n.targets = @(foreach ($t in $targets) {
        $u = [uri]$t.url; $row = [ordered]@{ name = $t.name; host = $u.Host }
        try { $row.dns = @(Resolve-DnsName -Name $u.Host -ErrorAction Stop | Where-Object { $_.IPAddress } | Select-Object -First 1).Count -gt 0 } catch { $row.dns = $false }
        try {
            $sw = Get-Date
            $resp = Invoke-WebRequest -Uri $t.url -Method Head -UseBasicParsing -TimeoutSec 10 -MaximumRedirection 5 -ErrorAction Stop
            $row.http = [int]$resp.StatusCode
        } catch {
            $code = $null; try { $code = [int]$_.Exception.Response.StatusCode } catch {}
            $row.http = if ($code) { $code } else { "error: " + ("" + $_.Exception.Message).Split("`n")[0] }
        }
        $row.ms = [int]((Get-Date) - $sw).TotalMilliseconds
        $row
    })
    $n
}

# ── 10. 现有 VSE Toolbox 安装 ─────────────────────────────────
Step "10/12 现有 VSE Toolbox 安装情况"
$VseRoot = $null
Try-Section "vseInstall" {
    $exePath = $null
    $proc = Get-Process -Name "VSE-WebUI" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($proc) { try { $exePath = $proc.Path } catch {} }
    if (-not $exePath -and $VsePath) {
        $cand = if ((Get-Item -LiteralPath $VsePath).PSIsContainer) { Join-Path $VsePath "VSE-WebUI.exe" } else { $VsePath }
        if (Test-Path -LiteralPath $cand) { $exePath = $cand }
    }
    if (-not $exePath) {
        $roots = @((Desktop-Dir), (Join-Path $env:USERPROFILE "Downloads"), $env:LOCALAPPDATA, "D:\", "E:\")
        foreach ($r in $roots) {
            if (-not $r -or -not (Test-Path -LiteralPath $r)) { continue }
            $hit = Get-ChildItem -LiteralPath $r -Filter "VSE-WebUI.exe" -Recurse -Depth 3 -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { $exePath = $hit.FullName; break }
        }
    }
    if (-not $exePath) { return [ordered]@{ found = $false; hint = "没找到 VSE-WebUI.exe：可以先打开 VSE Toolbox 再运行本脚本" } }
    $root = Split-Path -Parent $exePath
    $script:VseRoot = $root
    $data = Join-Path $root "data"
    if (-not (Test-Path -LiteralPath $data)) { $data = Join-Path $env:LOCALAPPDATA "VSE-Toolbox" }
    $plugins = @()
    $pdir = Join-Path $root "plugins"
    if (Test-Path -LiteralPath $pdir) {
        $plugins = @(Get-ChildItem -LiteralPath $pdir -Directory | ForEach-Object {
            $m = Join-Path $_.FullName "plugin.json"
            if (Test-Path -LiteralPath $m) { $j = Get-Content -LiteralPath $m -Raw -Encoding UTF8 | ConvertFrom-Json; "{0}@{1}" -f $j.id, $j.version }
        })
    }
    $active = $null
    $af = Join-Path $data "plugin-updates\active.json"
    if (Test-Path -LiteralPath $af) { try { $a = Get-Content -LiteralPath $af -Raw -Encoding UTF8 | ConvertFrom-Json; $active = @($a.plugins.PSObject.Properties | ForEach-Object { "{0}@{1}" -f $_.Name, $_.Value.version }) } catch {} }
    $sub = [ordered]@{}
    if (Test-Path -LiteralPath $data) { Get-ChildItem -LiteralPath $data -Directory -ErrorAction SilentlyContinue | ForEach-Object { $sub[$_.Name] = SizeMB $_.FullName } }
    $db = Join-Path $data "vse_toolbox.db"
    $writable = $false; try { $f = Join-Path $root ".probe-w"; Set-Content -LiteralPath $f -Value 1; Remove-Item -LiteralPath $f -Force; $writable = $true } catch {}
    [ordered]@{
        found          = $true
        runningNow     = [bool]$proc
        installDir     = $root
        installDirWritable = $writable
        exeVersion     = FileVer $exePath
        exeDate        = (Get-Item -LiteralPath $exePath).LastWriteTime.ToString("yyyy-MM-dd")
        # exe 直接放在「下载」或桌面时，整个文件夹的大小没有意义，只统计 VSE 自己的 exe
        installSizeMB  = $(if ((Get-ChildItem -LiteralPath $root -Directory -Filter "_internal" -ErrorAction SilentlyContinue)) { SizeMB $root } else { $null })
        layout         = $(if (Test-Path -LiteralPath (Join-Path $root "_internal")) { "onedir" } else { "onefile" })
        vseExeCopies   = @(Get-ChildItem -LiteralPath $root -Filter "VSE-*.exe" -File).Count
        vseExeTotalMB  = [int]((Get-ChildItem -LiteralPath $root -Filter "VSE-*.exe" -File | Measure-Object -Property Length -Sum).Sum / 1MB)
        dataDir        = $data
        dbSizeMB       = if (Test-Path -LiteralPath $db) { [math]::Round((Get-Item -LiteralPath $db).Length / 1MB, 1) } else { $null }
        dataSubdirsMB  = $sub
        bundledPlugins = $plugins
        updatedPlugins = $active
        excelWorkerExe = Test-Path -LiteralPath (Join-Path $root "VSE-ExcelWorker.exe")
        otherExes      = @(Get-ChildItem -LiteralPath $root -Filter "*.exe" -File | ForEach-Object { $_.Name })
    }
}

# ── 11. 现有 VSE 的使用统计（需要程序正在运行；只记结构、数量、状态，不记内容） ──
Step "11/12 读取使用统计（只读接口，只记数量与状态）"
$EnumKeys = @("status","state","category","kind","type","enabled","mode","updatemode","source","sourcekind","version",
              "hostapi","id","phase","frequency","intervalminutes","running","paused","ok","code","errorcode","outcome",
              "syncstate","authstate","querystate","result","jobkey","key","formkey","deliverableid","catalogid","channel","displaystate")
$SecretRx = "pass|token|cookie|secret|credential|session|auth.*header|password"
function Shape($v, [int]$depth) {
    if ($null -eq $v) { return "null" }
    if ($depth -gt 6) { return "…" }
    if ($v -is [string]) { return "str" }
    if ($v -is [bool]) { return "bool" }
    if ($v -is [int] -or $v -is [long] -or $v -is [double] -or $v -is [decimal]) { return "num" }
    if ($v -is [array]) {
        $o = [ordered]@{ "#len" = $v.Count }
        if ($v.Count -gt 0) {
            $o["#item"] = Shape $v[0] ($depth + 1)
            # 对数组元素里的枚举型字段做值分布统计
            if ($v[0] -is [psobject] -and -not ($v[0] -is [string])) {
                $dist = [ordered]@{}
                foreach ($el in $v) {
                    foreach ($p in $el.PSObject.Properties) {
                        $k = $p.Name.ToLower()
                        if ($EnumKeys -contains $k -and $k -notmatch $SecretRx -and ($p.Value -is [string] -or $p.Value -is [bool] -or $p.Value -is [int]) -and ("" + $p.Value).Length -le 40) {
                            if (-not $dist.Contains($p.Name)) { $dist[$p.Name] = [ordered]@{} }
                            $val = "" + $p.Value
                            if ($dist[$p.Name].Contains($val)) { $dist[$p.Name][$val]++ } else { $dist[$p.Name][$val] = 1 }
                        }
                    }
                }
                if ($dist.Count) { $o["#values"] = $dist }
            }
        }
        return $o
    }
    $o = [ordered]@{}
    foreach ($p in $v.PSObject.Properties) {
        $k = $p.Name
        if ($k -match $SecretRx) { $o[$k] = "<不采集>"; continue }
        $pv = $p.Value
        if ($EnumKeys -contains $k.ToLower() -and ($pv -is [string] -or $pv -is [bool] -or $pv -is [int]) -and ("" + $pv).Length -le 40) { $o[$k] = "=" + $pv }
        else { $o[$k] = Shape $pv ($depth + 1) }
    }
    return $o
}
Try-Section "vseApi" {
    $ports = @()
    if ($Port) { $ports += $Port }
    $ports += 5000
    try {
        $pids = @(Get-Process -Name "VSE-WebUI" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
        if ($pids.Count) {
            netstat -ano | Select-String "127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING\s+(\d+)" | ForEach-Object {
                if ($pids -contains [int]$_.Matches[0].Groups[2].Value) { $ports += [int]$_.Matches[0].Groups[1].Value }
            }
        }
    } catch {}
    $base = $null
    foreach ($p in ($ports | Select-Object -Unique)) {
        try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$p/api/version" -TimeoutSec 4; $base = "http://127.0.0.1:$p"; break } catch {}
    }
    if (-not $base) { return [ordered]@{ reachable = $false; hint = "VSE Toolbox 没有在运行：先打开它再运行本脚本，可以多采集使用统计" } }
    $eps = @("/api/version","/api/host/manifest","/api/host/updates","/api/settings","/api/project-status",
             "/api/project-status/scheduler","/api/project-status/runs","/api/project-status/updates","/api/project-status/section-rollup",
             "/api/tasks?limit=200","/api/scheduled-archive/jobs","/api/scheduled-archive/runs","/api/excel-tasks","/api/excel-worker/status",
             "/api/deliverables/catalog","/api/p/project-overview/sync-settings","/api/p/project-overview/watchlist",
             "/api/p/sign-daily/state","/api/p/tir-report/state","/api/p/tir-report/files")
    # 访问本机接口时绕开系统代理（有的公司代理没有排除 127.0.0.1）
    $oldProxy = $null; try { $oldProxy = [System.Net.WebRequest]::DefaultWebProxy; [System.Net.WebRequest]::DefaultWebProxy = $null } catch {}
    $res = [ordered]@{ reachable = $true; port = ([uri]$base).Port; endpoints = [ordered]@{} }
    foreach ($e in $eps) {
        $row = [ordered]@{}
        $sw = Get-Date
        try {
            $r = Invoke-WebRequest -Uri ($base + $e) -UseBasicParsing -TimeoutSec 30
            $row.http = [int]$r.StatusCode
            $row.bytes = $r.RawContentLength
            $row.ms = [int]((Get-Date) - $sw).TotalMilliseconds
            try { $row.shape = Shape ($r.Content | ConvertFrom-Json) 0 } catch { $row.shape = "non-json" }
        } catch {
            $row.ms = [int]((Get-Date) - $sw).TotalMilliseconds
            $code = $null; try { $code = [int]$_.Exception.Response.StatusCode } catch {}
            $row.http = if ($code) { $code } else { "error" }
        }
        $res.endpoints[$e] = $row
    }
    # 首页加载耗时（体验基线）
    $sw = Get-Date
    try { $null = Invoke-WebRequest -Uri ($base + "/") -UseBasicParsing -TimeoutSec 30; $res.homeMs = [int]((Get-Date) - $sw).TotalMilliseconds } catch {}
    try { if ($oldProxy) { [System.Net.WebRequest]::DefaultWebProxy = $oldProxy } } catch {}
    $res
}

# ── 12. 日志统计（只数级别、模块名、异常类型，不保存日志正文） ──
Step "12/12 日志错误统计"
Try-Section "logs" {
    if (-not $VseRoot) { return [ordered]@{ skipped = "未找到安装目录" } }
    $dirs = @((Join-Path $VseRoot "data"), (Join-Path $VseRoot "data\logs"), (Join-Path $VseRoot "logs"), (Join-Path $env:LOCALAPPDATA "VSE-Toolbox"))
    $files = @(foreach ($d in $dirs) { if (Test-Path -LiteralPath $d) { Get-ChildItem -LiteralPath $d -Filter "*.log*" -File -ErrorAction SilentlyContinue } })
    $levels = [ordered]@{}; $loggers = @{}; $exc = @{}; $days = @{}
    foreach ($f in $files | Select-Object -First 20) {
        foreach ($line in (Get-Content -LiteralPath $f.FullName -Encoding UTF8 -Tail 20000 -ErrorAction SilentlyContinue)) {
            if ($line -match "^(\d{4}-\d{2}-\d{2}) [\d:,]+ \[(\w+)\] ([\w\.\-]+):") {
                $lv = $Matches[2]; $lg = $Matches[3]; $day = $Matches[1]
                if ($levels.Contains($lv)) { $levels[$lv]++ } else { $levels[$lv] = 1 }
                if ($lv -eq "ERROR" -or $lv -eq "WARNING" -or $lv -eq "CRITICAL") {
                    $key = "$lv $lg"; $loggers[$key] = 1 + [int]$loggers[$key]
                    $days[$day] = 1 + [int]$days[$day]
                }
            }
            if ($line -cmatch "\b([A-Z][A-Za-z]{2,}(?:Error|Exception|Timeout))\b") { $n = $Matches[1]; $exc[$n] = 1 + [int]$exc[$n] }
        }
    }
    [ordered]@{
        files            = @($files | ForEach-Object { "{0} ({1} KB, {2})" -f $_.Name, [int]($_.Length / 1KB), $_.LastWriteTime.ToString("yyyy-MM-dd") })
        levelCounts      = $levels
        topWarnErrorLoggers = @($loggers.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 15 | ForEach-Object { "{0} x{1}" -f $_.Key, $_.Value })
        exceptionTypes   = @($exc.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 15 | ForEach-Object { "{0} x{1}" -f $_.Key, $_.Value })
        warnErrorDaysLast = @($days.GetEnumerator() | Sort-Object Key -Descending | Select-Object -First 14 | ForEach-Object { "{0} x{1}" -f $_.Key, $_.Value })
    }
}

# ── 输出：脱敏 → JSON + 摘要 → zip ────────────────────────────
$R["errors"] = $Errors
$R["durationSeconds"] = [int]((Get-Date) - $Started).TotalSeconds
$json = $R | ConvertTo-Json -Depth 12
# 用户名、电脑名、域名一律替换成占位符
# 域名不替换：它就是公司简称，会把内网主机名也替换掉（probe 1.0 的教训）
foreach ($pair in @(@($env:USERNAME, "<user>"), @($env:COMPUTERNAME, "<pc>"))) {
    # 只替换完整的名字（前后不是字母数字），避免短用户名把普通单词也替换掉
    if ($pair[0] -and $pair[0].Length -ge 2) { $json = $json -ireplace ("(?<![A-Za-z0-9])" + (Rx-Escape $pair[0]) + "(?![A-Za-z0-9])"), $pair[1] }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$outDir = Join-Path (Desktop-Dir) "VSE-env-$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$json | Out-File -LiteralPath (Join-Path $outDir "report.json") -Encoding utf8

function YN($b) { if ($b -eq $true) { "是" } elseif ($b -eq $false) { "否" } else { "未知" } }
$s = New-Object System.Collections.ArrayList
[void]$s.Add("VSE Toolbox 环境采集摘要（probe $ProbeVersion，$($R.meta.collectedAt)，耗时 $($R.durationSeconds) 秒）")
[void]$s.Add("请先看一遍本文件和 report.json，确认没有你不想发出的内容，再发送 zip。")
[void]$s.Add("")
[void]$s.Add("系统：$($R.os.productName) $($R.os.displayVersion) build $($R.os.build)，$($R.os.architecture)，内存 $($R.os.memoryGB) GB")
[void]$s.Add("管理员权限：$(YN $R.user.adminEnabledInToken)；加入域：$(YN $R.os.domainJoined)")
[void]$s.Add("用户目录可写：$(YN $R.writeTests.localAppDataWritable)；用户目录能运行程序：$(YN $R.writeTests.exeRunsFromLocalAppData)；HKCU 可写（文件关联/自启）：$(YN $R.writeTests.hkcuClassesWritable)/$(YN $R.writeTests.hkcuRunWritable)")
[void]$s.Add("WebView2：本机 $($R.runtimes.webView2Machine) / 用户 $($R.runtimes.webView2User)；Edge $($R.runtimes.edgeVersion)")
[void]$s.Add("VC++ 运行库：$($R.runtimes.vcRedistX64)；vcruntime140 $($R.runtimes.vcruntime140)；Python：$(if ($R.runtimes.pythonOnPath) { '有' } else { '无' })")
[void]$s.Add("Excel：$($R.office.excelVersion)（$($R.office.platform)）；COM 测试：$($R.office.comTest)；Outlook：$(YN $R.office.outlookInstalled)")
[void]$s.Add("杀毒软件：$((@($R.security.antivirus) | ForEach-Object { $_.name }) -join '、')")
if ($R.network.targets -is [array]) { foreach ($t in $R.network.targets) { [void]$s.Add("连通性 $($t.name)：DNS $(YN $t.dns)，HTTP $($t.http)，$($t.ms) ms") } }
[void]$s.Add("现有 VSE：$(if ($R.vseInstall.found) { "版本 $($R.vseInstall.exeVersion)，数据库 $($R.vseInstall.dbSizeMB) MB，运行中 $(YN $R.vseInstall.runningNow)" } else { '未找到' })")
[void]$s.Add("使用统计接口：$(if ($R.vseApi.reachable) { "已读取（端口 $($R.vseApi.port)，首页 $($R.vseApi.homeMs) ms）" } else { '未读取（程序没运行）' })")
[void]$s.Add("采集中出错的项：$($Errors.Count)")
($s -join "`r`n") | Out-File -LiteralPath (Join-Path $outDir "summary.txt") -Encoding utf8

$zip = "$outDir.zip"
try { Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zip -Force } catch { $zip = $null }

Write-Host ""
Write-Host ($s -join "`n")
Write-Host ""
Write-Host "完成。结果在桌面：" -ForegroundColor Green
Write-Host "  文件夹 $outDir"
if ($zip) { Write-Host "  压缩包 $zip   ← 检查后把这个发回来" -ForegroundColor Green }
try { Start-Process explorer.exe -ArgumentList "/select,`"$(if ($zip) { $zip } else { $outDir })`"" } catch {}
