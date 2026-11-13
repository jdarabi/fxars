#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'datetime-utc' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $cf = Join-Path $ProjectRoot 'fxars\live\consult.py'
    if (-not (Test-Path -LiteralPath $cf)) { Write-Skip "consult.py موجود نیست"; return }
    $text = Read-TextFile -FullPath $cf
    if ($text -match 'FIX-11-DATETIME-UTC') { Write-Skip "از قبل patch شده"; return }
    $old = "datetime.now().strftime('%H:%M:%S')"
    $new = "datetime.now(tz=UTC).strftime('%H:%M:%S')"
    if (-not $text.Contains($old)) { Write-Skip "anchor پیدا نشد"; return }
    $text = $text.Replace($old, $new)
    if ($text -notmatch 'from datetime import.*\bUTC\b') {
        if ($text -match 'from datetime import ([^\n]+)') {
            $oldImport = $Matches[0]
            if ($oldImport -notmatch '\bUTC\b') {
                $text = $text.Replace($oldImport, $oldImport.TrimEnd() + ', UTC')
            }
        }
    }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $cf
    $text = $text.TrimEnd() + "`n`n# FIX-11-DATETIME-UTC`n"
    Write-TextFile -FullPath $cf -Content $text
    if (Test-PyCompile -FullPath $cf) { Write-Ok "consult.py patch شد" }
    else { Restore-File -FullPath $cf | Out-Null }
    Write-Host "`n===[ DONE: gam 11 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
