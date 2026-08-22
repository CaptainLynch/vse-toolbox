[CmdletBinding()]
param(
    [ValidateSet("official", "relay")]
    [string]$CodexProfile = "relay",

    [ValidateSet("agy-heavy", "codex-controlled")]
    [string]$SupervisorProfile = "codex-controlled",

    [string]$TaskFile,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$runner = Join-Path $repoRoot "tools\agents\run_supervisor.ps1"
$setup = Join-Path $repoRoot "tools\agents\setup_codex_relay_profile.ps1"
$tasksRoot = Join-Path $repoRoot ".agents\tasks"

if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Supervisor runner was not found: $runner"
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

if ([string]::IsNullOrWhiteSpace($TaskFile)) {
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

$arguments = @{
    TaskFile = $TaskFile
    CodexProfile = $CodexProfile
    SupervisorProfile = $SupervisorProfile
}
if ($DryRun) {
    $arguments.DryRun = $true
}

Write-Host "Starting supervisor: Codex=$CodexProfile, orchestration=$SupervisorProfile"
& $runner @arguments
exit $LASTEXITCODE
