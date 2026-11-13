#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'precompute-comment' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $bt = Join-Path $ProjectRoot 'fxars\research\backtest.py'
    $text = Read-TextFile -FullPath $bt
    if ($text -match 'FIX-12-PRECOMPUTE-COMMENT') { Write-Skip "از قبل patch شده"; return }
    $old = '        self._precomputed_structure_per_bar = None  # فعلاً پیاده نشده'
    $new = @'
        # FIX-12-PRECOMPUTE-COMMENT: در حال حاضر فقط swings و indicators precompute می‌شوند.
        self._precomputed_structure_per_bar = None
'@
    if ($text.Contains($old)) {
        $text = $text.Replace($old, $new.TrimEnd())
    } else {
        Write-Skip "کامنت قدیمی پیدا نشد (شاید قبلاً اصلاح شده)"
    }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $bt
    $text = $text.TrimEnd() + "`n`n# FIX-12-PRECOMPUTE-COMMENT`n"
    Write-TextFile -FullPath $bt -Content $text
    if (Test-PyCompile -FullPath $bt) { Write-Ok "backtest.py patch شد" }
    else { Restore-File -FullPath $bt | Out-Null }
    Write-Host "`n===[ DONE: gam 12 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
