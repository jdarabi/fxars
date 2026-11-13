#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'intermarket' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $im = Join-Path $ProjectRoot 'fxars\analysis\intermarket.py'
    $text = Read-TextFile -FullPath $im
    if ($text -match 'FIX-09-NO-ZERO-RETURN') { Write-Skip "از قبل patch شده"; return }

    $old = @'
                main_return = float((candle.close - previous.close) / previous.close) if previous.close else 0.0
                ref_return = float((reference.close - reference_previous.close) / reference_previous.close) if reference_previous.close else 0.0
'@
    $new = @'
                # FIX-09-NO-ZERO-RETURN
                if not previous.close or not reference_previous.close:
                    continue
                main_return = float((candle.close - previous.close) / previous.close)
                ref_return = float((reference.close - reference_previous.close) / reference_previous.close)
'@
    if (-not $text.Contains($old)) { Write-Err "anchor پیدا نشد"; return }
    $text = $text.Replace($old, $new.TrimEnd())

    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $im
    $text = $text.TrimEnd() + "`n`n# FIX-09-NO-ZERO-RETURN`n"
    Write-TextFile -FullPath $im -Content $text
    if (Test-PyCompile -FullPath $im) { Write-Ok "intermarket.py patch شد" }
    else { Restore-File -FullPath $im | Out-Null }
    Write-Host "`n===[ DONE: gam 09 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
