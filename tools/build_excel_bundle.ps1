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
$workerSpec = Join-Path $repoRoot "VSE-ExcelWorker.spec"

if (-not (Test-Path -LiteralPath $webuiSpec -PathType Leaf)) {
    throw "Spec file not found: $webuiSpec"
}
if (-not (Test-Path -LiteralPath $workerSpec -PathType Leaf)) {
    throw "Spec file not found: $workerSpec"
}

$webuiWork = Join-Path $resolvedWorkDir "webui"
$workerWork = Join-Path $resolvedWorkDir "worker"

if ($Clean) {
    Assert-SafeRuntimePath -PathToCheck $resolvedWorkDir -RuntimeRootPath $resolvedRuntime
    if (Test-Path -LiteralPath $resolvedWorkDir) {
        Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $webuiWork)) {
    New-Item -ItemType Directory -Path $webuiWork -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $workerWork)) {
    New-Item -ItemType Directory -Path $workerWork -Force | Out-Null
}

Write-Host "Building Excel dual-executable bundle..."
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

# 2. Build VSE-ExcelWorker
Write-Host "==> Building VSE-ExcelWorker executable..."
& $PythonExecutable -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $resolvedOutputDir `
    --workpath $workerWork `
    $workerSpec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed for VSE-ExcelWorker.spec with exit code $LASTEXITCODE"
}

# 3. Verify sibling executables exist and are regular files
$webuiExe = Join-Path $resolvedOutputDir "VSE-WebUI.exe"
$workerExe = Join-Path $resolvedOutputDir "VSE-ExcelWorker.exe"

if (-not (Test-Path -LiteralPath $webuiExe -PathType Leaf)) {
    throw "Verification failed: '$webuiExe' does not exist or is not a regular file."
}
if (-not (Test-Path -LiteralPath $workerExe -PathType Leaf)) {
    throw "Verification failed: '$workerExe' does not exist or is not a regular file."
}

Write-Host "Verification succeeded:"
Write-Host "  - $webuiExe"
Write-Host "  - $workerExe"

$checksumFile = Join-Path $resolvedOutputDir "SHA256SUMS.txt"
@($webuiExe, $workerExe) |
    ForEach-Object {
        $hash = Get-FileHash -LiteralPath $_ -Algorithm SHA256
        "$($hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($hash.Path))"
    } |
    Set-Content -LiteralPath $checksumFile -Encoding ascii
Write-Host "  - $checksumFile"

# 4. Confined cleanup of temporary work directory beneath .runtime
if ($Clean -or (-not $NoCleanup)) {
    Assert-SafeRuntimePath -PathToCheck $resolvedWorkDir -RuntimeRootPath $resolvedRuntime
    Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Cleaned temporary work directory: $resolvedWorkDir"
}

Write-Host "Dual-executable bundle build completed successfully."
