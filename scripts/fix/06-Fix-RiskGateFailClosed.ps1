#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\risk\gate.py'
Write-Host "[FIX-06] Risk Gate Fail-Closed" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-06-RISK-FAIL-CLOSED') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

# 6.1 حساب تازه: timestamp آینده Fail
$oldFresh = @'
        add("account_snapshot_fresh",
            account is not None and (now - account.taken_at).total_seconds() <= policy.max_account_age_seconds,
            "تصویر حساب تازه است.",
            None if account is None else round((now - account.taken_at).total_seconds(), 1), policy.max_account_age_seconds)
'@
$newFresh = @'
        # FIX-06-RISK-FAIL-CLOSED: حساب آینده یا خارج از TTL ⇒ Fail
        account_age_seconds: float | None = None
        if account is not None:
            account_age_seconds = (now - account.taken_at).total_seconds()
        account_fresh = (
            account_age_seconds is not None
            and -5.0 <= account_age_seconds <= policy.max_account_age_seconds
        )
        add("account_snapshot_fresh", account_fresh,
            "تصویر حساب تازه و در بازه مجاز است." if account_fresh else "تصویر حساب تازه نیست یا در آینده است.",
            None if account_age_seconds is None else round(account_age_seconds, 1),
            policy.max_account_age_seconds)
'@
if (-not $content.Contains($oldFresh)) { throw "account_snapshot_fresh anchor not found" }
$content = $content.Replace($oldFresh, $newFresh)

# 6.2 Spread نامشخص ⇒ Fail (به‌جای Pass)
$oldSpread = @'
        spread_pips: Decimal | None = None
        if candle is not None and candle.spread is not None and instrument is not None:
            spread_pips = candle.spread / instrument.pip_size
        add("spread_within_limit", spread_pips is None or spread_pips <= policy.max_spread_pips,
            "اسپرد در محدوده مجاز است." if spread_pips is not None else "اسپرد در داده موجود نیست؛ بدون تخمین پذیرفته شد.",
            None if spread_pips is None else quantize(spread_pips, 2), policy.max_spread_pips)
'@
$newSpread = @'
        spread_pips: Decimal | None = None
        if candle is not None and candle.spread is not None and instrument is not None:
            spread_pips = candle.spread / instrument.pip_size
        # FIX-06-RISK-FAIL-CLOSED: نبود اسپرد ⇒ Fail (نه Pass)
        spread_ok = spread_pips is not None and spread_pips <= policy.max_spread_pips
        add("spread_within_limit", spread_ok,
            "اسپرد در محدوده مجاز است." if spread_ok else "اسپرد ناموجود یا خارج از سقف مجاز؛ ریسک تأیید نمی‌شود.",
            None if spread_pips is None else quantize(spread_pips, 2), policy.max_spread_pips)
'@
if (-not $content.Contains($oldSpread)) { throw "spread anchor not found" }
$content = $content.Replace($oldSpread, $newSpread)

# 6.3 مواجهه ارزی: اگر حساب نبود یا exposure None بود، Fail
$oldExp = @'
        exposure_ok = True
        exposures: dict[str, Decimal] = {}
        if account is not None and instrument is not None and sizing is not None and sizing.volume > ZERO:
            exposure_ok, exposures = exposure_tools.combined_currency_ok(
                positions, context.instruments, context.rates, instrument, sizing.volume, entry, side,
                account.equity * policy.max_currency_exposure,
            )
        add("currency_exposure_ok", exposure_ok, "مواجهه خالص ارزها در سقف مجاز است.",
            {key: str(quantize(value, 2)) for key, value in exposures.items()},
            None if account is None else account.equity * policy.max_currency_exposure)
'@
$newExp = @'
        # FIX-06-RISK-FAIL-CLOSED: عدم امکان محاسبه مواجهه ⇒ Fail
        exposures: dict[str, Decimal] = {}
        can_compute_exposure = (
            account is not None and instrument is not None
            and sizing is not None and sizing.volume > ZERO
        )
        if can_compute_exposure:
            exposure_ok, exposures = exposure_tools.combined_currency_ok(
                positions, context.instruments, context.rates, instrument, sizing.volume, entry, side,
                account.equity * policy.max_currency_exposure,
            )
        else:
            exposure_ok = False
        add("currency_exposure_ok", exposure_ok,
            "مواجهه خالص ارزها در سقف مجاز است." if exposure_ok else "محاسبه مواجهه ارزی ممکن یا در محدوده نیست.",
            {key: str(quantize(value, 2)) for key, value in exposures.items()},
            None if account is None else account.equity * policy.max_currency_exposure)
'@
if (-not $content.Contains($oldExp)) { throw "currency exposure anchor not found" }
$content = $content.Replace($oldExp, $newExp)

# 6.4 Entry deviation: اگر قیمت جاری از Entry Level دور باشد ⇒ Fail (کنترل جدید)
if ($content -notmatch 'entry_deviation_ok') {
    $anchor = @'
        add("validity_window_ok", now < scenario.expiry_at, "سناریو منقضی نشده است.",
            scenario.expiry_at.isoformat(), now.isoformat())
'@
    $patch = @'
        add("validity_window_ok", now < scenario.expiry_at, "سناریو منقضی نشده است.",
            scenario.expiry_at.isoformat(), now.isoformat())

        # FIX-06-RISK-FAIL-CLOSED: کنترل جدید — انحراف قیمت جاری از Entry
        entry_deviation_ok = False
        entry_deviation_atr = None
        if candle is not None and instrument is not None and entry > ZERO:
            deviation_pips = abs(candle.close - entry) / instrument.pip_size
            entry_deviation_atr = float(deviation_pips)
            # اجازه حداکثر ۲۵ پیپ انحراف (یا معادل ۰٫۵٪ قیمت)
            entry_deviation_ok = deviation_pips <= Decimal("25")
        add("entry_deviation_ok", entry_deviation_ok,
            "قیمت جاری نزدیک سطح ورود است." if entry_deviation_ok else "قیمت از سطح ورود سناریو فاصله زیادی دارد.",
            entry_deviation_atr, "25 pip")
'@
    if (-not $content.Contains($anchor)) { throw "validity anchor not found" }
    $content = $content.Replace($anchor, $patch)
}

# 6.5 نگاشت reason_code برای کنترل جدید
$oldMap = @'
    "validity_window_ok": RiskReasonCode.SCENARIO_EXPIRED,
}
'@
$newMap = @'
    "validity_window_ok": RiskReasonCode.SCENARIO_EXPIRED,
    "entry_deviation_ok": RiskReasonCode.PRICE_INVALID,
}
'@
if (-not $content.Contains($oldMap)) { throw "reason map anchor not found" }
$content = $content.Replace($oldMap, $newMap)

$content = $content + "`r`n# FIX-06-RISK-FAIL-CLOSED`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] risk/gate.py patched (fail-closed)" -ForegroundColor Green