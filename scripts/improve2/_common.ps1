#Requires -Version 7.0
$script:ProjectRoot = 'C:\project\FX'
$script:BackupRoot  = $null

function Write-Info  ($msg) { Write-Host "  [INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err   ($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Skip  ($msg) { Write-Host "  [SKIP] $msg" -ForegroundColor DarkGray }

function Pause-IfNeeded {
    param([switch]$NoPause)
    if ($NoPause) { return }
    if ([Console]::IsInputRedirected) { return }
    Write-Host "`nبرای بستن پنجره Enter بزنید..." -ForegroundColor DarkGray
    try { Read-Host | Out-Null } catch { }
}

function Initialize-Script {
    param([string]$Name, [string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun)
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
    $script:ProjectRoot = $ProjectRoot
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script:BackupRoot = Join-Path $ProjectRoot ".fix-backups\improve2\$Name-$stamp"
    New-Item -ItemType Directory -Path $script:BackupRoot -Force | Out-Null
    Write-Host "`n===[ $Name ]===" -ForegroundColor Cyan
    Write-Host "ProjectRoot : $ProjectRoot"
    Write-Host "BackupDir   : $($script:BackupRoot)"
    if ($DryRun) { Write-Host "Mode        : DRY-RUN" -ForegroundColor Yellow }
    Write-Host ""
}

function Backup-File {
    param([string]$FullPath)
    if (-not $script:BackupRoot) {
        $script:BackupRoot = Join-Path $script:ProjectRoot ".fix-backups\improve2\manual-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        New-Item -ItemType Directory -Path $script:BackupRoot -Force | Out-Null
    }
    $rel = $FullPath.Substring($script:ProjectRoot.Length).TrimStart('\')
    $dst = Join-Path $script:BackupRoot $rel
    New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $FullPath -Destination $dst -Force
    Write-Ok "backup: $rel"
}

function Restore-File {
    param([string]$FullPath)
    $rel = $FullPath.Substring($script:ProjectRoot.Length).TrimStart('\')
    $src = Join-Path $script:BackupRoot $rel
    if (-not (Test-Path $src)) { Write-Err "backup پیدا نشد: $rel"; return $false }
    Copy-Item -LiteralPath $src -Destination $FullPath -Force
    Write-Warn2 "rollback: $rel"
    return $true
}

function Read-TextFile {
    param([string]$FullPath)
    return [System.IO.File]::ReadAllText($FullPath, [System.Text.Encoding]::UTF8)
}

function Write-TextFile {
    param([string]$FullPath, [string]$Content)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($FullPath, $Content, $utf8NoBom)
}

function Test-PyCompile {
    param([string]$FullPath)
    $out = & python -m py_compile $FullPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "py_compile ناموفق: $(Split-Path -Leaf $FullPath)"
        $out | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        return $false
    }
    return $true
}

function Assert-Pwsh7 {
    if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ لازم است" }
}

function Assert-Python {
    try { $py = Get-Command python -ErrorAction Stop; Write-Ok "python: $($py.Source)"; return $true }
    catch { Write-Err "python در PATH نیست"; return $false }
}
