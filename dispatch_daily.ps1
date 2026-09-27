$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$internal = Join-Path $repo 'local-state'
New-Item -ItemType Directory -Force -Path $internal | Out-Null
$log = Join-Path $internal 'daily-dispatch.log'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
try {
    $ErrorActionPreference = 'Continue'
    & $python (Join-Path $repo 'dispatch_daily.py') --scheduled 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
    $result = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($result -ne 0) { throw "Dispatch failed with exit code $result" }
} catch {
    "$(Get-Date -Format s) $_" | Add-Content -LiteralPath $log -Encoding utf8
    exit 1
}
