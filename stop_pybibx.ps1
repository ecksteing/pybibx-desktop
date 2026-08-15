# stop_pybibx.ps1
# Stops PyBibX Desktop launcher/Python processes for THIS install only.
# Used before uninstall/upgrade so Python-Portable files are not locked.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\stop_pybibx.ps1
#   powershell -ExecutionPolicy Bypass -File .\stop_pybibx.ps1 -AppDir "C:\...\PyBibX Desktop"

param(
    [string]$AppDir = ""
)

$ErrorActionPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($AppDir)) {
    $AppDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
}
$AppDir = [System.IO.Path]::GetFullPath($AppDir.TrimEnd('\', '/'))

$PythonProcessNames = @(
    "python.exe", "pythonw.exe", "python", "pythonw"
)

function Test-UnderAppDir([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
    } catch {
        $full = $Path
    }
    return $full.StartsWith($AppDir + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $full.Equals($AppDir, [StringComparison]::OrdinalIgnoreCase)
}

function Test-MentionsAppDir([string]$Text) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    return $Text.IndexOf($AppDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Get-TargetProcessIds {
    $ids = @{}

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $name = [string]$_.Name
        $exe = [string]$_.ExecutablePath
        $cmd = [string]$_.CommandLine
        $isLauncher = $name -match '^run_pybibx(\.exe)?$'
        $isPython = $PythonProcessNames -contains $name
        if (-not ($isLauncher -or $isPython)) { return }

        if ((Test-UnderAppDir $exe) -or (Test-MentionsAppDir $cmd)) {
            $ids[[int]$_.ProcessId] = $true
        }
    }

    Get-Process -Name "run_pybibx" -ErrorAction SilentlyContinue | ForEach-Object {
        if (Test-UnderAppDir $_.Path) {
            $ids[[int]$_.Id] = $true
        }
    }

    return @($ids.Keys)
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    & "$env:SystemRoot\System32\taskkill.exe" /PID $ProcessId /T /F 2>$null | Out-Null
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-PortHolders {
    param([int[]]$Ports)

    foreach ($port in $Ports) {
        $ownerIds = @{}

        try {
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
                ForEach-Object { $ownerIds[[int]$_.OwningProcess] = $true }
        } catch {
            try {
                $output = & "$env:SystemRoot\System32\netstat.exe" -ano -p TCP 2>$null
                $suffix = ":$port"
                foreach ($line in $output) {
                    if ($line -notmatch "LISTENING") { continue }
                    $parts = $line -split "\s+" | Where-Object { $_ }
                    if ($parts.Count -lt 5) { continue }
                    if (-not $parts[1].EndsWith($suffix)) { continue }
                    $procId = 0
                    if ([int]::TryParse($parts[-1], [ref]$procId) -and $procId -gt 0) {
                        $ownerIds[$procId] = $true
                    }
                }
            } catch { }
        }

        foreach ($procId in @($ownerIds.Keys)) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
            if (-not $proc) { continue }
            $name = [string]$proc.Name
            $isOurs = (Test-UnderAppDir $proc.ExecutablePath) -or
                (Test-MentionsAppDir $proc.CommandLine) -or
                ($name -match '^run_pybibx(\.exe)?$') -or
                ($PythonProcessNames -contains $name)
            if ($isOurs) {
                Stop-ProcessTree $procId
            }
        }
    }
}

for ($attempt = 1; $attempt -le 4; $attempt++) {
    foreach ($procId in Get-TargetProcessIds) {
        Stop-ProcessTree $procId
    }
    Stop-PortHolders -Ports @(5172, 5173)

    Start-Sleep -Milliseconds (700 * $attempt)

    if ((Get-TargetProcessIds).Count -eq 0) { break }
}
