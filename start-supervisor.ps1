[CmdletBinding()]
param(
    [ValidateSet("official", "relay")]
    [string]$CodexProfile = "official",

    [ValidateSet("agy-heavy", "codex-controlled")]
    [string]$SupervisorProfile = "agy-heavy",

    [string]$TaskFile,

    [switch]$RestartDesktop,

    [switch]$DesktopOnly,

    [string]$DesktopExecutable,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$runner = Join-Path $repoRoot "tools\agents\run_supervisor.ps1"
$setup = Join-Path $repoRoot "tools\agents\setup_codex_relay_profile.ps1"
$desktopSwitcher = Join-Path $repoRoot "tools\agents\switch_codex_desktop.ps1"
$tasksRoot = Join-Path $repoRoot ".agents\tasks"

if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Supervisor runner was not found: $runner"
}
if ($DesktopOnly -and -not $RestartDesktop) {
    throw "DesktopOnly requires RestartDesktop."
}

if ($CodexProfile -eq "relay") {
    try {
        & $setup -CheckOnly | Write-Host
    }
    catch {
        Write-Host "Relay profile is not installed or is outdated; installing the approved no-secret profile."
        & $setup
    }
}

$credentialName = "CODEX_RELAY_API_KEY"
$hadCredential = Test-Path "Env:$credentialName"
$previousCredential = if ($hadCredential) {
    [Environment]::GetEnvironmentVariable($credentialName, "Process")
}
else {
    $null
}
$temporaryCredential = $false

if ($CodexProfile -eq "relay" -and $RestartDesktop -and
    (-not $hadCredential -or [string]::IsNullOrWhiteSpace($previousCredential))) {
    $secure = Read-Host "Relay API key (kept only for the launched processes)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plain)) {
            throw "Relay API key cannot be empty."
        }
        [Environment]::SetEnvironmentVariable($credentialName, $plain, "Process")
        $temporaryCredential = $true
    }
    finally {
        if ($null -ne $pointer) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        if ($null -ne $secure) {
            $secure.Dispose()
        }
        $plain = $null
    }
}

try {
    if (-not $DesktopOnly -and [string]::IsNullOrWhiteSpace($TaskFile)) {
        $tasks = @(Get-ChildItem -LiteralPath $tasksRoot -Filter "*.json" -File | Sort-Object Name)
        if ($tasks.Count -eq 0) {
            throw "No task JSON files were found under $tasksRoot"
        }

        Write-Host "Available supervisor tasks:"
        for ($index = 0; $index -lt $tasks.Count; $index++) {
            Write-Host ("  [{0}] {1}" -f ($index + 1), $tasks[$index].Name)
        }

        $selection = Read-Host "Select a task number"
        $selectedNumber = 0
        if (-not [int]::TryParse($selection, [ref]$selectedNumber) -or
            $selectedNumber -lt 1 -or $selectedNumber -gt $tasks.Count) {
            throw "Invalid task selection: $selection"
        }
        $TaskFile = $tasks[$selectedNumber - 1].FullName
    }

    if (-not $DesktopOnly) {
        $arguments = @{
            TaskFile = $TaskFile
            CodexProfile = $CodexProfile
            SupervisorProfile = $SupervisorProfile
        }
        if ($DryRun) {
            $arguments.DryRun = $true
        }
    }

    if ($RestartDesktop) {
        $desktopArguments = @{
            CodexProfile = $CodexProfile
            RestartDesktop = $true
        }
        if (-not [string]::IsNullOrWhiteSpace($DesktopExecutable)) {
            $desktopArguments.DesktopExecutable = $DesktopExecutable
        }
        & $desktopSwitcher @desktopArguments
    }

    if ($DesktopOnly) {
        $exitCode = 0
    }
    else {
        Write-Host "Starting supervisor: Codex=$CodexProfile, orchestration=$SupervisorProfile"
        & $runner @arguments
        $exitCode = $LASTEXITCODE
    }
}
finally {
    if ($temporaryCredential) {
        if ($hadCredential) {
            [Environment]::SetEnvironmentVariable($credentialName, $previousCredential, "Process")
        }
        else {
            [Environment]::SetEnvironmentVariable($credentialName, $null, "Process")
        }
    }
}

exit $exitCode
