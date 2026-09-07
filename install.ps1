#requires -Version 5.1
<#+.SYNOPSIS
Install Gaiascapes for the current Windows user.
.DESCRIPTION
Creates a private Python environment, preserves data, and adds launch shortcuts.
Run again from the source checkout or installed folder to update the application.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = $env:GAIA_SCAPE_INSTALL_DIR,
    [ValidateSet('Desktop', 'Headless')][string]$Mode = 'Desktop',
    [string]$Python = $env:GAIA_SCAPE_PYTHON,
    [string]$ShortcutDirectory = [Environment]::GetFolderPath('DesktopDirectory'),
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'
try {
    if ($env:OS -ne 'Windows_NT') { throw 'This installer requires Windows 10 or 11.' }
    $sourceDir = $PSScriptRoot
    if (-not (Test-Path -LiteralPath (Join-Path $sourceDir 'pyproject.toml'))) {
        $sourceRecord = Join-Path $sourceDir 'data\install-source'
        if (-not (Test-Path -LiteralPath $sourceRecord)) { throw 'The recorded source checkout is unavailable. Run install.cmd from an extracted source checkout.' }
        if (-not $InstallDir) { $InstallDir = $sourceDir }
        $modeRecord = Join-Path $sourceDir 'data\install-mode'
        if (-not $PSBoundParameters.ContainsKey('Mode') -and (Test-Path -LiteralPath $modeRecord)) {
            $Mode = (Get-Content -LiteralPath $modeRecord -Raw).Trim()
        }
        $sourceDir = (Get-Content -LiteralPath $sourceRecord -Raw).Trim()
        if (-not (Test-Path -LiteralPath (Join-Path $sourceDir 'pyproject.toml'))) {
            throw 'The recorded source checkout is unavailable. Run install.cmd from an extracted source checkout.'
        }
    }
    if ($Mode -notin @('Desktop', 'Headless')) { throw 'Install mode must be Desktop or Headless.' }
    if (-not $InstallDir) { $InstallDir = Join-Path $env:USERPROFILE 'Gaiascapes' }
    if (-not [IO.Path]::IsPathRooted($InstallDir)) { throw 'InstallDir must be an absolute path.' }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    if ($InstallDir -eq [IO.Path]::GetPathRoot($InstallDir).TrimEnd('\') -or
        $InstallDir -eq $env:USERPROFILE.TrimEnd('\') -or $InstallDir -eq $sourceDir) {
        throw 'Choose a dedicated installation folder outside the source checkout.'
    }

    # Resolve the actual interpreter so a launcher or Microsoft Store alias is
    # never embedded in shortcuts. Python 3.13 x64 is the tested Windows path.
    if (-not $Python) {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
            $Python = & py.exe -3.13 -c 'import sys; print(sys.executable)'
            if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.13 (64-bit), or pass -Python with an existing Python executable.' }
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            $Python = (Get-Command python.exe).Source
        } else { throw 'Install Python 3.13 (64-bit) from https://www.python.org/downloads/windows/ and run install.cmd again.' }
    }
    & $Python -c "import struct, sys; sys.exit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Gaiascapes requires 64-bit Python 3.10 or newer; Python 3.13 is recommended on Windows.' }

    if ($Mode -eq 'Desktop') {
        $webviewInstalled = $false
        foreach ($root in @('HKCU:\Software', 'HKLM:\Software\WOW6432Node', 'HKLM:\Software')) {
            $key = "$root\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
            $version = Get-ItemProperty -LiteralPath $key -Name pv -ErrorAction SilentlyContinue
            if ($version -and $version.pv -and $version.pv -ne '0.0.0.0') { $webviewInstalled = $true }
        }
        if (-not $webviewInstalled) {
            throw 'Install the Microsoft Edge WebView2 Evergreen Runtime from https://developer.microsoft.com/microsoft-edge/webview2/ then retry, or use -Mode Headless for the browser UI.'
        }
    }

    New-Item -ItemType Directory -Force -Path $InstallDir, (Join-Path $InstallDir 'data'), (Join-Path $InstallDir 'scripts'), (Join-Path $InstallDir 'supercollider') | Out-Null
    $logFile = Join-Path $InstallDir 'install.log'
    "Installing Gaiascapes from $sourceDir into $InstallDir" | Tee-Object -FilePath $logFile
    & $Python -m venv (Join-Path $InstallDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment. Close Gaiascapes before repairing an installation.' }
    $runtimePython = Join-Path $InstallDir '.venv\Scripts\python.exe'
    $extras = if ($Mode -eq 'Desktop') { 'desktop,lightning,eumetsat' } else { 'lightning,eumetsat' }
    # Windows PowerShell 5.1 wraps native stderr as error records, including
    # successful pip warnings. Use the native exit status to detect failure.
    $ErrorActionPreference = 'Continue'
    & $runtimePython -m pip install --disable-pip-version-check --upgrade "$sourceDir[$extras]" 2>&1 | Tee-Object -FilePath $logFile -Append
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw "Python package installation failed. See $logFile." }
    if ($Mode -eq 'Desktop') {
        & $runtimePython -c 'import webview; import webview.platforms.winforms'
        if ($LASTEXITCODE -ne 0) { throw 'The Windows desktop backend could not load. Check WebView2 and .NET Framework 4.8, then retry.' }
    }
    foreach ($name in @('install.cmd', 'install.ps1', 'scripts\run_gaiascapes.ps1', 'README.md', 'WINDOWS_INSTALL.md', 'SYSTEM_REQUIREMENTS.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'PRIVACY.md', 'SECURITY.md')) {
        Copy-Item -LiteralPath (Join-Path $sourceDir $name) -Destination (Join-Path $InstallDir $name) -Force
    }
    Copy-Item -LiteralPath (Join-Path $sourceDir 'supercollider\gaia-scape.scd') -Destination (Join-Path $InstallDir 'supercollider\gaia-scape.scd') -Force
    Copy-Item -LiteralPath (Join-Path $sourceDir 'src\gaiascapes_host\static\gaia-scape-desktop-icon.ico') -Destination (Join-Path $InstallDir 'gaiascapes.ico') -Force
    [IO.File]::WriteAllText((Join-Path $InstallDir 'data\install-source'), $sourceDir)
    [IO.File]::WriteAllText((Join-Path $InstallDir 'data\install-mode'), $Mode.ToLowerInvariant())

    if (-not $NoShortcut) {
        New-Item -ItemType Directory -Force -Path $ShortcutDirectory | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $launchMode = if ($Mode -eq 'Desktop') { 'Desktop' } else { 'Server' }
        foreach ($item in @(@('Gaiascapes', $launchMode), @('Gaiascapes Audio', 'Audio'))) {
            $shortcut = $shell.CreateShortcut((Join-Path $ShortcutDirectory "$($item[0]).lnk"))
            $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
            $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $InstallDir 'scripts\run_gaiascapes.ps1') + '" -Mode ' + $item[1] + ' -PauseOnError'
            $shortcut.WorkingDirectory = $InstallDir
            $shortcut.IconLocation = (Join-Path $InstallDir 'gaiascapes.ico') + ',0'
            $shortcut.Save()
        }
    }
    Write-Host "Gaiascapes installed in $InstallDir"
    Write-Host 'Open the Gaiascapes shortcut. Browser UI: http://127.0.0.1:8768'
    Write-Host 'SuperCollider is optional; install it separately for synthesized sound.'
    Write-Host "Application data: $(Join-Path $InstallDir 'data')"
} catch {
    Write-Error "Gaiascapes installation failed: $_" -ErrorAction Continue
    exit 1
}
