param(
    [string]$ImageName = "skating-analyzer-allinone",
    [string]$ImageTag = "latest",
    [string]$OutputDir = ".\\dist"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedOutputDir = Join-Path $projectRoot $OutputDir
$fullImageName = "${ImageName}:${ImageTag}"
$tarName = "${ImageName}-${ImageTag}.tar"
$tarPath = Join-Path $resolvedOutputDir $tarName

New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

Write-Host "Building image $fullImageName ..."
docker build -f docker/allinone/Dockerfile -t $fullImageName $projectRoot

Write-Host "Saving image to $tarPath ..."
docker save -o $tarPath $fullImageName

Write-Host "Done"
Write-Host "Image: $fullImageName"
Write-Host "Tar:   $tarPath"
