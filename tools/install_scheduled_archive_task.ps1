[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = "VSE Toolbox Scheduled Archive",
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
$arguments = '"{0}" scheduled-archive --once' -f $resolvedMain
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
    "Runs one fixed-contract VSE archive pass every 60 minutes as the " +
    "current Windows user so Credential Manager references remain user-scoped."
)
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description

if ($PSCmdlet.ShouldProcess($TaskName, "Register scheduled archive task for $currentUser")) {
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
