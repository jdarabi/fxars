#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'cli-dedup' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $cli = Join-Path $ProjectRoot 'fxars\cli\main.py'
    if (-not (Test-Path -LiteralPath $cli)) { Write-Err "main.py پیدا نشد"; return }
    $text = Read-TextFile -FullPath $cli
    if ($text -match 'FIX-04-DEDUP') { Write-Skip "از قبل patch شده"; return }
    $defPattern = 'def _copy_sqlite_to_postgres\('
    $matches = [regex]::Matches($text, $defPattern)
    Write-Info "تعداد تعریف: $($matches.Count)"
    if ($matches.Count -lt 2) { Write-Skip "dedup لازم نیست"; return }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    $def2Start = $matches[1].Index
    $afterDef2 = $text.Substring($def2Start)
    $nextDefMatch = [regex]::Match($afterDef2, '\ndef (?!_copy_sqlite_to_postgres)\w+\(')
    if (-not $nextDefMatch.Success) {
        $nextDefMatch = [regex]::Match($afterDef2, '\nif __name__')
        if (-not $nextDefMatch.Success) { Write-Err "پایان بلوک دوم پیدا نشد"; return }
    }
    $def2End = $def2Start + $nextDefMatch.Index
    Backup-File -FullPath $cli
    $newText = $text.Substring(0, $def2Start) + $text.Substring($def2End)
    $newText = $newText.TrimEnd() + "`n`n# FIX-04-DEDUP`n"
    Write-TextFile -FullPath $cli -Content $newText
    if (-not (Test-PyCompile -FullPath $cli)) { Restore-File -FullPath $cli | Out-Null; return }
    $final = Read-TextFile -FullPath $cli
    $count = ([regex]::Matches($final, $defPattern)).Count
    Write-Info "تعداد نهایی: $count"
    if ($count -eq 1) { Write-Ok "dedup موفق" } else { Write-Warn2 "بررسی دستی لازم" }
    Write-Host "`n===[ DONE: gam 04 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
