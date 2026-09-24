[CmdletBinding()]
param(
    [ValidateSet('native','wsl')][string]$Mode = 'native',
    [ValidateSet('copilot','claude','codex','kiro')][string]$Backend = 'copilot',
    [string]$Project = '',
    [string]$Distro = 'Ubuntu-24.04',
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Project) { $Project = if ($Mode -eq 'wsl') { '~' } else { $HOME } }
$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Quack Actual.lnk'
if ($Remove) {
    if (Test-Path $ShortcutPath) { Remove-Item -LiteralPath $ShortcutPath }
    Write-Host 'Quack Actual automatic startup removed.'
    return
}
# Reject command-line control characters rather than constructing a shell command.
foreach ($Value in @($Root, $Project, $Distro)) {
    if ($Value -match '["\r\n]') { throw 'Paths and distro names cannot contain quotes or newlines.' }
}
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.WorkingDirectory = $Root
if ($Mode -eq 'native') {
    $Shortcut.TargetPath = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path $Shortcut.TargetPath)) { $Shortcut.TargetPath = (Get-Command pwsh).Source }
    $Shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'launch.ps1') + '" start --backend ' + $Backend + ' --project "' + $Project + '"'
} else {
    $LinuxRoot = (& wsl.exe -d $Distro -- wslpath -u $Root).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $LinuxRoot) { throw 'Could not resolve checkout in WSL.' }
    $Shortcut.TargetPath = (Get-Command wsl.exe).Source
    $Shortcut.Arguments = '-d "' + $Distro + '" -- bash "' + $LinuxRoot + '/launch.sh" start --backend ' + $Backend + ' --project "' + $Project + '"'
}
$Shortcut.Description = 'Quack Actual - voice console for coding agents'
$Shortcut.WindowStyle = 1
$Shortcut.Save()
Write-Host "Startup enabled in a visible terminal: $ShortcutPath"
Write-Host 'Microphone listening starts at next login. Use -Remove to disable.'
