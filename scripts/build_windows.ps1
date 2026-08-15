# scripts/build_windows.ps1
# Prepare Python-Portable, build the onedir launcher, and compile the Inno Setup installer.
#
# Prerequisites:
#   - Python with PyInstaller (pip install -r requirements-build.txt) for packaging the launcher
#   - Inno Setup 7+ (ISCC.exe) preferred; 6+ also works
#   - Internet access to download the embeddable Python runtime
#
# The setup exe stays relatively small: heavy AI wheels download during install
# (or on first launch) via scripts/bootstrap_runtime.ps1.
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -SkipPreparePython
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -SkipInstaller

[CmdletBinding()]
param(
    [switch]$SkipPreparePython,
    [switch]$SkipInstaller,
    [string]$PythonVersion = "3.12.10"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Find-ISCC {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Get-Command $path -ErrorAction SilentlyContinue) {
            return (Get-Command $path).Source
        }
        if (Test-Path $path) {
            return $path
        }
    }

    $searchRoots = @(
        (Join-Path $env:LOCALAPPDATA "Programs"),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($searchRoot in $searchRoots) {
        $hit = Get-ChildItem -Path $searchRoot -Directory -Filter "Inno Setup *" -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "ISCC.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $null
}

if (-not $SkipPreparePython) {
    Write-Host "==> Preparing lean Python-Portable..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\prepare_python_portable.ps1") -PythonVersion $PythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "prepare_python_portable.ps1 failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "==> Skipping Python-Portable prepare (-SkipPreparePython)"
    if (-not (Test-Path (Join-Path $Root "Python-Portable\python.exe"))) {
        throw "Python-Portable\python.exe not found. Run without -SkipPreparePython first."
    }
}

Write-Host "==> Installing/upgrading PyInstaller..."
python -m pip install --upgrade -r (Join-Path $Root "requirements-build.txt")

Write-Host "==> Building onedir launcher (run_pybibx.exe + _internal)..."
$distAppDir = Join-Path $Root "dist\run_pybibx"
$exeBuilt = Join-Path $distAppDir "run_pybibx.exe"
$exeRoot = Join-Path $Root "run_pybibx.exe"
$internalRoot = Join-Path $Root "_internal"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --name run_pybibx `
    --icon (Join-Path $Root "app_icon.ico") `
    (Join-Path $Root "run_pybibx.py")

if (-not (Test-Path $exeBuilt)) {
    throw "PyInstaller did not produce $exeBuilt"
}

if (Test-Path $internalRoot) {
    Remove-Item -LiteralPath $internalRoot -Recurse -Force
}
Copy-Item -Force $exeBuilt $exeRoot
Copy-Item -Recurse -Force (Join-Path $distAppDir "_internal") $internalRoot
Write-Host "Staged launcher at $exeRoot (with _internal\)"

if ($SkipInstaller) {
    Write-Host "==> Skipping Inno Setup (-SkipInstaller)"
    Write-Host "Done."
    exit 0
}

$iscc = Find-ISCC
if (-not $iscc) {
    throw "Inno Setup (ISCC.exe) not found. Install Inno Setup 7+ (or 6+) or pass -SkipInstaller."
}

Write-Host "==> Compiling installer with $iscc ..."
& $iscc (Join-Path $Root "installer_config.iss")
if ($LASTEXITCODE -ne 0) {
    throw "ISCC failed with exit code $LASTEXITCODE"
}

$version = (Get-Content (Join-Path $Root "version.txt") -Raw).Trim()
$setup = Join-Path $Root "Output\PyBibXSetup_$version.exe"
if (-not (Test-Path $setup)) {
    throw "Expected installer not found: $setup"
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  Launcher : $exeRoot"
Write-Host "  Installer: $setup"
Write-Host ""
Write-Host "Note: the setup exe downloads pybibx/torch during install (internet required)."
Write-Host "Next: test on a clean Windows account, then upload the installer to GitHub Releases."
