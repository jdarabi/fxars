#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'fold-zero' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $tu = Join-Path $ProjectRoot 'fxars\core\timeutil.py'
    $text = Read-TextFile -FullPath $tu
    if ($text -match 'FIX-13-FOLD-ZERO') { Write-Skip "از قبل patch شده"; return }
    $oldW1 = @'
            return datetime(
                year=monday_date.year, month=monday_date.month, day=monday_date.day,
                hour=0, minute=0, second=0, microsecond=0,
                tzinfo=dt.tzinfo, fold=dt.fold,
            )
'@
    $newW1 = @'
            # FIX-13-FOLD-ZERO
            return datetime(
                year=monday_date.year, month=monday_date.month, day=monday_date.day,
                hour=0, minute=0, second=0, microsecond=0,
                tzinfo=dt.tzinfo, fold=0,
            )
'@
    if ($text.Contains($oldW1)) {
        $text = $text.Replace($oldW1, $newW1.TrimEnd())
        Write-Info "W1 fold=0"
    } else { Write-Skip "W1 anchor پیدا نشد" }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $tu
    $text = $text.TrimEnd() + "`n`n# FIX-13-FOLD-ZERO`n"
    Write-TextFile -FullPath $tu -Content $text
    if (Test-PyCompile -FullPath $tu) { Write-Ok "timeutil.py patch شد" }
    else { Restore-File -FullPath $tu | Out-Null }
    Write-Host "`n===[ DONE: gam 13 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
