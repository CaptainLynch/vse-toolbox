# Fix IM channel model: cn:deepseek-v4-flash (retired) -> cn:deepseek-v4.1-flash
# Usage: fully quit the DSH desktop app first, run this script, then start the app again.
# Idempotent: channels already on the new model are skipped. Any failure leaves the file untouched.
param(
    [string]$StateFile = (Join-Path $env:USERPROFILE '.dsh\dsh-im-connect\channels.json'),
    [string]$OldModel  = 'cn:deepseek-v4-flash',
    [string]$NewModel  = 'cn:deepseek-v4.1-flash',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $StateFile)) { throw "state file not found: $StateFile" }

$raw = Get-Content $StateFile -Raw -Encoding utf8
$data = $raw | ConvertFrom-Json
if (-not $data.channels) { throw 'channels.json has no channels field' }

$changed = @()
foreach ($prop in $data.channels.PSObject.Properties) {
    $ch = $prop.Value
    if ($ch.assistant -and $ch.assistant.model -eq $OldModel) {
        $ch.assistant.model = $NewModel
        $changed += ("{0}: {1} -> {2}" -f $prop.Name, $OldModel, $NewModel)
    }
}

if ($changed.Count -eq 0) { Write-Output 'nothing to fix: every channel already uses the new model'; exit 0 }
$changed | ForEach-Object { Write-Output ("  will change " + $_) }

if ($DryRun) { Write-Output 'dry run: nothing written'; exit 0 }

$backup = "$StateFile.bak-model-$(Get-Date -Format yyyyMMdd-HHmmss)"
Copy-Item $StateFile $backup -Force
Write-Output ("backup written: " + $backup)

$json = $data | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($StateFile, $json, (New-Object System.Text.UTF8Encoding($false)))

$check = Get-Content $StateFile -Raw -Encoding utf8 | ConvertFrom-Json
$bad = @()
foreach ($prop in $check.channels.PSObject.Properties) {
    if ($prop.Value.assistant.model -eq $OldModel) { $bad += $prop.Name }
}
if ($bad.Count -gt 0) { throw ("still on old model after write: " + ($bad -join ', ')) }
Write-Output ("done: all channels now use " + $NewModel)
