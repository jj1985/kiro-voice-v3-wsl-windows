[CmdletBinding()]
param([switch]$TextOnly, [switch]$SkipModels, [switch]$NoBootstrap)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
if (-not [Environment]::Is64BitProcess) { throw 'Use 64-bit PowerShell on Windows 11.' }
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) {
    $Uv = Join-Path $HOME '.local\bin\uv.exe'
    if (-not (Test-Path $Uv)) {
        if ($NoBootstrap) { throw 'uv is missing. Install uv, then rerun this script.' }
        Write-Host 'Installing uv from Astral. No administrator privileges required.'
        $env:UV_NO_MODIFY_PATH = '1'
        Invoke-Expression (Invoke-RestMethod 'https://astral.sh/uv/0.10.0/install.ps1')
        if (-not (Test-Path $Uv)) { throw 'uv installation failed. Install uv manually and retry.' }
    }
}
$OldVenv = $env:UV_PROJECT_ENVIRONMENT
$OldLink = $env:UV_LINK_MODE
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $Root '.venv'
    $env:UV_LINK_MODE = 'copy'
    & $Uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Managed Python installation failed.' }
    $Sync = @('sync', '--project', $Root, '--python', '3.12', '--no-dev')
    if (Test-Path (Join-Path $Root 'uv.lock')) { $Sync += '--locked' }
    if (-not $TextOnly) { $Sync += @('--extra', 'voice') }
    & $Uv @Sync
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $Python = Join-Path $Root '.venv\Scripts\python.exe'
    & $Python -X utf8 -m quack_actual config init
    if ($LASTEXITCODE -ne 0) { throw 'Configuration initialization failed.' }
    if (-not $TextOnly -and -not $SkipModels) {
        & $Python -X utf8 -m quack_actual download-models
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Retry or use -SkipModels for download on first use.' }
    }
    Write-Host ''
    Write-Host 'Quack Actual installed. Next: authenticate your selected coding CLI.'
    Write-Host 'Native Windows: .\launch.ps1 start --backend copilot --project C:\src\your-project'
    Write-Host 'Diagnostics:    .\launch.ps1 doctor --backend copilot'
    Write-Host 'Audio devices:  .\launch.ps1 devices'
    Write-Host 'For voice, enable desktop microphone access in Windows privacy settings.'
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $OldVenv
    $env:UV_LINK_MODE = $OldLink
}
