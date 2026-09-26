$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$node = Join-Path $runtime 'node\bin\node.exe'
$root = 'E:\论文\知识点概述\日常文献查询记录'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$log = Join-Path $root '本地同步日志_UTF8.txt'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
try {
    $ErrorActionPreference = 'Continue'
    & $python (Join-Path $repo 'local_sync.py') --repo $repo --root $root --node $node --builder (Join-Path $repo 'build_catalog.mjs') 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
    $result = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($result -ne 0) { throw "local_sync.py failed with exit code $result" }
} catch {
    "$(Get-Date -Format s) 同步失败: $_" | Add-Content -LiteralPath $log -Encoding utf8
    exit 1
}
"$(Get-Date -Format s) 同步完成" | Add-Content -LiteralPath $log -Encoding utf8
