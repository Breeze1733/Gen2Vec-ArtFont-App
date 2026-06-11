$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "run-small-acceptance.ps1"
& $Script -Suite smoke2 @args
exit $LASTEXITCODE
