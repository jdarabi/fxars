#Requires -Version 7.0
# اسکریپت عیب‌یابی مسیر تحلیل/استراتژی روی سرور محلی.
# رمز دمو از متغیر محیطی خوانده می‌شود و در فایل ذخیره نمی‌شود.
[CmdletBinding()]
param([string]$Base = "http://127.0.0.1:8080")

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $env:FXARS_DEMO_PASSWORD) {
    Write-Host "FXARS_DEMO_PASSWORD تنظیم نشده است؛ رمز حساب دمو را در متغیر محیطی قرار دهید." -ForegroundColor Red
    return
}

Write-Host "`n===[ تست استراتژی ]===" -ForegroundColor Cyan
Write-Host "Base: $Base`n"

function New-IdempotencyKey {
    return [guid]::NewGuid().ToString()
}

function Invoke-PostWithIdem {
    param(
        [string]$Uri,
        [string]$Body,
        [hashtable]$Headers
    )
    $allHeaders = @{
        "Idempotency-Key" = (New-IdempotencyKey)
    }
    if ($Headers) {
        foreach ($k in $Headers.Keys) { $allHeaders[$k] = $Headers[$k] }
    }
    return Invoke-RestMethod -Uri $Uri -Method POST -Body $Body `
        -ContentType "application/json" -Headers $allHeaders `
        -TimeoutSec 120
}

try {
    Write-Host "[1] health..." -ForegroundColor Yellow
    try {
        $health = Invoke-RestMethod -Uri "$Base/api/v1/health" -TimeoutSec 5
        Write-Host "  OK: $($health.status)" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL: سرور بالا نیست" -ForegroundColor Red
        Write-Host "  دستور: python -m fxars serve --port 8080" -ForegroundColor Yellow
        return
    }

    Write-Host "`n[2] demo-totp..." -ForegroundColor Yellow
    try {
        $totpResp = Invoke-RestMethod -Uri "$Base/api/v1/auth/demo-totp?username=admin" -TimeoutSec 5
        $totpCode = $totpResp.code
        Write-Host "  code: $totpCode (expires_in: $($totpResp.expires_in)s)" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails) { Write-Host "  body: $($_.ErrorDetails.Message)" -ForegroundColor Red }
        return
    }

    Write-Host "`n[3] login..." -ForegroundColor Yellow
    $loginBody = @{
        username = "admin"
        password = $env:FXARS_DEMO_PASSWORD
        totp_code = $totpCode
    } | ConvertTo-Json
    try {
        $login = Invoke-RestMethod -Uri "$Base/api/v1/auth/login" -Method POST -Body $loginBody -ContentType "application/json" -TimeoutSec 10
        $headers = @{ "Authorization" = "Bearer $($login.token)" }
        Write-Host "  OK: role=$($login.user.role)" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails) { Write-Host "  body: $($_.ErrorDetails.Message)" -ForegroundColor Red }
        return
    }

    Write-Host "`n[4] trading/status..." -ForegroundColor Yellow
    try {
        $status = Invoke-RestMethod -Uri "$Base/api/v1/trading/status" -Method GET -Headers $headers -TimeoutSec 10
        Write-Host "  connected: $($status.connected)" -ForegroundColor Green
        Write-Host "  phase: $($status.phase)" -ForegroundColor Green
        if ($status.account) {
            Write-Host "  account: $($status.account.login) / $($status.account.server)" -ForegroundColor Green
            Write-Host "  balance: $($status.account.balance) $($status.account.currency)" -ForegroundColor Green
        }
    } catch {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor Red
    }

    Write-Host "`n[5] strategy/analyze (EURUSD/H1)..." -ForegroundColor Yellow
    $stratBody = @{
        instrument_id = "EURUSD"
        timeframe = "H1"
        bars = 2000
    } | ConvertTo-Json -Compress

    try {
        $analysis = Invoke-PostWithIdem `
            -Uri "$Base/api/v1/strategy/analyze" `
            -Body $stratBody `
            -Headers $headers

        Write-Host "`n  === نتیجه تحلیل ===" -ForegroundColor Cyan
        Write-Host "  signal: $($analysis.signal)" -ForegroundColor $(if ($analysis.signal -eq 'NO_TRADE') { 'Yellow' } else { 'Green' })
        Write-Host "  reason: $($analysis.reason)" -ForegroundColor Green
        if ($analysis.best) {
            Write-Host "`n  بهترین استراتژی: $($analysis.best.name)" -ForegroundColor Green
            Write-Host "    trades: $($analysis.best.trades)" -ForegroundColor Green
            Write-Host "    net_profit: $($analysis.best.net_profit)" -ForegroundColor Green
            Write-Host "    sharpe: $($analysis.best.sharpe)" -ForegroundColor Green
            Write-Host "    profit_factor: $($analysis.best.profit_factor)" -ForegroundColor Green
            Write-Host "    max_drawdown_pct: $($analysis.best.max_drawdown_pct)" -ForegroundColor Green
            Write-Host "    score: $($analysis.best.score)" -ForegroundColor Green
            if ($analysis.entry) {
                Write-Host "`n  سیگنال فعلی:" -ForegroundColor Yellow
                Write-Host "    entry: $($analysis.entry)" -ForegroundColor Green
                Write-Host "    stop: $($analysis.stop)" -ForegroundColor Green
                Write-Host "    target: $($analysis.target)" -ForegroundColor Green
            }
        }
        Write-Host "`n  === همه استراتژی‌ها ===" -ForegroundColor Cyan
        foreach ($r in $analysis.all) {
            Write-Host "  - $($r.name): trades=$($r.trades) sharpe=$($r.sharpe) pf=$($r.profit_factor) score=$($r.score)" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails) { Write-Host "  body: $($_.ErrorDetails.Message)" -ForegroundColor Red }
        return
    }
}
catch {
    Write-Host "`n[خطای غیرمنتظره] $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
}
finally {
    Write-Host "`n=== پایان ===" -ForegroundColor Cyan
}
