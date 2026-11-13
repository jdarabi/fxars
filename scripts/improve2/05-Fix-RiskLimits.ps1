#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'risk-limits' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $gate = Join-Path $ProjectRoot 'fxars\risk\gate.py'
    $gateText = Read-TextFile -FullPath $gate
    if ($gateText -match 'FIX-05-MIN-LIMITS') { Write-Skip "gate.py از قبل patch شده" }
    else {
        $old1 = '        daily_limit = account.max_daily_loss if account and account.max_daily_loss is not None else policy.daily_loss_limit'
        $new1 = @'
        # FIX-05-MIN-LIMITS
        if account is not None and account.max_daily_loss is not None:
            daily_limit = min(account.max_daily_loss, policy.daily_loss_limit)
        else:
            daily_limit = policy.daily_loss_limit
'@
        $old2 = '        drawdown_limit = account.max_drawdown if account and account.max_drawdown is not None else policy.drawdown_stop'
        $new2 = @'
        # FIX-05-MIN-LIMITS
        if account is not None and account.max_drawdown is not None:
            drawdown_limit = min(account.max_drawdown, policy.drawdown_stop)
        else:
            drawdown_limit = policy.drawdown_stop
'@
        if (-not $gateText.Contains($old1)) { Write-Err "daily_limit anchor پیدا نشد" }
        elseif (-not $gateText.Contains($old2)) { Write-Err "drawdown_limit anchor پیدا نشد" }
        elseif ($DryRun) { Write-Warn2 "DRY-RUN: gate.py" }
        else {
            Backup-File -FullPath $gate
            $patched = $gateText.Replace($old1, $new1.TrimEnd()).Replace($old2, $new2.TrimEnd())
            $patched = $patched.TrimEnd() + "`n`n# FIX-05-MIN-LIMITS`n"
            Write-TextFile -FullPath $gate -Content $patched
            if (Test-PyCompile -FullPath $gate) { Write-Ok "gate.py patch شد" }
            else { Restore-File -FullPath $gate | Out-Null }
        }
    }
    Write-Host "`n===[ DONE: gam 05 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
