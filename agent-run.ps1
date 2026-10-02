param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Task
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& python (Join-Path $root 'tools/agents/supervisor.py') run ($Task -join ' ')
exit $LASTEXITCODE
