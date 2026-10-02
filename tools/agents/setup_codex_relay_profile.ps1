[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$CodexHome = $(
        if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
            Join-Path $env:USERPROFILE ".codex"
        }
        else {
            $env:CODEX_HOME
        }
    ),
    [switch]$Force,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$codexHomeFull = [System.IO.Path]::GetFullPath($CodexHome)
$target = [System.IO.Path]::GetFullPath((Join-Path $codexHomeFull "vse-relay.config.toml"))
if (-not $target.StartsWith($codexHomeFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved relay profile path escapes CODEX_HOME."
}

$content = @'
model = "GPT-5.6 SOL"
model_provider = "vse_relay"

[model_providers.vse_relay]
name = "VSE temporary Responses relay"
base_url = "https://node-cf.sssaicodeapi.com/api/v1"
env_key = "CODEX_RELAY_API_KEY"
wire_api = "responses"
request_max_retries = 2
stream_max_retries = 4
stream_idle_timeout_ms = 300000
'@ + [Environment]::NewLine

if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "Relay profile is not installed: $target"
    }
    $current = [System.IO.File]::ReadAllText($target)
    if ($current -ne $content) {
        throw "Relay profile exists but does not match the approved configuration: $target"
    }
    Write-Output "Relay profile is installed and matches the approved configuration: $target"
    return
}

if (-not (Test-Path -LiteralPath $codexHomeFull -PathType Container)) {
    if ($PSCmdlet.ShouldProcess($codexHomeFull, "Create CODEX_HOME directory")) {
        New-Item -ItemType Directory -Path $codexHomeFull | Out-Null
    }
}

if (Test-Path -LiteralPath $target -PathType Leaf) {
    $current = [System.IO.File]::ReadAllText($target)
    if ($current -eq $content) {
        Write-Output "Relay profile already matches the approved configuration: $target"
        return
    }
    if (-not $Force) {
        throw "Relay profile already exists with different content. Re-run with -Force to create a timestamped backup and replace it."
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$target.backup-$stamp"
    if ($PSCmdlet.ShouldProcess($backup, "Back up existing relay profile")) {
        Copy-Item -LiteralPath $target -Destination $backup
    }
}

$temporary = "$target.tmp-$PID"
try {
    if ($PSCmdlet.ShouldProcess($target, "Install VSE temporary relay profile")) {
        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($temporary, $content, $utf8NoBom)
        Move-Item -LiteralPath $temporary -Destination $target -Force
    }
}
finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Force
    }
}

Write-Output "Installed relay profile without storing an API key: $target"
