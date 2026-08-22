[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("official", "relay")]
    [string]$CodexProfile,

    [string]$CodexHome = $(
        if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
            Join-Path $env:USERPROFILE ".codex"
        }
        else {
            $env:CODEX_HOME
        }
    ),

    [string]$DesktopExecutable,

    [switch]$RestartDesktop,

    [switch]$ConfigureOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($RestartDesktop -and $ConfigureOnly) {
    throw "RestartDesktop and ConfigureOnly cannot be used together."
}

$codexHomeFull = [System.IO.Path]::GetFullPath($CodexHome)
$configPath = Join-Path $codexHomeFull "config.toml"
$switchRoot = Join-Path $codexHomeFull ".vse-profile-switch"
$backupPath = Join-Path $switchRoot "official.config.toml"
$statePath = Join-Path $switchRoot "state.json"
$credentialName = "CODEX_RELAY_API_KEY"

function Get-FileHashValue([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Utf8Atomic([string]$Path, [string]$Content) {
    $temporary = "$Path.tmp-$PID"
    try {
        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($temporary, $Content, $utf8NoBom)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Copy-Atomic([string]$Source, [string]$Destination) {
    $temporary = "$Destination.tmp-$PID"
    try {
        Copy-Item -LiteralPath $Source -Destination $temporary -Force
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Read-SwitchState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-SwitchState([hashtable]$State) {
    $json = $State | ConvertTo-Json -Depth 4
    Write-Utf8Atomic -Path $statePath -Content ($json + [Environment]::NewLine)
}

function Find-CodexDesktopProcesses {
    return @(Get-Process -Name "ChatGPT" -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.Path -and $_.Path -match '[\\/]OpenAI\.Codex_[^\\/]+[\\/]app[\\/]ChatGPT\.exe$'
        }
        catch {
            $false
        }
    })
}

function Resolve-DesktopExecutable($State, $Processes) {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($DesktopExecutable)) {
        $candidates += $DesktopExecutable
    }
    foreach ($process in $Processes) {
        if ($process.Path) {
            $candidates += $process.Path
        }
    }
    if ($null -ne $State -and $State.PSObject.Properties.Name -contains "desktop_executable") {
        $candidates += [string]$State.desktop_executable
    }
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $resolved = [System.IO.Path]::GetFullPath($candidate)
            if ((Test-Path -LiteralPath $resolved -PathType Leaf) -and
                [System.IO.Path]::GetFileName($resolved) -ieq "ChatGPT.exe") {
                return $resolved
            }
        }
    }
    return $null
}

function New-RelayConfig([string]$OfficialContent) {
    $withoutRelaySection = [regex]::Replace(
        $OfficialContent,
        '(?ms)^\[model_providers\.vse_relay\]\r?\n.*?(?=^\[|\z)',
        ''
    )
    $withoutProvider = [regex]::Replace(
        $withoutRelaySection,
        '(?m)^model_provider\s*=.*\r?\n?',
        ''
    )
    if ($withoutProvider -notmatch '(?m)^model\s*=') {
        throw "The base Codex config does not contain a top-level model setting."
    }
    $configured = [regex]::Replace(
        $withoutProvider,
        '(?m)^model\s*=.*$',
        'model = "GPT-5.6 SOL"' + [Environment]::NewLine + 'model_provider = "vse_relay"',
        1
    )
    $relaySection = @'
[model_providers.vse_relay]
name = "VSE temporary Responses relay"
base_url = "https://node-cf.sssaicodeapi.com/api/v1"
env_key = "CODEX_RELAY_API_KEY"
wire_api = "responses"
request_max_retries = 2
stream_max_retries = 4
stream_idle_timeout_ms = 300000
'@
    return $configured.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $relaySection + [Environment]::NewLine
}

if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Codex config was not found: $configPath"
}

$state = Read-SwitchState
$processes = Find-CodexDesktopProcesses
$desktopPath = Resolve-DesktopExecutable -State $state -Processes $processes

if ($RestartDesktop -and [string]::IsNullOrWhiteSpace($desktopPath)) {
    throw "Codex Desktop executable could not be resolved. Pass -DesktopExecutable with the full ChatGPT.exe path."
}
if (-not $RestartDesktop -and -not $ConfigureOnly -and $processes.Count -gt 0) {
    throw "Codex Desktop is running. Re-run with -RestartDesktop from an external PowerShell window."
}

# Complete all non-mutating safety checks before stopping the desktop app.
if ($CodexProfile -eq "relay") {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($credentialName, "Process"))) {
        throw "Relay desktop launch requires process environment variable CODEX_RELAY_API_KEY."
    }
    if ($null -ne $state -and [string]$state.active_profile -eq "relay") {
        if ((Get-FileHashValue $configPath) -ne [string]$state.relay_hash) {
            throw "Codex config changed while relay mode was active. Refusing to overwrite it; inspect $configPath manually."
        }
    }
    elseif (Test-Path -LiteralPath $backupPath) {
        throw "A prior official backup exists without a valid relay state. Refusing to overwrite: $backupPath"
    }
}
elseif ($null -ne $state -and [string]$state.active_profile -eq "relay") {
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "Official config backup is missing: $backupPath"
    }
    if ((Get-FileHashValue $configPath) -ne [string]$state.relay_hash) {
        throw "Codex config changed while relay mode was active. Refusing to discard those changes."
    }
    if ((Get-FileHashValue $backupPath) -ne [string]$state.official_hash) {
        throw "Official config backup hash mismatch. Refusing unsafe restore."
    }
}

if ($RestartDesktop -and $processes.Count -gt 0) {
    $processes | Stop-Process -Force
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = Find-CodexDesktopProcesses
    } while ($remaining.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline)
    if ($remaining.Count -gt 0) {
        throw "Codex Desktop did not exit within 20 seconds; configuration was not changed."
    }
}

if ($CodexProfile -eq "relay") {
    if ($null -ne $state -and [string]$state.active_profile -eq "relay") {
        $currentHash = Get-FileHashValue $configPath
        if ($currentHash -ne [string]$state.relay_hash) {
            throw "Codex config changed while relay mode was active. Refusing to overwrite it; inspect $configPath manually."
        }
    }
    else {
        if (Test-Path -LiteralPath $backupPath) {
            throw "A prior official backup exists without a valid relay state. Refusing to overwrite: $backupPath"
        }
        New-Item -ItemType Directory -Path $switchRoot -Force | Out-Null
        Copy-Item -LiteralPath $configPath -Destination $backupPath
    }

    $officialHash = Get-FileHashValue $backupPath
    $officialContent = [System.IO.File]::ReadAllText($backupPath)
    $relayContent = New-RelayConfig $officialContent
    Write-Utf8Atomic -Path $configPath -Content $relayContent
    $relayHash = Get-FileHashValue $configPath
    Write-SwitchState @{
        active_profile = "relay"
        official_hash = $officialHash
        relay_hash = $relayHash
        desktop_executable = $desktopPath
        updated_at = [DateTime]::UtcNow.ToString("o")
    }
}
else {
    if ($null -eq $state -or [string]$state.active_profile -ne "relay") {
        Write-Output "Desktop profile is already official; no managed relay state was found."
    }
    else {
        if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
            throw "Official config backup is missing: $backupPath"
        }
        if ((Get-FileHashValue $configPath) -ne [string]$state.relay_hash) {
            throw "Codex config changed while relay mode was active. Refusing to discard those changes."
        }
        if ((Get-FileHashValue $backupPath) -ne [string]$state.official_hash) {
            throw "Official config backup hash mismatch. Refusing unsafe restore."
        }
        Copy-Atomic -Source $backupPath -Destination $configPath
        Remove-Item -LiteralPath $backupPath -Force
        Remove-Item -LiteralPath $statePath -Force
        if ((Get-ChildItem -LiteralPath $switchRoot -Force | Measure-Object).Count -eq 0) {
            Remove-Item -LiteralPath $switchRoot
        }
    }
}

Write-Output "Codex Desktop default profile is configured as '$CodexProfile'."

if ($RestartDesktop) {
    Start-Process -FilePath $desktopPath
    Write-Output "Codex Desktop was started with profile '$CodexProfile'."
}
