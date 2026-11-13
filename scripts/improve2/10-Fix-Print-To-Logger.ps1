#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'print-to-logger' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $pf = Join-Path $ProjectRoot 'fxars\platform.py'
    $ptext = Read-TextFile -FullPath $pf
    if ($ptext -match 'FIX-10-PRINT-TO-LOGGER') { Write-Skip "platform.py از قبل patch شده" }
    else {
        $old = '            print(f"[WARN] MT5Broker unavailable ({exc}); falling back to PaperBroker")'
        $new = @'
            from fxars.core.logging_setup import get_logger
            get_logger("platform").warning(
                "MT5Broker unavailable; falling back to PaperBroker",
                extra={"data": {"error": str(exc)}},
            )
'@
        if (-not $ptext.Contains($old)) { Write-Err "platform.py anchor پیدا نشد" }
        elseif ($DryRun) { Write-Warn2 "DRY-RUN: platform.py" }
        else {
            Backup-File -FullPath $pf
            $patched = $ptext.Replace($old, $new.TrimEnd())
            $patched = $patched.TrimEnd() + "`n`n# FIX-10-PRINT-TO-LOGGER`n"
            Write-TextFile -FullPath $pf -Content $patched
            if (Test-PyCompile -FullPath $pf) { Write-Ok "platform.py patch شد" }
            else { Restore-File -FullPath $pf | Out-Null }
        }
    }
    Write-Host "`n===[ DONE: gam 10 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
