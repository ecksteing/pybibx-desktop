# scripts/bootstrap_runtime.ps1
# Install critical pybibx runtime packages into Python-Portable (fast path for the web UI).
# Heavy AI wheels (PyTorch / transformers / BERTopic) are finished on first app launch
# in the background so Setup and first paint stay responsive.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1 -AppDir "C:\...\PyBibX Desktop"
#   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1 -FullAi

[CmdletBinding()]
param(
    [string]$AppDir = "",
    [switch]$FullAi,
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
$UiMarker = Join-Path $AppDir "Python-Portable\runtime_ui_ready.txt"
$AiMarker = Join-Path $AppDir "Python-Portable\runtime_ai_ready.txt"
$ReadyMarker = Join-Path $AppDir "Python-Portable\runtime_ready.txt"
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

$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONIOENCODING = "utf-8"

# Already able to open the web UI?
& $Python -c "import pybibx; from pybibx.base import app" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-BootLog "Web UI already importable; refreshing UI marker."
    Set-Content -LiteralPath $UiMarker -Value ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) -Encoding ascii
} else {
    Write-BootLog "Installing pybibx (no-deps) + critical web UI libraries..."
    & $Python -m pip install --upgrade --prefer-binary pybibx --no-deps --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Write-BootLog "pip install pybibx --no-deps failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    $critical = @(
        "flask", "werkzeug", "plotly", "pandas", "numpy", "matplotlib",
        "scipy", "scikit-learn", "networkx", "Pillow", "chardet", "numba", "wordcloud"
    )
    & $Python -m pip install --upgrade --prefer-binary @critical --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Write-BootLog "Critical package install failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    & $Python -c "import pybibx; from pybibx.base import app; print('ui-ok')"
    if ($LASTEXITCODE -ne 0) {
        Write-BootLog "Web UI import check failed after critical install."
        exit 2
    }
    Set-Content -LiteralPath $UiMarker -Value ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) -Encoding ascii
    Write-BootLog "Critical web UI packages ready."
}

if (-not $FullAi) {
    Write-BootLog "Skipping full AI stack during Setup (installed on first launch in background)."
    exit 0
}

Write-BootLog "FullAi requested — installing Torch + AI libraries..."

if (-not $SkipTorchCpuIndex) {
    & $Python -m pip install --upgrade --prefer-binary torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Write-BootLog "CPU torch install failed (exit $LASTEXITCODE); continuing with default PyPI resolution."
    }
}

$ai = @(
    "bertopic", "bert-extractive-summarizer", "sentence-transformers", "transformers",
    "sentencepiece", "umap-learn", "keybert", "openai", "google-generativeai", "llmx"
)
& $Python -m pip install --upgrade --prefer-binary @ai --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    Write-BootLog "AI package install failed; trying full pybibx resolve..."
    & $Python -m pip install --upgrade --prefer-binary pybibx --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Set-Content -LiteralPath $AiMarker -Value ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) -Encoding ascii
Set-Content -LiteralPath $ReadyMarker -Value ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) -Encoding ascii
Write-BootLog "Bootstrap complete (UI + AI)."
exit 0
