param(
    [string]$ImageName = "skating-analyzer-allinone",
    [string]$ImageTag = "latest",
    [string]$PipelineVersion = "",
    [string]$OutputDir = ".\\deliverables"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedOutputDir = Join-Path $projectRoot $OutputDir
$fullImageName = "${ImageName}:${ImageTag}"
if ([string]::IsNullOrWhiteSpace($PipelineVersion)) {
    $versionFile = Join-Path $projectRoot "backend\\app\\services\\pipeline_version.py"
    $versionText = Get-Content -Raw -Path $versionFile
    $match = [regex]::Match($versionText, 'CURRENT_PIPELINE_VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Unable to read CURRENT_PIPELINE_VERSION from $versionFile"
    }
    $PipelineVersion = $match.Groups[1].Value
}
$timestamp = Get-Date -Format "yyyyMMdd-HHmm"
$tarName = "${ImageName}-${PipelineVersion}-${timestamp}.tar"
$tarPath = Join-Path $resolvedOutputDir $tarName

New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

Write-Host "Building image $fullImageName ..."
docker build -f docker/allinone/Dockerfile -t $fullImageName $projectRoot
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed with exit code $LASTEXITCODE"
}

Write-Host "Saving image to $tarPath ..."
docker save -o $tarPath $fullImageName
if ($LASTEXITCODE -ne 0) {
    throw "docker save failed with exit code $LASTEXITCODE"
}

Write-Host "Done"
Write-Host "Image: $fullImageName"
Write-Host "Tar:   $tarPath"
