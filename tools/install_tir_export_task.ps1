[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = "VSE Toolbox TIR Export",
    [string]$PythonExecutable = "python",
    [string]$Repository = (Split-Path -Parent $PSScriptRoot),
    [string]$ExportPath
)

# Same shape as install_scheduled_archive_task.ps1: an hourly one-shot pass as the
# current Windows user. Whether a pass actually exports is decided by the plugin's
# auto-export switch and hour (TIR数据简表 page), so the task can stay installed.
$cliPath = Join-Path -Path $Repository -ChildPath "tools\tir_export_cli.py"
if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) {
    throw "tools\tir_export_cli.py was not found beneath the supplied repository."
}

$resolvedCli = (Resolve-Path -LiteralPath $cliPath).Path
$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
$arguments = '"{0}" --once' -f $resolvedCli
$action = New-ScheduledTaskAction `
    -Execute $PythonExecutable `
    -Argument $arguments `
    -WorkingDirectory $resolvedRepository
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 60)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 55) `
    -StartWhenAvailable
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$description = (
    "Runs one TIR report export pass every 60 minutes as the current Windows " +
    "user so the DPAPI domain credential remains user-scoped."
)
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description

if ($PSCmdlet.ShouldProcess($TaskName, "Register TIR export task for $currentUser")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
}

if ($ExportPath) {
    $parent = Split-Path -Parent $ExportPath
    if ($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Export parent directory does not exist."
    }
    Export-ScheduledTask -TaskName $TaskName |
        Set-Content -LiteralPath $ExportPath -Encoding Unicode
}
