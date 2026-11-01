#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [switch]$SkipBackup,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
Write-Host "`n================ FX-ARS FIX PIPELINE ================" -ForegroundColor Magenta
Write-Host "ProjectRoot: $ProjectRoot" -ForegroundColor Magenta

$steps = @(
    @{ Name = '00-Backup';                    Script = '00-Backup.ps1';                    Optional = $SkipBackup },
    @{ Name = '01-IngestionTransaction';      Script = '01-Fix-IngestionTransaction.ps1' },
    @{ Name = '02-DataQualityVerdict';        Script = '02-Fix-DataQualityVerdict.ps1' },
    @{ Name = '03-PrimarySourceSelection';    Script = '03-Fix-PrimarySourceSelection.ps1' },
    @{ Name = '04-FundamentalModuleHistory';  Script = '04-Fix-FundamentalModuleHistory.ps1' },
    @{ Name = '05-BacktestParity';            Script = '05-Fix-BacktestParity.ps1' },
    @{ Name = '06-RiskGateFailClosed';        Script = '06-Fix-RiskGateFailClosed.ps1' },
    @{ Name = '07-ApiValidationErrors';       Script = '07-Fix-ApiValidationErrors.ps1' },
    @{ Name = '08-RateLimitBypass';           Script = '08-Fix-RateLimitBypass.ps1' },
    @{ Name = '09-IdempotencyAtomicity';      Script = '09-Fix-IdempotencyAtomicity.ps1' },
    @{ Name = '10-IdentitySessions';          Script = '10-Fix-IdentitySessions.ps1' },
    @{ Name = '11-ExecutionBrokerReject';     Script = '11-Fix-ExecutionBrokerReject.ps1' },
    @{ Name = '12-ApiCandlesPagination';      Script = '12-Fix-ApiCandlesPagination.ps1' },
    @{ Name = '13-ResultHashCompleteness';    Script = '13-Fix-ResultHashCompleteness.ps1' },
    @{ Name = '14-RegressionTests';           Script = '14-Add-RegressionTests.ps1' }
)

$failures = 0
foreach ($step in $steps) {
    if ($step.Optional) {
        Write-Host "`n[SKIP] $($step.Name)" -ForegroundColor DarkGray
        continue
    }
    $script = Join-Path $PSScriptRoot $step.Script
    if (-not (Test-Path $script)) {
        Write-Host "`n[MISSING] $($step.Name) → $script" -ForegroundColor Red
        $failures++
        continue
    }
    Write-Host "`n[RUN] $($step.Name)" -ForegroundColor Cyan
    try {
        & $script -ProjectRoot $ProjectRoot
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Exit code $LASTEXITCODE"
        }
    }
    catch {
        Write-Host "  [FAIL] $($step.Name): $_" -ForegroundColor Red
        $failures++
        if (-not (Read-Host "ادامه می‌دهید؟ (y/N)" -eq 'y')) { break }
    }
}

if (-not $SkipTests) {
    Write-Host "`n[RUN] 15-Run-Tests" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot '15-Run-Tests.ps1') -ProjectRoot $ProjectRoot
}

Write-Host "`n================ DONE ($failures failures) ================" -ForegroundColor Magenta
exit $failures