#Requires -Version 7.0
<#
.SYNOPSIS
    پشتیبان‌گیری امن از پروژه FX-ARS قبل از اعمال اصلاحات.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$ErrorActionPreference = 'Stop'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $ProjectRoot ".fix-backups\$timestamp"

Write-Host "[BACKUP] ProjectRoot: $ProjectRoot" -ForegroundColor Cyan
Write-Host "[BACKUP] BackupDir  : $backupRoot" -ForegroundColor Cyan

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

# فقط پوشه‌های مهم پروژه
$targets = @('fxars', 'tests', 'scripts', 'docs', 'README.md', 'pyproject.toml', 'FXARS.bat')
foreach ($t in $targets) {
    $src = Join-Path $ProjectRoot $t
    if (Test-Path $src) {
        $dst = Join-Path $backupRoot $t
        Copy-Item -Path $src -Destination $dst -Recurse -Force
        Write-Host "  [OK] $t" -ForegroundColor Green
    }
}

# ذخیره هش فایل‌ها برای بازگشت
$manifest = Get-ChildItem -Path $ProjectRoot -Recurse -File -Include *.py,*.ps1,*.md,*.toml,*.bat,*.sql `
    -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\\.fix-backups\\' } |
    ForEach-Object { [PSCustomObject]@{ Path = $_.FullName; Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash } }

$manifest | ConvertTo-Json -Depth 3 | Set-Content (Join-Path $backupRoot 'manifest.json') -Encoding UTF8
Write-Host "[BACKUP] Done. Restore later via: Copy-Item '$backupRoot\*' '$ProjectRoot' -Recurse -Force" -ForegroundColor Yellow