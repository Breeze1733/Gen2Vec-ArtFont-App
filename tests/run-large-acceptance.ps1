$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "run-small-acceptance.ps1"
& $Script -Suite large @args
exit $LASTEXITCODE
