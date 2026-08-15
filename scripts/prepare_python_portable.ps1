# scripts/prepare_python_portable.ps1
# Download the official Windows embeddable Python package and enable pip.
#
# The installer ships this lean runtime. PyBibX / PyTorch / transformers are
# downloaded during install (or on first launch) via bootstrap_runtime.ps1.
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\prepare_python_portable.ps1

[CmdletBinding()]
param(
    [string]$PythonVersion = "3.12.10"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$TargetDir = Join-Path $Root "Python-Portable"
$ZipName = "python-$PythonVersion-embed-amd64.zip"
$ZipUrl = "https://www.python.org/ftp/python/$PythonVersion/$ZipName"
$ZipPath = Join-Path $env:TEMP $ZipName
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$GetPipPath = Join-Path $env:TEMP "get-pip-pybibx.py"

Write-Host "==> Preparing Python-Portable ($PythonVersion embeddable amd64)"

if (Test-Path (Join-Path $TargetDir "python.exe")) {
    Write-Host "Python-Portable already present at $TargetDir"
} else {
    Write-Host "Downloading $ZipUrl ..."
    Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing

    if (Test-Path $TargetDir) {
        Remove-Item -LiteralPath $TargetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $TargetDir | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $TargetDir -Force
    Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
}

$python = Join-Path $TargetDir "python.exe"
if (-not (Test-Path $python)) {
    throw "python.exe missing after extract: $python"
}

# Enable site-packages / pip for the embeddable distribution.
$pthFiles = Get-ChildItem -Path $TargetDir -Filter "python*._pth"
if (-not $pthFiles) {
    throw "No python*._pth file found in $TargetDir"
}
foreach ($pth in $pthFiles) {
    $lines = Get-Content -LiteralPath $pth.FullName
    $updated = @()
    $hasSitePackages = $false
    $hasImportSite = $false
    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ($trimmed -match '^(#\s*)?Lib[\\/]+site-packages$') {
            $hasSitePackages = $true
            $updated += "Lib/site-packages"
            continue
        }
        if ($trimmed -eq "import site" -or $trimmed -eq "#import site") {
            $hasImportSite = $true
            $updated += "import site"
            continue
        }
        # Drop accidental double-backslash paths from older script runs.
        if ($trimmed -eq "Lib\\site-packages") {
            $hasSitePackages = $true
            $updated += "Lib/site-packages"
            continue
        }
        $updated += $line
    }
    if (-not $hasSitePackages) {
        $updated += "Lib/site-packages"
    }
    if (-not $hasImportSite) {
        $updated += "import site"
    }
    # ASCII, LF-friendly content for the embeddable ._pth parser.
    [System.IO.File]::WriteAllLines($pth.FullName, $updated)
    Write-Host "Updated $($pth.Name) for site-packages + import site"
}

$sitePackages = Join-Path $TargetDir "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

# Ensure pip exists. (Embeddable Python has no pip until get-pip.py runs.)
$pipOk = $false
try {
    $pipProbe = & $python -m pip --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pipOk = $true
        Write-Host "pip already available: $pipProbe"
    }
} catch {
    $pipOk = $false
}

if (-not $pipOk) {
    Write-Host "Bootstrapping pip via get-pip.py ..."
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath -UseBasicParsing
    & $python $GetPipPath --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        throw "get-pip.py failed with exit code $LASTEXITCODE"
    }
    Remove-Item -Force $GetPipPath -ErrorAction SilentlyContinue
}

& $python -m pip install --upgrade pip setuptools wheel --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE"
}

$versionFile = Join-Path $TargetDir "PYTHON_VERSION.txt"
Set-Content -LiteralPath $versionFile -Value $PythonVersion -Encoding ascii

Write-Host ""
Write-Host "Python-Portable ready:"
Write-Host "  $python"
Write-Host "  (pybibx / torch are installed later by bootstrap_runtime.ps1)"
