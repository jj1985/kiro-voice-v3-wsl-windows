param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$Project = "~",
    [ValidateSet("kiro", "claude", "codex")]
    [string]$Backend = "kiro",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Root
$Startup = [Environment]::GetFolderPath("Startup")
$CmdPath = Join-Path $Startup "AgentVoice.cmd"
$LegacyCmdPath = Join-Path $Startup "KiroVoiceV3.cmd"

if ($Remove) {
    if (Test-Path $CmdPath) { Remove-Item $CmdPath -Force }
    if (Test-Path $LegacyCmdPath) { Remove-Item $LegacyCmdPath -Force }
    Write-Host "Removed Agent Voice startup entry."
    exit 0
}

$WslRepo = (& wsl.exe -d $Distro -- wslpath -u "$RepoRoot").Trim()
if (-not $WslRepo) {
    throw "Could not translate repository path into WSL."
}

$RunScript = "$WslRepo/wsl/run.sh"
$escapedProject = $Project.Replace("'", "'\''")
$bash = "AGENT_VOICE_PROJECT='$escapedProject' AGENT_VOICE_BACKEND='$Backend' '$RunScript'"

# Windows Terminal stays visible so agent tool/permission output is inspectable.
$cmd = "@echo off`r`nwt.exe new-tab --title `"Agent Voice - $Backend`" wsl.exe -d `"$Distro`" -- bash -lc `"$bash`"`r`n"
Set-Content -Path $CmdPath -Value $cmd -Encoding ASCII

Write-Host "Installed Startup entry:"
Write-Host "  $CmdPath"
Write-Host "Distro: $Distro"
Write-Host "Project: $Project"
Write-Host "Backend: $Backend"
Write-Host ""
Write-Host "Remove later with:"
Write-Host "  .\install-autostart.ps1 -Remove"
