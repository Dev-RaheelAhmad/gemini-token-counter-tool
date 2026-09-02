# Creates Windows Desktop and Start Menu shortcuts for Gemini Token Monitor for ANY Windows User Account
$WshShell = New-Object -comObject WScript.Shell

# 1. Resolve Desktop Path (handling OneDrive redirection or standard Desktop)
$DesktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
if (-not (Test-Path $DesktopPath) -and $env:USERPROFILE) {
    $DesktopPath = Join-Path $env:USERPROFILE "Desktop"
}

# 2. Resolve Start Menu Programs Path
$StartMenuPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::StartMenu) + "\Programs"
if (-not (Test-Path $StartMenuPath) -and $env:APPDATA) {
    $StartMenuPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetScript = Join-Path $ScriptDir "token_counter_gui.pyw"

# 3. Dynamically resolve pythonw.exe or python.exe across any installation
$PythonwExe = $null

# Check current python in PATH
$PythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($PythonCmd) {
    $Dir = Split-Path -Parent $PythonCmd.Source
    $Cand = Join-Path $Dir "pythonw.exe"
    if (Test-Path $Cand) {
        $PythonwExe = $Cand
    } else {
        $PythonwExe = $PythonCmd.Source
    }
}

# Fallback: Check LocalAppData programs
if (-not $PythonwExe -and $env:LOCALAPPDATA) {
    $LocalPyCand = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Filter "pythonw.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($LocalPyCand) {
        $PythonwExe = $LocalPyCand.FullName
    }
}

# Fallback default
if (-not $PythonwExe) {
    $PythonwExe = "pythonw.exe"
}

# Create Desktop Shortcut
if (Test-Path $DesktopPath) {
    try {
        $ShortcutPath = Join-Path $DesktopPath "Gemini Token Monitor.lnk"
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $PythonwExe
        $Shortcut.Arguments = "`"$TargetScript`""
        $Shortcut.WorkingDirectory = $ScriptDir
        $Shortcut.Description = "Gemini Token Counter & Live Quota Monitor"
        $Shortcut.Save()
        Write-Host "Created Desktop shortcut at: $ShortcutPath" -ForegroundColor Green
    } catch {
        Write-Host "Could not create desktop shortcut: $_" -ForegroundColor Yellow
    }
}

# Create Start Menu Shortcut
if (Test-Path $StartMenuPath) {
    try {
        $StartShortcutPath = Join-Path $StartMenuPath "Gemini Token Monitor.lnk"
        $StartShortcut = $WshShell.CreateShortcut($StartShortcutPath)
        $StartShortcut.TargetPath = $PythonwExe
        $StartShortcut.Arguments = "`"$TargetScript`""
        $StartShortcut.WorkingDirectory = $ScriptDir
        $StartShortcut.Description = "Gemini Token Counter & Live Quota Monitor"
        $StartShortcut.Save()
        Write-Host "Created Start Menu shortcut at: $StartShortcutPath" -ForegroundColor Green
    } catch {
        Write-Host "Could not create start menu shortcut: $_" -ForegroundColor Yellow
    }
}
