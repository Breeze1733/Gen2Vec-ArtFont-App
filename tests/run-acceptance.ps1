param(
  [ValidateSet("acceptance")]
  [string]$Suite = "acceptance",
  [string]$CliPath = "",
  [string]$OutputRoot = "",
  [string]$Resolution = "1280 x 720",
  [ValidateSet("clean", "balanced", "detailed", "ultra")]
  [string]$VectorPreset = "balanced",
  [int]$Wait = 30,
  [int]$Seed = 0,
  [int]$SeedStep = 1,
  [string]$Negative = "low quality, blurry, wrong text, missing character, extra character, garbled letters, busy background, human figure, watermark",
  [int]$MaxFailures = 0,
  [int]$MaxE2eMs = 0,
  [int]$MaxVectorMs = 0,
  [switch]$NoVectorize,
  [switch]$DryRun,
  [string]$VerifyOnly = "",
  [switch]$AllowResolutionMismatch,
  [switch]$StrictSvgGroups,
  [switch]$SkipHealth
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

function Get-SuiteConfig {
  param([string]$Name)
  $fixture = Join-Path $ScriptDir "acceptance.txt"
  if (-not (Test-Path -LiteralPath $fixture)) {
    $fixture = Join-Path $ScriptDir "fixtures\acceptance.txt"
  }
  switch ($Name) {
    "acceptance" {
      return @{
        Label = "acceptance"
        Fixture = $fixture
        ExpectedRows = 0
        MinRows = 100
        Seed = 2026061201
        TimeoutMinutes = 270
        OutputRoot = "outputs\cli-acceptance"
      }
    }
  }
}

function Resolve-AbsolutePath {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
  if ([System.IO.Path]::IsPathRooted($Value)) { return $Value }
  return (Join-Path $RepoRoot $Value)
}

function Resolve-CliExecutable {
  param([string]$ExplicitPath)

  if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
    $resolved = Resolve-AbsolutePath $ExplicitPath
    if (Test-Path -LiteralPath $resolved) { return (Resolve-Path -LiteralPath $resolved).Path }
    throw "CLI not found: $ExplicitPath"
  }

  $candidates = @(
    (Join-Path $ScriptDir "..\gen2vec_cli.exe"),
    (Join-Path $ScriptDir "..\gen2vec-cli.exe"),
    (Join-Path $ScriptDir "gen2vec_cli.exe"),
    (Join-Path $ScriptDir "gen2vec-cli.exe"),
    (Join-Path $RepoRoot "gen2vec_cli.exe"),
    (Join-Path $RepoRoot "gen2vec-cli.exe"),
    (Join-Path $RepoRoot "apps\cli\dist\gen2vec_cli.exe")
  )

  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
  }

  foreach ($name in @("gen2vec_cli.exe", "gen2vec-cli.exe")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
  }

  throw "gen2vec_cli.exe was not found. Run this script from the install directory, or pass -CliPath."
}

function Test-LiteralPathExists {
  param([string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
  return Test-Path -LiteralPath $Path
}

function Split-PromptLine {
  param([string]$Line)
  $lineText = $Line.Replace([string][char]0xFEFF, "").Replace([string][char]0xFF5C, "|").Replace("`t|", "|").Replace("|`t", "|").Trim()
  if ([string]::IsNullOrWhiteSpace($lineText) -or $lineText.StartsWith("#")) { return $null }

  if ($lineText.Contains("|")) {
    $parts = $lineText -split "\|", 5
  } elseif ($lineText.Contains("`t")) {
    $parts = $lineText -split "`t", 5
  } else {
    $parts = @($lineText)
  }

  while ($parts.Count -lt 5) { $parts += "" }
  return [PSCustomObject]@{
    Text = $parts[0].Trim()
    Prompt = $parts[1].Trim()
    Negative = $parts[2].Trim()
    Seed = $parts[3].Trim()
    Resolution = $parts[4].Trim()
  }
}

function New-PreparedFixture {
  param(
    [string]$FixturePath,
    [string]$PreparedPath,
    [hashtable]$Config
  )

  if (-not (Test-LiteralPathExists $FixturePath)) { throw "Fixture not found: $FixturePath" }
  $rows = @()
  foreach ($line in Get-Content -LiteralPath $FixturePath -Encoding UTF8) {
    $row = Split-PromptLine $line
    if ($null -ne $row -and (-not [string]::IsNullOrWhiteSpace($row.Text) -or -not [string]::IsNullOrWhiteSpace($row.Prompt))) {
      $rows += $row
    }
  }

  if ($Config.ExpectedRows -gt 0 -and $rows.Count -ne $Config.ExpectedRows) {
    throw "$($Config.Label) expected $($Config.ExpectedRows) rows, got $($rows.Count)."
  }
  if ($rows.Count -ge $Config.MinRows) {
    Write-Host "$($Config.Label) row count ok: $($rows.Count) rows, minimum is $($Config.MinRows)." -ForegroundColor Green
  }

  New-Item -ItemType Directory -Path (Split-Path -Parent $PreparedPath) -Force | Out-Null
  $outLines = foreach ($row in $rows) {
    $parts = @($row.Text, $row.Prompt, $row.Negative, $row.Seed, $row.Resolution)
    while ($parts.Count -gt 2 -and [string]::IsNullOrWhiteSpace($parts[$parts.Count - 1])) {
      $parts = $parts[0..($parts.Count - 2)]
    }
    $parts -join " | "
  }
  [System.IO.File]::WriteAllLines($PreparedPath, $outLines, [System.Text.UTF8Encoding]::new($false))
  return $rows
}

function Format-CommandLine {
  param([string]$Exe, [string[]]$Args)
  $quotedArgs = $Args | ForEach-Object {
    if ($_ -match "\s") { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
  }
  return '"' + $Exe + '" ' + ($quotedArgs -join " ")
}

function Wait-BackendHealth {
  param([string]$CliExe, [int]$Seconds)
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    & $CliExe "health" *> $null
    if ($LASTEXITCODE -eq 0) {
    Write-Host "Backend health check passed." -ForegroundColor Green
      return
    }
    Start-Sleep -Seconds 1
  } while ((Get-Date) -lt $deadline)

  throw "Backend health check failed. Start the desktop app first, or start txt2img-api:9001 and vectorizer-api:8000 manually."
}

function Get-LatestSummary {
  param([string]$Root)
  $summary = Get-ChildItem -LiteralPath $Root -Recurse -Filter "batch_summary.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $summary) { throw "batch_summary.csv not found: $Root" }
  return $summary.FullName
}

function Read-UInt32BE {
  param([byte[]]$Bytes, [int]$Offset)
  return (([uint32]$Bytes[$Offset] -shl 24) -bor ([uint32]$Bytes[$Offset + 1] -shl 16) -bor ([uint32]$Bytes[$Offset + 2] -shl 8) -bor [uint32]$Bytes[$Offset + 3])
}

function Read-PngInfo {
  param([string]$Path)
  $bytes = [System.IO.File]::ReadAllBytes($Path)
  $signature = [byte[]](0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
  if ($bytes.Length -lt 33) { throw "PNG file is too small: $Path" }
  for ($i = 0; $i -lt $signature.Length; $i++) {
    if ($bytes[$i] -ne $signature[$i]) { throw "Invalid PNG: $Path" }
  }

  $hasTrns = $false
  $offset = 8
  while ($offset + 12 -le $bytes.Length) {
    $length = Read-UInt32BE $bytes $offset
    $type = [System.Text.Encoding]::ASCII.GetString($bytes, $offset + 4, 4)
    if ($type -eq "tRNS") { $hasTrns = $true }
    $next = $offset + 12 + [int]$length
    if ($next -le $offset -or $next -gt $bytes.Length + 12) { break }
    $offset = $next
  }

  $width = Read-UInt32BE $bytes 16
  $height = Read-UInt32BE $bytes 20
  $colorType = [int]$bytes[25]
  return [PSCustomObject]@{
    Width = $width
    Height = $height
    HasAlpha = ($colorType -eq 4 -or $colorType -eq 6 -or $hasTrns)
  }
}

function Get-ResolutionObject {
  param([string]$Value)
  if ($Value -notmatch "(\d+)\D+(\d+)") { return $null }
  return [PSCustomObject]@{ Width = [int]$Matches[1]; Height = [int]$Matches[2] }
}

function Get-QwenMappedResolution {
  param([object]$Resolution)
  if (-not $Resolution -or $Resolution.Height -le 0) { return $null }
  $official = @(
    [PSCustomObject]@{ Width = 1328; Height = 1328 },
    [PSCustomObject]@{ Width = 1664; Height = 928 },
    [PSCustomObject]@{ Width = 928; Height = 1664 },
    [PSCustomObject]@{ Width = 1472; Height = 1104 },
    [PSCustomObject]@{ Width = 1104; Height = 1472 },
    [PSCustomObject]@{ Width = 1584; Height = 1056 },
    [PSCustomObject]@{ Width = 1056; Height = 1584 }
  )
  $ratio = [double]$Resolution.Width / [double]$Resolution.Height
  return $official |
    Sort-Object @{ Expression = { [Math]::Abs(([double]$_.Width / [double]$_.Height) - $ratio) } } |
    Select-Object -First 1
}

function Test-SizeEquals {
  param([object]$Png, [object]$Resolution)
  return $Resolution -and $Png.Width -eq $Resolution.Width -and $Png.Height -eq $Resolution.Height
}

function Add-ResolutionFinding {
  param(
    [System.Collections.Generic.List[string]]$Failures,
    [System.Collections.Generic.List[string]]$Warnings,
    [string]$Label,
    [string]$FileName,
    [object]$Png,
    [object]$Resolution
  )

  if (-not $Resolution -or (Test-SizeEquals $Png $Resolution)) { return }

  $mapped = Get-QwenMappedResolution $Resolution
  $message = "$Label $FileName size $($Png.Width)x$($Png.Height) does not match requested $($Resolution.Width)x$($Resolution.Height)"
  if ($mapped -and (Test-SizeEquals $Png $mapped)) {
    Add-Warning $Warnings "$message; accepted as Qwen official mapped size $($mapped.Width)x$($mapped.Height)."
  } elseif ($AllowResolutionMismatch) {
    Add-Warning $Warnings $message
  } else {
    Add-Failure $Failures $message
  }
}

function Resolve-ArtifactPath {
  param([string]$Value, [string]$SummaryPath)
  if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
  if ([System.IO.Path]::IsPathRooted($Value)) { return $Value }
  return Join-Path (Split-Path -Parent $SummaryPath) $Value
}

function Read-RunLog {
  param([string]$Path)
  $map = @{}
  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $idx = $line.IndexOf("=")
    if ($idx -gt 0) {
      $map[$line.Substring(0, $idx)] = $line.Substring($idx + 1)
    }
  }
  return $map
}

function Add-Failure {
  param([System.Collections.Generic.List[string]]$Failures, [string]$Message)
  $Failures.Add($Message) | Out-Null
}

function Add-Warning {
  param([System.Collections.Generic.List[string]]$Warnings, [string]$Message)
  $Warnings.Add($Message) | Out-Null
}

function Test-AcceptanceArtifacts {
  param(
    [string]$SummaryPath,
    [array]$ExpectedRows,
    [hashtable]$Config
  )

  $failures = [System.Collections.Generic.List[string]]::new()
  $warnings = [System.Collections.Generic.List[string]]::new()
  $rows = @(Import-Csv -LiteralPath $SummaryPath -Encoding UTF8)
  $resolution = Get-ResolutionObject $Resolution

  if ($rows.Count -ne $ExpectedRows.Count) {
    Add-Failure $failures "Summary CSV row count should be $($ExpectedRows.Count), got $($rows.Count): $SummaryPath"
  }

  $failedRows = @($rows | Where-Object { $_.status -eq "failed" -or -not [string]::IsNullOrWhiteSpace($_.error) })
  if ($failedRows.Count -gt $MaxFailures) {
    Add-Failure $failures "Failed row count $($failedRows.Count) exceeds threshold $MaxFailures"
  }

  $allowedStatuses = @("success", "degraded")
  for ($i = 0; $i -lt $rows.Count; $i++) {
    $row = $rows[$i]
    $expected = if ($i -lt $ExpectedRows.Count) { $ExpectedRows[$i] } else { $null }
    if ($row.status -ne "failed" -and $allowedStatuses -notcontains $row.status) {
      Add-Failure $failures "[$($i + 1)] status $($row.status) is not allowed: success,degraded"
    }
    if ($expected -and $row.text -ne $expected.Text) {
      Add-Failure $failures "[$($i + 1)] summary text mismatch: $($row.text) != $($expected.Text)"
    }
  }

  for ($i = 0; $i -lt $rows.Count; $i++) {
    $row = $rows[$i]
    $label = "[$($i + 1)] $($row.text)"
    $taskDir = Resolve-ArtifactPath $row.task_dir $SummaryPath
    $paths = @{
      original = Resolve-ArtifactPath $row.original_path $SummaryPath
      transparent = Resolve-ArtifactPath $row.transparent_path $SummaryPath
      svg = Resolve-ArtifactPath $row.result_svg_path $SummaryPath
      preview = Resolve-ArtifactPath $row.preview_path $SummaryPath
      metadata = Resolve-ArtifactPath $row.metadata_path $SummaryPath
      log = Resolve-ArtifactPath $row.run_log_path $SummaryPath
      workflowApi = Join-Path $taskDir "workflows\workflow_api.json"
      workflowNodes = Join-Path $taskDir "workflows\nodes.md"
      modelDependencies = Join-Path $taskDir "workflows\model_dependencies.json"
    }

    $required = if ($NoVectorize) {
      @("original", "metadata", "log", "workflowApi", "modelDependencies")
    } else {
      @("original", "transparent", "svg", "preview", "metadata", "log", "workflowApi", "modelDependencies")
    }

    foreach ($key in $required) {
      $pathValue = $paths[$key]
      if ([string]::IsNullOrWhiteSpace($pathValue) -or -not (Test-LiteralPathExists $pathValue)) {
        Add-Failure $failures "$label missing artifact: $key ($pathValue)"
      } elseif ((Get-Item -LiteralPath $pathValue).Length -le 0) {
        Add-Failure $failures "$label empty file: $key ($pathValue)"
      }
    }
    if (-not (Test-LiteralPathExists $paths.workflowNodes)) {
      Add-Warning $warnings "$label missing optional workflowNodes ($($paths.workflowNodes))"
    }

    if (Test-LiteralPathExists $paths.original) {
      try {
        $png = Read-PngInfo $paths.original
        Add-ResolutionFinding $failures $warnings $label "original.png" $png $resolution
      } catch {
        Add-Failure $failures "$label original.png validation failed: $($_.Exception.Message)"
      }
    }

    if (-not $NoVectorize -and (Test-LiteralPathExists $paths.transparent)) {
      try {
        $png = Read-PngInfo $paths.transparent
        if (-not $png.HasAlpha) { Add-Failure $failures "$label transparent.png missing alpha channel" }
        Add-ResolutionFinding $failures $warnings $label "transparent.png" $png $resolution
      } catch {
        Add-Failure $failures "$label transparent.png validation failed: $($_.Exception.Message)"
      }
    }

    if (-not $NoVectorize -and (Test-LiteralPathExists $paths.preview)) {
      try {
        [void](Read-PngInfo $paths.preview)
      } catch {
        Add-Failure $failures "$label preview.png validation failed: $($_.Exception.Message)"
      }
    }

    if (-not $NoVectorize -and (Test-LiteralPathExists $paths.svg)) {
      $svg = Get-Content -LiteralPath $paths.svg -Raw -Encoding UTF8
      try {
        $svgDocument = [xml]$svg
        [void]$svgDocument
      } catch {
        Add-Failure $failures "$label SVG XML validation failed: $($_.Exception.Message)"
      }
      if ($svg -notmatch "<svg[\s>]") { Add-Failure $failures "$label result.svg missing <svg> root element" }
      if ($svg -notmatch "viewBox=") { Add-Warning $warnings "$label result.svg missing viewBox" }
      if ($svg -match "<image[\s>]" -or $svg -match "data:image/[^;]+;base64") {
        Add-Failure $failures "$label result.svg contains bitmap <image> or base64 data"
      }
      if ($svg -notmatch "<(path|polygon|polyline|rect|circle|ellipse)\b") {
        Add-Failure $failures "$label result.svg missing editable vector elements"
      }
      if ($svg -notmatch "<g[\s>]") {
        $message = "$label result.svg has no <g> group"
        if ($StrictSvgGroups) { Add-Failure $failures $message } else { Add-Warning $warnings $message }
      }
    }

    $metadata = $null
    if (Test-LiteralPathExists $paths.metadata) {
      try {
        $metadata = Get-Content -LiteralPath $paths.metadata -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $metadata.schema_version) { Add-Failure $failures "$label metadata.json missing schema_version" }
        if ($metadata.generation.text -and $row.text -and $metadata.generation.text -ne $row.text) {
          Add-Failure $failures "$label metadata.generation.text mismatch"
        }
      } catch {
        Add-Failure $failures "$label metadata.json is not valid JSON: $($_.Exception.Message)"
      }
    }

    if (Test-LiteralPathExists $paths.log) {
      $runLog = Read-RunLog $paths.log
      if (-not $runLog.ContainsKey("status")) { Add-Failure $failures "$label run.log missing status" }
      $stage1 = 0
      $stage2 = 0
      [void][int]::TryParse([string]$runLog["stage1_ms"], [ref]$stage1)
      [void][int]::TryParse([string]$runLog["stage2_ms"], [ref]$stage2)
      if ($MaxE2eMs -gt 0 -and ($stage1 + $stage2) -gt $MaxE2eMs) {
        Add-Failure $failures "$label end-to-end time $($stage1 + $stage2)ms exceeds $MaxE2eMs ms"
      }
      if (-not $NoVectorize -and $MaxVectorMs -gt 0 -and $stage2 -gt $MaxVectorMs) {
        Add-Failure $failures "$label vectorization time $stage2 ms exceeds $MaxVectorMs ms"
      }
    }

    if (-not $NoVectorize -and $metadata -and $metadata.stats -and $metadata.stats.elapsed_ms) {
      $elapsed = [double]$metadata.stats.elapsed_ms
      if ($MaxVectorMs -gt 0 -and $elapsed -gt $MaxVectorMs) {
        Add-Failure $failures "$label metadata.stats.elapsed_ms $elapsed ms exceeds $MaxVectorMs ms"
      }
    }
  }

  return [PSCustomObject]@{
    Total = $rows.Count
    FailedRows = $failedRows.Count
    Failures = $failures
    Warnings = $warnings
  }
}

$config = Get-SuiteConfig $Suite
if ($Seed -eq 0) { $Seed = $config.Seed }
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
  $OutputRoot = Join-Path $RepoRoot $config.OutputRoot
} else {
  $OutputRoot = Resolve-AbsolutePath $OutputRoot
}

$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runDir = if ([string]::IsNullOrWhiteSpace($VerifyOnly)) {
  Join-Path $OutputRoot "$Suite-$runStamp"
} else {
  Split-Path -Parent (Resolve-AbsolutePath $VerifyOnly)
}
$preparedFixture = Join-Path $runDir "_prepared\$Suite.txt"

Write-Host ""
Write-Host "=== $($config.Label) ($Suite) ===" -ForegroundColor Cyan
Write-Host "Fixture: $($config.Fixture)"
Write-Host "Output dir: $runDir"

$expectedRows = New-PreparedFixture -FixturePath $config.Fixture -PreparedPath $preparedFixture -Config $config
Write-Host "Prepared input: $preparedFixture"
Write-Host "Rows: $($expectedRows.Count)"

if ([string]::IsNullOrWhiteSpace($VerifyOnly)) {
  $confirm = Read-Host "Run batch acceptance test? (y/n)"
  if ($confirm.Trim().ToLowerInvariant() -ne "y") {
    Write-Host "Batch acceptance test cancelled." -ForegroundColor Yellow
    exit 0
  }

  try {
    $cliExe = Resolve-CliExecutable $CliPath
  } catch {
    if ($DryRun) {
      $cliExe = if ([string]::IsNullOrWhiteSpace($CliPath)) { "gen2vec_cli.exe" } else { $CliPath }
      Write-Host "dry-run: CLI not found, printing command with placeholder path: $cliExe" -ForegroundColor Yellow
    } else {
      throw
    }
  }
  Write-Host "CLI: $cliExe"

  $batchArgs = @(
    "batch",
    "--input-file", $preparedFixture,
    "--output-dir", $runDir,
    "--seed", [string]$Seed,
    "--seed-step", [string]$SeedStep,
    "--resolution", $Resolution,
    "--vector-preset", $VectorPreset,
    "--negative", $Negative,
    "--wait", [string]$Wait
  )
  if ($NoVectorize) { $batchArgs += "--no-vectorize" }

  Write-Host "Command: $(Format-CommandLine $cliExe $batchArgs)"
  if ($DryRun) {
    Write-Host "dry-run: CLI was not run and artifacts were not verified." -ForegroundColor Yellow
    exit 0
  }

  if (-not $SkipHealth) {
    Wait-BackendHealth -CliExe $cliExe -Seconds $Wait
  }

  & $cliExe @batchArgs
  if ($LASTEXITCODE -ne 0) {
    throw "CLI batch exited with code $LASTEXITCODE"
  }

  $summaryPath = Get-LatestSummary $runDir
} else {
  $summaryPath = Resolve-AbsolutePath $VerifyOnly
  if (-not (Test-LiteralPathExists $summaryPath)) { throw "batch_summary.csv does not exist: $summaryPath" }
}

$report = Test-AcceptanceArtifacts -SummaryPath $summaryPath -ExpectedRows $expectedRows -Config $config

Write-Host ""
Write-Host "=== Acceptance result ===" -ForegroundColor Cyan
Write-Host "summary: $summaryPath"
Write-Host "Total: $($report.Total)  Failed rows: $($report.FailedRows)  Failures: $($report.Failures.Count)  Warnings: $($report.Warnings.Count)"

$report.Warnings | Select-Object -First 20 | ForEach-Object {
  Write-Host "WARN $_" -ForegroundColor Yellow
}
$report.Failures | Select-Object -First 50 | ForEach-Object {
  Write-Host "FAIL $_" -ForegroundColor Red
}

if ($report.Failures.Count -gt 0) {
  throw "Acceptance failed: $($report.Failures.Count) failures, $($report.Warnings.Count) warnings"
}

Write-Host "PASS $($config.Label)" -ForegroundColor Green
