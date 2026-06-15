param(
    [string]$ReviewDir = "tmp\target-preview-review\v5.2.296-awaiting-target-review-69",
    [string]$SelectionJson = "",
    [string]$VideoDir = "C:\Users\qihq\Pictures\skate testing video",
    [string]$Label = "v5.2.302-reviewed-target-apply",
    [switch]$DryRunOnly,
    [switch]$SkipDiagnostics
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$reviewJson = Join-Path $ReviewDir "target-preview-review.json"
$selectionJson = if ($SelectionJson) { $SelectionJson } else { Join-Path $ReviewDir "target-selection-reviewed.json" }

if (-not (Test-Path -LiteralPath $reviewJson)) {
    throw "Missing review JSON: $reviewJson"
}
if (-not (Test-Path -LiteralPath $selectionJson)) {
    $candidateDirs = @(
        $ReviewDir,
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "Documents")
    )
    $candidates = @()
    $searchedDirs = @()
    foreach ($dir in $candidateDirs) {
        if (-not (Test-Path -LiteralPath $dir)) {
            continue
        }
        $searchedDirs += $dir
        $candidates += Get-ChildItem -LiteralPath $dir -File -Filter "target-selection-reviewed*.json" -ErrorAction SilentlyContinue
    }
    $candidates = $candidates | Sort-Object LastWriteTime -Descending
    if ($candidates.Count -eq 1) {
        $selectionJson = $candidates[0].FullName
        Write-Host "Using reviewed target selection JSON: $selectionJson"
    } elseif ($candidates.Count -gt 1) {
        $paths = ($candidates | Select-Object -First 10 | ForEach-Object { $_.FullName }) -join "`n"
        throw "Missing reviewed target selection JSON at $selectionJson and found multiple candidates. Re-run with -SelectionJson:`n$paths"
    } else {
        $searched = ($searchedDirs | ForEach-Object { "  - $_" }) -join "`n"
        $reviewPage = Join-Path $ReviewDir "index.html"
        throw @"
Missing reviewed target selection JSON.

Expected:
  $selectionJson

Also searched for:
  target-selection-reviewed*.json

In:
$searched

Open the review page, select every row until it says Complete, then download/save target-selection-reviewed.json:
  $reviewPage

If the file is somewhere else, rerun with:
  powershell -ExecutionPolicy Bypass -File .\scripts\apply_reviewed_target_selection_v5.2.300.ps1 -SelectionJson "C:\path\to\target-selection-reviewed.json"
"@
    }
}

python scripts\apply_target_selection_reviews.py `
    --review-json $reviewJson `
    --target-selection-json $selectionJson `
    --video-dir $VideoDir `
    --output-dir tmp\api-batch-skate-analysis `
    --label "$Label-dry-run" `
    --poll-seconds 10 `
    --max-wait-seconds 900 `
    --require-complete `
    --require-completed `
    --dry-run

if ($DryRunOnly) {
    exit 0
}

python scripts\apply_target_selection_reviews.py `
    --review-json $reviewJson `
    --target-selection-json $selectionJson `
    --video-dir $VideoDir `
    --output-dir tmp\api-batch-skate-analysis `
    --label $Label `
    --poll-seconds 10 `
    --max-wait-seconds 900 `
    --require-complete `
    --require-completed

if ($SkipDiagnostics) {
    exit 0
}

$batchJson = Join-Path "tmp\api-batch-skate-analysis" "$Label.json"
$diagnosticsLabel = "$Label-diagnostics"
$diagnosticsJson = Join-Path "tmp\api-batch-skate-analysis" "$diagnosticsLabel.json"
$goalJson = Join-Path "tmp\api-batch-skate-analysis" "$Label-goal-progress.json"
$goalMd = Join-Path "tmp\api-batch-skate-analysis" "$Label-goal-progress.md"

if (-not (Test-Path -LiteralPath $batchJson)) {
    throw "Expected apply output JSON was not created: $batchJson"
}

python scripts\summarize_api_batch_diagnostics.py $batchJson `
    --output-dir tmp\api-batch-skate-analysis `
    --label $diagnosticsLabel `
    --refresh-target-preview `
    --timeout 180

if (-not (Test-Path -LiteralPath $diagnosticsJson)) {
    throw "Expected diagnostics JSON was not created: $diagnosticsJson"
}

python scripts\summarize_goal_progress.py $batchJson $diagnosticsJson `
    --latest-by-video `
    --threshold 0.1 `
    --frontend-url http://localhost:8080 `
    --output-json $goalJson `
    --output-md $goalMd
