#Requires -Version 7.0
# مسیر: C:\project\FX\scripts\improve\00-Create-ImproveScripts.ps1
# این اسکریپت همه اسکریپت‌های improve را روی دیسک می‌سازد.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $here) { $here = 'C:\project\FX\scripts\improve' }

function Write-Script {
    param([string]$Name, [string]$Content)
    $path = Join-Path $here $Name
    Set-Content -Path $path -Value $Content -Encoding UTF8
    Write-Host "  [created] $path" -ForegroundColor Green
}

Write-Host "`n=== ساخت اسکریپت‌های improve ===" -ForegroundColor Cyan
Write-Host "Directory: $here`n"

# ===========================================================================
# 01-Remove-Secrets.ps1
# ===========================================================================
Write-Script '01-Remove-Secrets.ps1' @'
#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [string]$TokenPrefix = 'REDACTED',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $ProjectRoot ".fix-backups\remove-secrets-$stamp"
Write-Host "`n===[ گام ۱+۲: حذف فایل‌های حاوی اسرار ]===" -ForegroundColor Cyan
Write-Host "ProjectRoot : $ProjectRoot"
Write-Host "BackupDir   : $backup"
if ($DryRun) { Write-Host "Mode        : DRY-RUN" -ForegroundColor Yellow }
Write-Host ""
if (-not (Test-Path $ProjectRoot)) { throw "مسیر پروژه یافت نشد: $ProjectRoot" }
$gitAvailable = [bool](Get-Command git -ErrorAction SilentlyContinue)
$isGitRepo    = Test-Path (Join-Path $ProjectRoot '.git')
if (-not $DryRun) { New-Item -ItemType Directory -Path $backup -Force | Out-Null }
$secretFiles = @('.env', 'live.local.ps1', '.env.local')
$removed = @()
foreach ($file in $secretFiles) {
    $full = Join-Path $ProjectRoot $file
    if (-not (Test-Path $full)) { Write-Host "  [skip] $file (not found)" -ForegroundColor DarkGray; continue }
    $tracked = $false
    if ($gitAvailable -and $isGitRepo) {
        $null = git -C $ProjectRoot ls-files --error-unmatch -- $file 2>$null
        $tracked = ($LASTEXITCODE -eq 0)
    }
    if (-not $DryRun) {
        Copy-Item $full (Join-Path $backup $file) -Force
        Remove-Item $full -Force
        if ($tracked -and $gitAvailable -and $isGitRepo) {
            $null = git -C $ProjectRoot rm --cached --ignore-unmatch -- $file 2>$null
            Write-Host "  [removed+git] $file (tracked)" -ForegroundColor Green
        } else {
            Write-Host "  [removed] $file (untracked)" -ForegroundColor Green
        }
    } else {
        Write-Host "  [would-remove] $file (tracked=$tracked)" -ForegroundColor DarkGray
    }
    $removed += [PSCustomObject]@{ File = $file; Tracked = $tracked }
}
$envExample = Join-Path $ProjectRoot '.env.example'
if (-not (Test-Path $envExample)) {
    if (-not $DryRun) {
        "# FX-ARS env vars (copy to .env)`nFXARS_TELEGRAM_TOKEN=`nFXARS_TELEGRAM_CHAT_ID=`n" | Set-Content -Path $envExample -Encoding UTF8
        Write-Host "  [created] .env.example" -ForegroundColor Green
    }
}
$gitignore = Join-Path $ProjectRoot '.gitignore'
if (Test-Path $gitignore -and -not $DryRun) {
    $gi = Get-Content $gitignore -Raw
    foreach ($pattern in @('.env', '*.local.ps1')) {
        if ($gi -notmatch [regex]::Escape($pattern)) {
            Add-Content -Path $gitignore -Value "`n# FIX-SECRETS`n$pattern" -Encoding UTF8
            Write-Host "  [gitignore+] $pattern" -ForegroundColor Green
        }
    }
}
Write-Host "`n--- Scan for leaked tokens ---" -ForegroundColor Yellow
$scanSkipDirs = @('.git', '.fix-backups', '.cleanup-backups', '.hypothesis', '__pycache__', 'data', 'reports', 'build', 'dist')
$leaks = @()
$candidates = Get-ChildItem -Path $ProjectRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $skip = $false
    foreach ($d in $scanSkipDirs) { if ($_.FullName -match [regex]::Escape("\$d\")) { $skip = $true; break } }
    -not $skip -and $_.Length -lt 5MB -and $_.Extension -notin ('.pyc','.pyo','.so','.dll','.exe','.zip','.gz','.png','.jpg','.jpeg','.ico','.pdf')
}
foreach ($f in $candidates) {
    try {
        $c = Get-Content $f.FullName -Raw -ErrorAction Stop
        if ($c -match [regex]::Escape($TokenPrefix)) { $leaks += $f.FullName.Substring($ProjectRoot.Length).TrimStart('\') }
    } catch {}
}
if ($leaks.Count -eq 0) { Write-Host "  [OK] هیچ فایل دیگری توکن ندارد" -ForegroundColor Green }
else { Write-Host "  [WARN] $($leaks.Count) فایل:" -ForegroundColor Red; $leaks | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red } }
Write-Host "`n===[ خلاصه ]===" -ForegroundColor Cyan
foreach ($r in $removed) { Write-Host "  - $($r.File)  [tracked=$($r.Tracked)]" -ForegroundColor Green }
Write-Host "`n⚠️  توکن‌ها را از @BotFather با /revoke باطل کنید!" -ForegroundColor Yellow
if ($DryRun) { Write-Host "[DRY-RUN] هیچ تغییری اعمال نشد." -ForegroundColor Yellow }
'@

# ===========================================================================
# 03-Cleanup-Artifacts.ps1
# ===========================================================================
Write-Script '03-Cleanup-Artifacts.ps1' @'
#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $ProjectRoot ".fix-backups\cleanup-artifacts-$stamp"
Write-Host "`n===[ گام ۳: پاک‌سازی فایل‌های زائد ]===" -ForegroundColor Cyan
if (-not $DryRun) { New-Item -ItemType Directory -Path $backup -Force | Out-Null }
$stats = @{ 'pre-fix'=0; 'bak'=0; 'orig'=0; 'pycache'=0; 'pyc'=0; 'pyo'=0; 'hypothesis'=0; 'pytest'=0; 'mypy'=0; 'ruff'=0; 'tox'=0; 'build'=0; 'dist'=0; 'egg-info'=0; 'reports'=0 }
$bytesFreed = 0
$skipDirs = @('.git', '.fix-backups', '.cleanup-backups')
function Test-Skip($p) { foreach ($d in $script:skipDirs) { if ($p -match [regex]::Escape("\$d\")) { return $true } } return $false }
function Remove-Safe($p, $r, [switch]$Dir) {
    if (-not (Test-Path -LiteralPath $p)) { return }
    $rel = $p.Substring($ProjectRoot.Length).TrimStart('\')
    try {
        if ($Dir) {
            $size = (Get-ChildItem -LiteralPath $p -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
            if ($null -eq $size) { $size = 0 }
            if (-not $DryRun) {
                $dest = Join-Path $backup $rel
                New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
                Copy-Item -LiteralPath $p -Destination $dest -Recurse -Force
                Remove-Item -LiteralPath $p -Recurse -Force
            }
            $script:bytesFreed += $size
            $script:stats[$r] += 1
            Write-Host "  [DIR/$r] $rel" -ForegroundColor Green
        } else {
            $size = (Get-Item -LiteralPath $p).Length
            if (-not $DryRun) {
                $dest = Join-Path $backup $rel
                New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
                Copy-Item -LiteralPath $p -Destination $dest -Force
                Remove-Item -LiteralPath $p -Force
            }
            $script:bytesFreed += $size
            $script:stats[$r] += 1
            Write-Host "  [FILE/$r] $rel" -ForegroundColor Green
        }
    } catch { Write-Host "  [FAIL] $rel : $_" -ForegroundColor Red }
}
foreach ($pat in @('*.pre-fix-*','*.bak','*.orig')) {
    $r = switch ($pat) { '*.pre-fix-*' {'pre-fix'} '*.bak' {'bak'} '*.orig' {'orig'} }
    Get-ChildItem -Path $ProjectRoot -Recurse -File -Filter $pat -ErrorAction SilentlyContinue | Where-Object { -not (Test-Skip $_.FullName) } | ForEach-Object { Remove-Safe $_.FullName $r }
}
Get-ChildItem -Path $ProjectRoot -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Where-Object { -not (Test-Skip $_.FullName) } | ForEach-Object { Remove-Safe $_.FullName 'pycache' -Dir }
foreach ($item in @(@{P='.hypothesis';R='hypothesis'},@{P='.pytest_cache';R='pytest'},@{P='.mypy_cache';R='mypy'},@{P='.ruff_cache';R='ruff'},@{P='.tox';R='tox'})) {
    $f = Join-Path $ProjectRoot $item.P
    if (Test-Path $f) { Remove-Safe $f $item.R -Dir }
}
$reports = Join-Path $ProjectRoot 'reports'
if (Test-Path $reports) {
    Get-ChildItem -Path $reports -Recurse -File -Include '*.html','*.md' -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne '.gitkeep' } | ForEach-Object { Remove-Safe $_.FullName 'reports' }
}
Write-Host "`n===[ خلاصه ]===" -ForegroundColor Cyan
$total = 0
foreach ($k in $stats.Keys) { if ($stats[$k] -gt 0) { Write-Host "  $k : $($stats[$k])" -ForegroundColor Green; $total += $stats[$k] } }
Write-Host "  مجموع: $total" -ForegroundColor Cyan
Write-Host "  آزادشده: $([math]::Round($bytesFreed/1MB,2)) MB" -ForegroundColor Cyan
'@

# ===========================================================================
# 04-Sync-Version.ps1
# ===========================================================================
Write-Script '04-Sync-Version.ps1' @'
#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$versionPy = Join-Path $ProjectRoot 'fxars\version.py'
if (-not (Test-Path $versionPy)) { throw "version.py یافت نشد" }
$content = Get-Content $versionPy -Raw -Encoding UTF8
if ($content -notmatch 'CODE_VERSION\s*=\s*"([^"]+)"') { throw "CODE_VERSION پیدا نشد" }
$codeVersion = $Matches[1]
Write-Host "Source: $codeVersion" -ForegroundColor Green
$pyproject = Join-Path $ProjectRoot 'pyproject.toml'
if (Test-Path $pyproject) {
    $ptext = Get-Content $pyproject -Raw -Encoding UTF8
    if ($ptext -match '(?m)^version\s*=\s*"([^"]+)"') {
        $old = $Matches[1]
        if ($old -ne $codeVersion) {
            $newText = $ptext -replace '(?m)^version\s*=\s*"[^"]+"', "version = `"$codeVersion`""
            if (-not $DryRun) { Set-Content -Path $pyproject -Value $newText -Encoding UTF8 -NoNewline }
            Write-Host "  [pyproject.toml] $old -> $codeVersion" -ForegroundColor Green
        } else { Write-Host "  [pyproject.toml] already $codeVersion" -ForegroundColor DarkGray }
    }
}
$impl = Join-Path $ProjectRoot 'docs\IMPLEMENTATION_REPORT.md'
if (Test-Path $impl) {
    $itext = Get-Content $impl -Raw -Encoding UTF8
    if ($itext -match 'نسخه پیاده‌سازی:\s*`[^`]+`') {
        $newText = $itext -replace 'نسخه پیاده‌سازی:\s*`[^`]+`', "نسخه پیاده‌سازی: ``$codeVersion``"
        if (-not $DryRun) { Set-Content -Path $impl -Value $newText -Encoding UTF8 -NoNewline }
        Write-Host "  [IMPLEMENTATION_REPORT.md] synced" -ForegroundColor Green
    }
}
Write-Host "Source of truth: $codeVersion" -ForegroundColor Cyan
'@

# ===========================================================================
# 05-Cleanup-Root.ps1
# ===========================================================================
Write-Script '05-Cleanup-Root.ps1' @'
#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $ProjectRoot "scripts\archive\$stamp"
$logArchive = Join-Path $ProjectRoot "scripts\archive\logs-$stamp"
if (-not $DryRun) {
    New-Item -ItemType Directory -Path $archive -Force | Out-Null
    New-Item -ItemType Directory -Path $logArchive -Force | Out-Null
}
$patterns = @('add_*.py','fix_*.py','install_*.py','check_*.py','debug_*.py','seed_*.py','apply-*.ps1','test_mt5.py','test_analysis_mt5.py','FXARS-Start.ps1','live.local.ps1','get_chat_id.py','get_chat_id.py.bak','.consult-job-id','.consult-process-id')
$moved = 0
foreach ($pat in $patterns) {
    Get-ChildItem -Path $ProjectRoot -File -Filter $pat -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -eq '05-Cleanup-Root.ps1') { return }
        if (-not $DryRun) {
            Move-Item -LiteralPath $_.FullName -Destination (Join-Path $archive $_.Name) -Force
            Write-Host "  [moved] $($_.Name)" -ForegroundColor Green
        } else { Write-Host "  [would-move] $($_.Name)" -ForegroundColor DarkGray }
        $script:moved++
    }
}
Get-ChildItem -Path $ProjectRoot -File -Filter '*.log' -ErrorAction SilentlyContinue | ForEach-Object {
    if (-not $DryRun) {
        Move-Item -LiteralPath $_.FullName -Destination (Join-Path $logArchive $_.Name) -Force
        Write-Host "  [moved-log] $($_.Name)" -ForegroundColor Green
    }
    $script:moved++
}
Write-Host "  مجموع منتقل‌شده: $moved" -ForegroundColor Cyan
'@

# ===========================================================================
# 06-Update-Docs.ps1
# ===========================================================================
Write-Script '06-Update-Docs.ps1' @'
#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "`n===[ گام ۶: آپدیت اسناد ]===" -ForegroundColor Cyan
Write-Host "PowerShell : $($PSVersionTable.PSVersion)"
$testCount = $null
$skippedCount = 0
if (-not $SkipTests) {
    Write-Host "--- اجرای تست‌ها ---" -ForegroundColor Yellow
    Push-Location $ProjectRoot
    try {
        $output = & python -B -m unittest discover -s tests 2>&1 | Out-String
        if ($output -match 'Ran\s+(\d+)\s+tests') {
            $testCount = [int]$Matches[1]
            Write-Host "  [OK] Ran $testCount tests" -ForegroundColor Green
        }
        if ($output -match 'OK\s*\(skipped=(\d+)\)') {
            $skippedCount = [int]$Matches[1]
            Write-Host "  [OK] OK (skipped=$skippedCount)" -ForegroundColor Green
        } elseif ($output -match '(?m)^OK\s*$') {
            Write-Host "  [OK] OK" -ForegroundColor Green
        } elseif ($output -match 'FAILED') {
            Write-Host "  [WARN] FAILED" -ForegroundColor Red
        }
    } finally { Pop-Location }
}
if ($null -ne $testCount) {
    foreach ($f in @('README.md','docs\PHASES.md','docs\IMPLEMENTATION_REPORT.md')) {
        $full = Join-Path $ProjectRoot $f
        if (-not (Test-Path $full)) { continue }
        $t = Get-Content $full -Raw -Encoding UTF8
        $orig = $t
        $t = $t -replace '\*\*۳۶۳\s+تست\*\*', "**$testCount تست**"
        $t = $t -replace '\*\*363\s+تست\*\*', "**$testCount تست**"
        $t = $t -replace '\(۳۳۸ تست\)', "($testCount تست)"
        $t = $t -replace '\(338 تست\)', "($testCount تست)"
        if ($t -ne $orig) {
            if (-not $DryRun) { Set-Content -Path $full -Value $t -Encoding UTF8 -NoNewline }
            Write-Host "  [updated] $f" -ForegroundColor Green
        }
    }
}
$settings = Join-Path $ProjectRoot 'config\settings.json'
if (Test-Path $settings) {
    $s = Get-Content $settings -Raw -Encoding UTF8
    if ($s -match '"phase"\s*:\s*"DEMO"') {
        if (-not $DryRun) {
            $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
            $b = Join-Path $ProjectRoot ".fix-backups\settings-$ts"
            New-Item -ItemType Directory -Path $b -Force | Out-Null
            Copy-Item $settings (Join-Path $b 'settings.json') -Force
            $s = $s -replace '"phase"\s*:\s*"DEMO"', '"phase": "READ_ONLY"'
            Set-Content -Path $settings -Value $s -Encoding UTF8 -NoNewline
        }
        Write-Host "  [settings.json] DEMO -> READ_ONLY" -ForegroundColor Green
    }
}
Write-Host "`nDONE" -ForegroundColor Cyan
'@

Write-Host "`n=== نتیجه ===" -ForegroundColor Cyan
Get-ChildItem -Path $here -Filter '*.ps1' | ForEach-Object { Write-Host "  $($_.Name)  ($([math]::Round($_.Length/1KB,1)) KB)" -ForegroundColor Green }
Write-Host "`nحالا اجرا کنید:" -ForegroundColor Yellow
Write-Host "  cd C:\project\FX" -ForegroundColor Yellow
Write-Host "  pwsh -File .\scripts\improve\06-Update-Docs.ps1" -ForegroundColor Yellow
