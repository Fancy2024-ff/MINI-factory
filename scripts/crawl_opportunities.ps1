# scripts/crawl_opportunities.ps1 — 薄包装，转发参数给 Python 脚本。
# 用法：
#   .\scripts\crawl_opportunities.ps1 --preset quick --dry-run
#   .\scripts\crawl_opportunities.ps1 --preset cn --limit 20
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
python "$repoRoot\scripts\crawl_opportunities.py" @args
