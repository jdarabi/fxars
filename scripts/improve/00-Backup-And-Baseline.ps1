#Requires -Version 7.0
<#
.SYNOPSIS
    گام 0: Backup کامل + اجرای تست‌های baseline قبل از اصلاحات.
.DESCRIPTION
    - کپی کامل پروژه به .fix-backups\improve-<timestamp>\
    - ذخیره هش همه فایل‌ها در manifest.json
    - ضبط نسخه‌های فعلی (version.py / pyproject / README / CHANGELOG)
    - اجرای تست‌ها و ذخیره خروجی به baseline-tests.log
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\FX',
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup  = Join-Path $ProjectRoot ".fix-backups\improve-$stamp"

Write-Host "`n===[ GAM 00: Backup & Baseline ]===" -ForegroundColor Cyan
Write-Host "ProjectRoot : $ProjectRoot"
Write-Host "BackupDir   : $backup"

# ---- 1) Backup
$targets = @('fxars','tests','scripts','docs','config',
             'README.md','CHANGELOG.md','pyproject.toml','FXARS.bat')
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($t in $targets) {
    $src = Join-Path $ProjectRoot $t
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $backup $t) -Recurse -Force
        Write-Host "  [OK] $t" -ForegroundColor Green
    } else {
        Write-Host "  [--] $t (not found, skip)" -ForegroundColor DarkGray
    }
}

# ---- 2) Manifest (hash همه فایل‌های مهم)
$manifest = Get-ChildItem $ProjectRoot -Recurse -File `
    -Include *.py,*.ps1,*.md,*.toml,*.bat,*.sql,*.json -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.fix-backups\\' -and
                   $_.FullName -notmatch '\\\.git\\' -and
                   $_.FullName -notmatch '__pycache__' } |
    ForEach-Object {
        [PSCustomObject]@{
            Path = $_.FullName.Substring($ProjectRoot.Length).TrimStart('\')
            Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        }
    }
$manifest | ConvertTo-Json -Depth 3 | Set-Content (Join-Path $backup 'manifest.json') -Encoding utf8
Write-Host "  [OK] manifest.json ($($manifest.Count) files)" -ForegroundColor Green

# ---- 3) ضبط نسخه‌ها
Write-Host "`n--- Current versions ---" -ForegroundColor Yellow
$versionInfo = @{}
$vFile = Join-Path $ProjectRoot 'fxars\version.py'
if (Test-Path $vFile) {
    $vText = Get-Content $vFile -Raw
    if ($vText -match 'CODE_VERSION\s*=\s*"([^"]+)"')   { $versionInfo['version.py'] = $Matches[1] }
}
$pFile = Join-Path $ProjectRoot 'pyproject.toml'
if (Test-Path $pFile) {
    $pText = Get-Content $pFile -Raw
    if ($pText -match 'version\s*=\s*"([^"]+)"')        { $versionInfo['pyproject.toml'] = $Matches[1] }
}
$cFile = Join-Path $ProjectRoot 'CHANGELOG.md'
if (Test-Path $cFile) {
    $cText = Get-Content $cFile -Raw
    if ($cText -match '##\s*\[v([^\]]+)\]')             { $versionInfo['CHANGELOG.md (latest)'] = $Matches[1] }
}
$eFile = Join-Path $ProjectRoot 'fxars.egg-info\PKG-INFO'
if (Test-Path $eFile) {
    $eText = Get-Content $eFile -Raw
    if ($eText -match '(?m)^Version:\s*(\S+)')          { $versionInfo['egg-info'] = $Matches[1] }
}
$versionInfo.GetEnumerator() | Sort-Object Name | Format-Table -AutoSize | Out-Host
$versionInfo | ConvertTo-Json | Set-Content (Join-Path $backup 'versions-before.json') -Encoding utf8

# ---- 4) Baseline tests
if (-not $SkipTests) {
    Write-Host "`n--- Running baseline tests (may take ~2 min) ---" -ForegroundColor Yellow
    Push-Location $ProjectRoot
    try {
        & python -B -m unittest discover -s tests 2>&1 |
            Tee-Object -FilePath (Join-Path $backup 'baseline-tests.log') |
            Select-Object -Last 40
    } finally {
        Pop-Location
    }
}

Write-Host "`n===[ DONE: gam 00 ]===" -ForegroundColor Green
Write-Host "Backup : $backup"
Write-Host "Rollback: Copy-Item '$backup\*' '$ProjectRoot' -Recurse -Force"