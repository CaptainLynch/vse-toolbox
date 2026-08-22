[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TaskFile,

    [ValidateSet("official", "relay")]
    [string]$CodexProfile = "official",

    [ValidateSet("agy-heavy", "codex-controlled")]
    [string]$SupervisorProfile = "codex-controlled",

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$taskPath = if ([System.IO.Path]::IsPathRooted($TaskFile)) {
    [System.IO.Path]::GetFullPath($TaskFile)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $TaskFile))
}
if (-not $taskPath.StartsWith($repoRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Task file must remain inside the repository."
}
if (-not (Test-Path -LiteralPath $taskPath -PathType Leaf)) {
    throw "Task file does not exist: $taskPath"
}

$codexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    Join-Path $env:USERPROFILE ".codex"
}
else {
    $env:CODEX_HOME
}
$relayProfile = Join-Path $codexHome "vse-relay.config.toml"
$credentialName = "CODEX_RELAY_API_KEY"
$hadCredential = Test-Path "Env:$credentialName"
$previousCredential = if ($hadCredential) { [Environment]::GetEnvironmentVariable($credentialName, "Process") } else { $null }
$temporaryCredential = $false

try {
    if ($CodexProfile -eq "relay") {
        if (-not (Test-Path -LiteralPath $relayProfile -PathType Leaf)) {
            throw "Relay profile is not installed. Run tools/agents/setup_codex_relay_profile.ps1 first."
        }
        & (Join-Path $PSScriptRoot "setup_codex_relay_profile.ps1") -CodexHome $codexHome -CheckOnly | Write-Output
        if (-not $hadCredential -or [string]::IsNullOrWhiteSpace($previousCredential)) {
            $secure = Read-Host "Relay API key (kept only for this process)" -AsSecureString
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
    }

    $arguments = @(
        (Join-Path $repoRoot "tools\agents\supervisor.py"),
        "run",
        "--task-file", $taskPath,
        "--profile", $SupervisorProfile,
        "--codex-profile", $CodexProfile
    )
    if ($DryRun) {
        $arguments += "--dry-run"
    }
    Write-Output "Running supervisor with orchestration profile '$SupervisorProfile' and Codex profile '$CodexProfile'."
    & python @arguments
    $exitCode = $LASTEXITCODE
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
