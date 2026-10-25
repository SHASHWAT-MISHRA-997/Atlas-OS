<#
.SYNOPSIS
  Sets up ATLAS OS on this Windows PC for the current user. No administrator rights needed.

.DESCRIPTION
  1. Checks for Python 3.11 or newer (it does not install Python).
  2. Creates a private Python environment in <repo>\.venv and installs ATLAS's packages into it.
  3. Writes <repo>\atlas-settings.cmd (only if it does not exist yet) for you to edit, and
     <repo>\start-atlas.cmd, which starts ATLAS at http://localhost:8000.
  4. With -StartOnLogin, adds a shortcut to your Startup folder so ATLAS starts when you sign in.

  It downloads only the Python packages listed in backend\requirements.txt. It never downloads
  AI models, never changes system settings, and never needs your passwords or API keys.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -StartOnLogin
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -RemoveStartOnLogin
#>
[CmdletBinding()]
param(
    [switch]$StartOnLogin,        # also start ATLAS when you sign in to Windows
    [switch]$RemoveStartOnLogin,  # undo -StartOnLogin and stop here
    [switch]$SkipPackages         # do not run pip (for re-running after a manual install)
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend = Join-Path $Root 'backend'
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Settings = Join-Path $Root 'atlas-settings.cmd'
$Starter = Join-Path $Root 'start-atlas.cmd'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'ATLAS OS.lnk'

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

if ($RemoveStartOnLogin) {
    if (Test-Path $Shortcut) { Remove-Item $Shortcut; Write-Host "Removed $Shortcut. ATLAS no longer starts when you sign in." }
    else { Write-Host 'ATLAS was not set to start when you sign in.' }
    exit 0
}

if (-not (Test-Path (Join-Path $Backend 'app\main.py'))) { throw "This script must stay in scripts\windows inside the ATLAS folder (no backend found at $Backend)." }

Step 'Looking for Python 3.11 or newer'
$python = $null
foreach ($candidate in @(@('py', '-3'), @('python'))) {
    $exe = $candidate[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $pyArgs = @($candidate | Select-Object -Skip 1)
    # No quotes inside the -c code: Windows PowerShell 5.1 and 7 pass embedded quotes differently.
    try { $code = & $exe @pyArgs -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>$null } catch { continue }
    if ($LASTEXITCODE -eq 0 -and "$code" -match '^\d+$' -and [int]"$code" -ge 311) {
        $python = $candidate; $version = '{0}.{1}' -f [math]::Floor([int]"$code" / 100), ([int]"$code" % 100); break
    }
}
if (-not $python) {
    Write-Host 'Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/windows/'
    Write-Host '(tick "Add python.exe to PATH"), then run this script again.'
    exit 1
}
Write-Host "Using: $($python -join ' ') (Python $version)"

if (-not (Test-Path $VenvPython)) {
    Step "Creating a private Python environment in $Venv"
    $pyArgs = @($python | Select-Object -Skip 1)
    & $python[0] @pyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

if (-not $SkipPackages) {
    Step 'Installing ATLAS packages (only those in backend\requirements.txt)'
    & $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $Backend 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pip could not install the packages. Check your internet connection and try again.' }
}

if (-not (Test-Path $Settings)) {
    Step "Writing $Settings (edit it any time; this script never overwrites it)"
    @'
@rem ATLAS OS settings. Remove "@rem " at the start of a line to turn it on. Restart ATLAS after editing.
@rem Never put API keys in a file you share or upload.

@rem PC actions (open apps, list/search/index files, create notes and documents, ATLAS trash).
@rem Every action still waits for your approval. Folders are name=path pairs separated by ;
@rem set ATLAS_ENABLE_DESKTOP_AGENT=true
@rem set ATLAS_AGENT_FOLDERS=documents=%USERPROFILE%\Documents;downloads=%USERPROFILE%\Downloads

@rem Phone on the same Wi-Fi: see docs\REMOTE_ACCESS.md before turning these on.
@rem set ATLAS_HOST=0.0.0.0
@rem set ATLAS_ALLOWED_HOSTS=192.168.1.5
@rem set ATLAS_PUBLIC_URL=http://192.168.1.5:8000

@rem Port (default 8000)
@rem set ATLAS_PORT=8000
'@ | Set-Content -Path $Settings -Encoding ASCII
}

Step "Writing $Starter"
@"
@echo off
rem Starts ATLAS OS. Written by scripts\windows\install.ps1; safe to re-run the installer to rewrite it.
setlocal
call "%~dp0atlas-settings.cmd"
cd /d "%~dp0backend"
echo ATLAS OS is starting. Open http://localhost:8000 (or the port set in atlas-settings.cmd). Close this window to stop it.
"%~dp0.venv\Scripts\python.exe" -m app.serve
"@ | Set-Content -Path $Starter -Encoding ASCII

if ($StartOnLogin) {
    Step "Adding ATLAS to your Startup folder"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Shortcut)
    $link.TargetPath = $Starter
    $link.WorkingDirectory = $Root
    $link.WindowStyle = 7  # minimised
    $link.Description = 'Start ATLAS OS'
    $link.Save()
    Write-Host "ATLAS will start (minimised) when you sign in. Undo with: install.ps1 -RemoveStartOnLogin"
}

Write-Host ''
Write-Host 'Done. Start ATLAS by double-clicking start-atlas.cmd, then open http://localhost:8000' -ForegroundColor Green
Write-Host "PC actions are off until you edit $Settings."
