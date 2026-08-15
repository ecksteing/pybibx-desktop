# scripts/bootstrap_runtime.ps1
# Install pybibx and heavy AI dependencies into Python-Portable.
# Used by the Inno Setup installer (during install) and as a manual repair tool.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1 -AppDir "C:\...\PyBibX Desktop"

[CmdletBinding()]
param(
    [string]$AppDir = "",
    [switch]$SkipTorchCpuIndex
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AppDir)) {
    $AppDir = if ($PSScriptRoot) {
        Resolve-Path (Join-Path $PSScriptRoot "..")
    } else {
        Split-Path -Parent $MyInvocation.MyCommand.Path
    }
}
$AppDir = [System.IO.Path]::GetFullPath($AppDir.TrimEnd('\', '/'))
$Python = Join-Path $AppDir "Python-Portable\python.exe"
$Marker = Join-Path $AppDir "Python-Portable\runtime_ready.txt"
$LogDir = Join-Path $env:LOCALAPPDATA "PyBibX Desktop"
$LogFile = Join-Path $LogDir "bootstrap.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-BootLog([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding utf8
    Write-Host $line
}

if (-not (Test-Path $Python)) {
    throw "Bundled Python not found: $Python"
}

Write-BootLog "Bootstrap starting in $AppDir"

# Already usable?
& $Python -c "import pybibx" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-BootLog "pybibx already importable; refreshing marker."
    Set-Content -LiteralPath $Marker -Value ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) -Encoding ascii
    exit 0
}

$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"

if (-not $SkipTorchCpuIndex) {
    Write-BootLog "Installing CPU PyTorch wheels..."
    & $Python -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Write-BootLog "CPU torch install failed (exit $LASTEXITCODE); continuing with default PyPI resolution."
    }
}

Write-BootLog "Installing pybibx and remaining dependencies from PyPI..."
& $Python -m pip install --upgrade pybibx --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    Write-BootLog "pip install pybibx failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

& $Python -c "import pybibx; print(pybibx.__name__)"
if ($LASTEXITCODE -ne 0) {
    Write-BootLog "pybibx import check failed after install."
    exit 2
}

Set-Content -LiteralPath $Marker -Value ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) -Encoding ascii
Write-BootLog "Bootstrap complete."
exit 0
