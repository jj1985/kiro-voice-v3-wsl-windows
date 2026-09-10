param(
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Config = Join-Path $Root "config.json"
$Example = Join-Path $Root "config.example.json"

Write-Host "Installing Kiro Voice V3 Windows audio service..."
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "py.exe was not found. Install Python $PythonVersion for Windows."
}

if (-not (Test-Path $Python)) {
    & py "-$PythonVersion" -m venv $Venv
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")

if (-not (Test-Path $Config)) {
    Copy-Item $Example $Config
    Write-Host "Created $Config"
}

Write-Host ""
Write-Host "Microphone devices:"
& $Python -c "import sounddevice as sd; print(sd.query_devices())"

$WslPython = (& wsl.exe wslpath -u "$Python").Trim()
Write-Host ""
Write-Host "Add this to ~/.bashrc inside WSL:"
Write-Host "export KIRO_VOICE_WINDOWS_PY='$WslPython'"
Write-Host ""
Write-Host "Default wake phrase: Hey Kiro"
Write-Host "Edit windows\config.json to change it."
