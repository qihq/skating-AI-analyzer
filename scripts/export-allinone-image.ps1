param(
    [string]$ImageName = "skating-analyzer-allinone",
    [string]$ImageTag = "latest",
    [string]$PipelineVersion = "",
    [string]$OutputDir = ".\\deliverables",
    [string]$StableTarName = "skating-analyzer-allinone-latest.tar"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $resolvedOutputDir = $OutputDir
} else {
    $resolvedOutputDir = Join-Path $projectRoot $OutputDir
}
$resolvedOutputDir = [System.IO.Path]::GetFullPath($resolvedOutputDir)
$fullImageName = "${ImageName}:${ImageTag}"
if ([string]::IsNullOrWhiteSpace($PipelineVersion)) {
    $versionFile = Join-Path $projectRoot "backend\\app\\services\\pipeline_version.py"
    $versionText = Get-Content -Raw -LiteralPath $versionFile
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

$stableTarPath = $null
if (-not [string]::IsNullOrWhiteSpace($StableTarName)) {
    if ([System.IO.Path]::IsPathRooted($StableTarName)) {
        $stableTarPath = [System.IO.Path]::GetFullPath($StableTarName)
    } else {
        $stableTarPath = Join-Path $resolvedOutputDir $StableTarName
    }
    Copy-Item -LiteralPath $tarPath -Destination $stableTarPath -Force
}

if (-not (Test-Path -LiteralPath $tarPath -PathType Leaf)) {
    throw "docker save reported success, but tar file is missing: $tarPath"
}
if ($stableTarPath -and -not (Test-Path -LiteralPath $stableTarPath -PathType Leaf)) {
    throw "stable tar copy is missing: $stableTarPath"
}

Write-Host "Done"
Write-Host "Image: $fullImageName"
Write-Host "Tar:   $tarPath"
if ($stableTarPath) {
    Write-Host "Latest: $stableTarPath"
}
