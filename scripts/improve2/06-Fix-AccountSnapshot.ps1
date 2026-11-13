#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'account-snapshot' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $account = Join-Path $ProjectRoot 'fxars\risk\account.py'
    $text = Read-TextFile -FullPath $account
    if ($text -match 'FIX-06-MAX-POSITIONS') { Write-Skip "از قبل patch شده"; return }
    $old = '        open_positions=int(data.get("open_positions", len(positions))),'
    $new = @'
        # FIX-06-MAX-POSITIONS
        open_positions=max(int(data.get("open_positions", len(positions))), len(positions)),
'@
    if (-not $text.Contains($old)) { Write-Err "anchor پیدا نشد"; return }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $account
    $patched = $text.Replace($old, $new.TrimEnd())
    $patched = $patched.TrimEnd() + "`n`n# FIX-06-MAX-POSITIONS`n"
    Write-TextFile -FullPath $account -Content $patched
    if (Test-PyCompile -FullPath $account) { Write-Ok "account.py patch شد" }
    else { Restore-File -FullPath $account | Out-Null }
    Write-Host "`n===[ DONE: gam 06 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
