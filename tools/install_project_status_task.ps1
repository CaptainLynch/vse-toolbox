[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = "VSE Toolbox Project Status Sync",
    [string]$PythonExecutable = "python",
    [string]$Repository = (Split-Path -Parent $PSScriptRoot),
    [string]$ExportPath
)

$mainPath = Join-Path -Path $Repository -ChildPath "main.py"
if (-not (Test-Path -LiteralPath $mainPath -PathType Leaf)) {
    throw "main.py was not found beneath the supplied repository."
}

$resolvedMain = (Resolve-Path -LiteralPath $mainPath).Path
$resolvedRepository = (Resolve-Path -LiteralPath $Repository).Path
$arguments = '"{0}" project-status-sync --once' -f $resolvedMain
$action = New-ScheduledTaskAction -Execute $PythonExecutable -Argument $arguments -WorkingDirectory $resolvedRepository
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 60)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 55) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Runs one credential-safe VSE deliverable sync every 60 minutes."

if ($PSCmdlet.ShouldProcess($TaskName, "Register scheduled task for the current Windows user")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
}

if ($ExportPath) {
    $parent = Split-Path -Parent $ExportPath
    if ($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Export parent directory does not exist."
    }
    Export-ScheduledTask -TaskName $TaskName | Set-Content -LiteralPath $ExportPath -Encoding Unicode
}
