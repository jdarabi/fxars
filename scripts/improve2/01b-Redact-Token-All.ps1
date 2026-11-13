#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [string]$TokenPrefix = 'REDACTED',
    [string]$Placeholder = '<REDACTED-TOKEN>',
    [switch]$DryRun,
    [switch]$NoPause
)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"

try {
    Write-Host "`n===[ gam 01b: redact token ]===" -ForegroundColor Cyan
    $skipDirs = @('.git','.fix-backups','.cleanup-backups','.hypothesis','__pycache__','data','reports','build','dist','.ruff_cache','.mypy_cache','.pytest_cache','.tox')
    $binExt = @('.pyc','.pyo','.so','.dll','.exe','.zip','.gz','.tar','.png','.jpg','.jpeg','.ico','.pdf','.docx','.xlsx','.db','.db-wal','.db-shm')

    $files = Get-ChildItem -Path $ProjectRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
        $skip = $false
        foreach ($d in $skipDirs) { if ($_.FullName -match [regex]::Escape("\$d\")) { $skip = $true; break } }
        -not $skip -and $_.Length -lt 5MB -and $_.Extension -notin $binExt
    }

    $tokenPattern = '\b\d{9,10}:[A-Za-z0-9_-]{35}\b'
    $leaks = @()
    foreach ($f in $files) {
        try {
            $c = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)
            if ($c -match [regex]::Escape($TokenPrefix)) {
                $leaks += [PSCustomObject]@{ FullPath = $f.FullName; Relative = $f.FullName.Substring($ProjectRoot.Length).TrimStart('\'); Content = $c }
            }
        } catch {}
    }

    if ($leaks.Count -eq 0) { Write-Ok "هیچ توکنی پیدا نشد"; return }

    Write-Warn2 "$($leaks.Count) فایل حاوی توکن:"
    $leaks | ForEach-Object { Write-Host "    - $($_.Relative)" -ForegroundColor Yellow }

    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path $ProjectRoot ".fix-backups\improve2\redact-$stamp"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    foreach ($leak in $leaks) {
        $dst = Join-Path $backupDir $leak.Relative
        New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $leak.FullPath -Destination $dst -Force

        $new = [regex]::Replace($leak.Content, $tokenPattern, $Placeholder)
        if ($new -eq $leak.Content) {
            $new = $leak.Content -replace [regex]::Escape($TokenPrefix), 'REDACTED'
        }
        if ($new -ne $leak.Content) {
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($leak.FullPath, $new, $utf8NoBom)
            Write-Ok "redacted: $($leak.Relative)"
        }
    }

    # بازبینی
    $remaining = @()
    foreach ($f in $files) {
        try {
            $c = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)
            if ($c -match [regex]::Escape($TokenPrefix)) { $remaining += $f.FullName.Substring($ProjectRoot.Length).TrimStart('\') }
        } catch {}
    }
    if ($remaining.Count -eq 0) { Write-Ok "همه redact شدند" }
    else { Write-Err "$($remaining.Count) فایل باقی ماند"; $remaining | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red } }

    Write-Host "`n⚠️  توکن را از @BotFather با /revoke باطل کنید!" -ForegroundColor Yellow
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
