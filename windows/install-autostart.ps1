param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$KiroProject = "~",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Root
$Startup = [Environment]::GetFolderPath("Startup")
$CmdPath = Join-Path $Startup "KiroVoiceV3.cmd"

if ($Remove) {
    if (Test-Path $CmdPath) { Remove-Item $CmdPath -Force }
    Write-Host "Removed Kiro Voice startup entry."
    exit 0
}

$WslRepo = (& wsl.exe -d $Distro -- wslpath -u "$RepoRoot").Trim()
if (-not $WslRepo) {
    throw "Could not translate repository path into WSL."
}

$RunScript = "$WslRepo/wsl/run.sh"
$escapedProject = $KiroProject.Replace("'", "'\''")
$bash = "KIRO_VOICE_PROJECT='$escapedProject' '$RunScript'"

# Windows Terminal gives permission prompts/tool output a visible interactive console.
$cmd = "@echo off`r`nwt.exe new-tab --title `"Kiro Voice`" wsl.exe -d `"$Distro`" -- bash -lc `"$bash`"`r`n"
Set-Content -Path $CmdPath -Value $cmd -Encoding ASCII

Write-Host "Installed Startup entry:"
Write-Host "  $CmdPath"
Write-Host "Distro: $Distro"
Write-Host "Kiro project: $KiroProject"
Write-Host ""
Write-Host "Remove later with:"
Write-Host "  .\install-autostart.ps1 -Remove"
