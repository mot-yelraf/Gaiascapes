#requires -Version 5.1
<#
.SYNOPSIS
Launch the installed Gaiascapes desktop, server, or audio renderer on Windows.
.DESCRIPTION
Uses this installation's data directory. Desktop mode supervises only the
SuperCollider process it starts; a separately running renderer is left alone.
#>
[CmdletBinding()]
param(
    [ValidateSet('Desktop', 'Server', 'Audio')][string]$Mode = 'Desktop',
    [string]$AudioDevice = $env:GAIA_SCAPE_AUDIO_DEVICE,
    [switch]$NoAudio,
    [switch]$PauseOnError,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ServerArguments
)

$ErrorActionPreference = 'Stop'
$audioProcess = $null
$exitCode = 0
try {
    $runtimeDir = Split-Path -Parent $PSScriptRoot
    $runtimePython = Join-Path $runtimeDir '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'The virtual environment is missing. Run install.cmd again.' }
    $env:GAIA_SCAPE_DATA_DIR = Join-Path $runtimeDir 'data'
    if (-not $env:GAIA_SCAPE_HTTP_HOST) { $env:GAIA_SCAPE_HTTP_HOST = '0.0.0.0' }
    Set-Location -LiteralPath $runtimeDir

    if ($Mode -eq 'Audio' -or ($Mode -eq 'Desktop' -and -not $NoAudio)) {
        $sclang = $env:GAIA_SCAPE_SCLANG
        if (-not $sclang) {
            $command = Get-Command sclang.exe -ErrorAction SilentlyContinue
            if ($command) { $sclang = $command.Source }
        }
        if (-not $sclang) {
            $candidates = @(Get-ChildItem -Path "$env:ProgramFiles\SuperCollider*\sclang.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
            if ($candidates.Count) { $sclang = $candidates[0].FullName }
        }
        if ($sclang -and (Test-Path -LiteralPath $sclang)) {
            # Let the web UI discover scsynth alongside sclang without changing PATH permanently.
            $env:PATH = (Split-Path -Parent $sclang) + ';' + $env:PATH
            $deviceFile = Join-Path $runtimeDir 'data\audio-device'
            if (-not $AudioDevice -and (Test-Path -LiteralPath $deviceFile)) { $AudioDevice = (Get-Content -LiteralPath $deviceFile -Raw).Trim() }
            $env:GAIA_SCAPE_AUDIO_DEVICE = if ($AudioDevice -and $AudioDevice -ne 'system') { $AudioDevice } else { $null }
            $languagePort = if ($env:GAIA_SCAPE_SCLANG_PORT) { $env:GAIA_SCAPE_SCLANG_PORT } else { '57131' }
            $audioScript = Join-Path $runtimeDir 'supercollider\gaia-scape.scd'
            if ($Mode -eq 'Audio') {
                & $sclang -u $languagePort $audioScript
                $exitCode = $LASTEXITCODE
            } elseif (-not (Get-NetUDPEndpoint -LocalPort 57130 -ErrorAction SilentlyContinue)) {
                $audioProcess = Start-Process -FilePath $sclang -ArgumentList @('-u', $languagePort, ('"' + $audioScript + '"')) -WorkingDirectory (Split-Path -Parent $sclang) -PassThru
                Start-Sleep -Seconds 2
                if ($audioProcess.HasExited) { Write-Warning 'SuperCollider exited; Gaiascapes will continue without synthesized audio.' }
            }
        } elseif ($Mode -eq 'Audio') {
            throw 'SuperCollider was not found. Install it from https://supercollider.github.io/downloads or set GAIA_SCAPE_SCLANG to sclang.exe.'
        } else { Write-Warning 'SuperCollider was not found; starting Gaiascapes without synthesized audio.' }
    }
    if ($Mode -eq 'Server') {
        & $runtimePython -m gaiascapes_host @ServerArguments
        $exitCode = $LASTEXITCODE
    } elseif ($Mode -eq 'Desktop') {
        $env:PYWEBVIEW_GUI = 'edgechromium'
        & $runtimePython -m gaiascapes_host.desktop
        $exitCode = $LASTEXITCODE
    }
} catch {
    Write-Error "Gaiascapes could not start: $_" -ErrorAction Continue
    $exitCode = 1
} finally {
    if ($audioProcess -and -not $audioProcess.HasExited) {
        # Stop this renderer and its scsynth child, never all SuperCollider processes.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $audioProcess.Id /T /F | Out-Null
    }
}
if ($exitCode -ne 0 -and $PauseOnError) { Read-Host 'Press Enter to close' | Out-Null }
exit $exitCode
