[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDir,

    [Parameter(Mandatory = $false)]
    [string]$WorkDir,

    [Parameter(Mandatory = $false)]
    [string]$PythonExecutable = "python",

    [Parameter(Mandatory = $false)]
    [switch]$Clean,

    [Parameter(Mandatory = $false)]
    [switch]$NoCleanup
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot ".runtime"

# Ensure .runtime directory exists
if (-not (Test-Path -LiteralPath $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
}
$resolvedRuntime = (Resolve-Path -LiteralPath $runtimeDir).Path

# Safe cleanup helper asserting path is strictly beneath .runtime
function Assert-SafeRuntimePath {
    param([string]$PathToCheck, [string]$RuntimeRootPath)
    if ([string]::IsNullOrWhiteSpace($PathToCheck)) {
        throw "Cannot verify an empty or whitespace path."
    }
    if (-not (Test-Path -LiteralPath $PathToCheck)) {
        return
    }
    $resolvedTarget = (Resolve-Path -LiteralPath $PathToCheck).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $RuntimeRootPath).Path
    if (-not ($resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase) -and $resolvedTarget.Length -gt $resolvedRoot.Length)) {
        throw "Directory '$PathToCheck' resolves to '$resolvedTarget' which is not strictly inside .runtime ('$resolvedRoot'). Cleanup refused."
    }
}

# Resolve OutputDir
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "dist"
}

if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}
$resolvedOutputDir = (Resolve-Path -LiteralPath $OutputDir).Path

# Resolve WorkDir
if ([string]::IsNullOrWhiteSpace($WorkDir)) {
    $WorkDir = Join-Path $runtimeDir "build_excel_bundle"
}

if (-not (Test-Path -LiteralPath $WorkDir)) {
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
}
$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path

# Spec file checks
$webuiSpec = Join-Path $repoRoot "VSE-WebUI.spec"

if (-not (Test-Path -LiteralPath $webuiSpec -PathType Leaf)) {
    throw "Spec file not found: $webuiSpec"
}

$webuiWork = Join-Path $resolvedWorkDir "webui"

if ($Clean) {
    Assert-SafeRuntimePath -PathToCheck $resolvedWorkDir -RuntimeRootPath $resolvedRuntime
    if (Test-Path -LiteralPath $resolvedWorkDir) {
        Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $webuiWork)) {
    New-Item -ItemType Directory -Path $webuiWork -Force | Out-Null
}

Write-Host "Building single-executable VSE-WebUI bundle..."
Write-Host "Output Directory: $resolvedOutputDir"
Write-Host "Working Directory: $resolvedWorkDir"

# 1. Build VSE-WebUI
Write-Host "==> Building VSE-WebUI executable..."
& $PythonExecutable -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $resolvedOutputDir `
    --workpath $webuiWork `
    $webuiSpec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed for VSE-WebUI.spec with exit code $LASTEXITCODE"
}

# VSE-WebUI is a onedir bundle (exe + _internal/ + plugins/) and now doubles as
# the Excel Worker: the host re-launches itself with the `--excel-worker`
# sentinel instead of a sibling executable (2026-10-09 advisor-reviewed plan A).
$bundleDir = Join-Path $resolvedOutputDir "VSE-WebUI"

# 2. Verify the host executable exists and is a regular file
$webuiExe = Join-Path $bundleDir "VSE-WebUI.exe"
$workerExe = Join-Path $bundleDir "VSE-ExcelWorker.exe"

if (-not (Test-Path -LiteralPath $webuiExe -PathType Leaf)) {
    throw "Verification failed: '$webuiExe' does not exist or is not a regular file."
}
# 单 exe 部署：不应再产出同目录 Worker。旧目录升级时遗留的 VSE-ExcelWorker.exe
# 不再被调用（controller 只自调起宿主），但必须显式拦下，避免误以为仍是旧布局。
if (Test-Path -LiteralPath $workerExe) {
    throw "Verification failed: '$workerExe' must not exist in the single-executable bundle."
}

Write-Host "Verification succeeded:"
Write-Host "  - $webuiExe (host + Excel Worker via --excel-worker sentinel)"

$checksumFile = Join-Path $bundleDir "SHA256SUMS.txt"
$bundlePrefix = $bundleDir.TrimEnd('\', '/').Length + 1
Get-ChildItem -LiteralPath $bundleDir -Recurse -File |
    Where-Object { $_.FullName -ne $checksumFile } |
    Sort-Object FullName |
    ForEach-Object {
        $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        $relative = $_.FullName.Substring($bundlePrefix).Replace('\', '/')
        "$($hash.Hash.ToLowerInvariant())  $relative"
    } |
    Set-Content -LiteralPath $checksumFile -Encoding ascii
Write-Host "  - $checksumFile"

# Colleagues receive one zip of the whole folder (shared via Feishu).
$zipFile = Join-Path $resolvedOutputDir "VSE-WebUI.zip"
if (Test-Path -LiteralPath $zipFile) {
    Remove-Item -LiteralPath $zipFile -Force
}
Compress-Archive -LiteralPath $bundleDir -DestinationPath $zipFile
Write-Host "  - $zipFile"

# 4. Confined cleanup of temporary work directory beneath .runtime
if ($Clean -or (-not $NoCleanup)) {
    Assert-SafeRuntimePath -PathToCheck $resolvedWorkDir -RuntimeRootPath $resolvedRuntime
    Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Cleaned temporary work directory: $resolvedWorkDir"
}

Write-Host "Single-executable bundle build completed successfully."
