# scripts/bake_critical_packages.ps1
# Pre-install pybibx + core web UI libraries into .\Python-Portable so the
# Windows setup exe ships them (faster install / first launch). Torch and other
# AI wheels stay out of the bake and install on first run in the background.
#
# Prerequisites:
#   - Python-Portable prepared (scripts/prepare_python_portable.ps1)
#   - Internet access to download wheels from PyPI
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\bake_critical_packages.ps1

[CmdletBinding()]
param(
    [string]$AppDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AppDir)) {
    $AppDir = Resolve-Path (Join-Path $PSScriptRoot "..")
}
$AppDir = [System.IO.Path]::GetFullPath($AppDir.TrimEnd('\', '/'))
$Python = Join-Path $AppDir "Python-Portable\python.exe"
$PkgFile = Join-Path $PSScriptRoot "critical_packages.txt"
$UiMarker = Join-Path $AppDir "Python-Portable\runtime_ui_ready.txt"
$BakeMarker = Join-Path $AppDir "Python-Portable\BAKED_CRITICAL.txt"

if (-not (Test-Path $Python)) {
    throw "Python-Portable not found at $Python. Run prepare_python_portable.ps1 first."
}
if (-not (Test-Path $PkgFile)) {
    throw "Missing package list: $PkgFile"
}

$packages = Get-Content -LiteralPath $PkgFile |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }

if (-not $packages) {
    throw "No packages listed in $PkgFile"
}

$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "==> Baking pybibx (--no-deps) into Python-Portable..."
& $Python -m pip install --upgrade --prefer-binary pybibx --no-deps --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "pip install pybibx --no-deps failed with exit code $LASTEXITCODE"
}

Write-Host "==> Baking critical packages ($($packages.Count))..."
Write-Host ("    " + ($packages -join ", "))
& $Python -m pip install --upgrade --prefer-binary @packages --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "Critical package bake failed with exit code $LASTEXITCODE"
}

Write-Host "==> Verifying web UI import..."
& $Python -c "import pybibx; from pybibx.base import app; print('bake-ok', pybibx.__name__)"
if ($LASTEXITCODE -ne 0) {
    throw "Bake verification failed: web UI import still broken."
}

Write-Host "==> Byte-compiling site-packages..."
& $Python -m compileall -q (Join-Path $AppDir "Python-Portable\Lib\site-packages")
# compileall may return non-zero on some noisy modules; do not fail the bake.

$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Set-Content -LiteralPath $UiMarker -Value $stamp -Encoding ascii
@(
    "baked=$stamp"
    "python=$(& $Python -c "import sys; print(sys.version.split()[0])")"
    "packages=pybibx(--no-deps),$($packages -join ',')"
) | Set-Content -LiteralPath $BakeMarker -Encoding ascii

Write-Host ""
Write-Host "Critical bake complete:"
Write-Host "  $BakeMarker"
Write-Host "  (Torch / transformers / BERTopic are NOT baked - first-launch background install.)"
