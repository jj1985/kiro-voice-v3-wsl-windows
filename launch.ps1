$ErrorActionPreference = 'Stop'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Run .\install.ps1 first.' }
$Forward = @($args)
if ($Forward.Count -eq 0) { $Forward = @('start') }
& $Python -X utf8 -m quack_actual @Forward
exit $LASTEXITCODE
