param(
    [string]$ImageName = "skating-analyzer-allinone",
    [string]$ImageTag = "latest",
    [string]$PipelineVersion = "v5.1.0",
    [string]$OutputDir = ".\\deliverables"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedOutputDir = Join-Path $projectRoot $OutputDir
$fullImageName = "${ImageName}:${ImageTag}"
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
