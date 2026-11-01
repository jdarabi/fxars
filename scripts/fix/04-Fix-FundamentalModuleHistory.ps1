#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\analysis\fundamental.py'
Write-Host "[FIX-04] Patching $file" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-04-FUNDAMENTAL-HISTORY') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

$old = @'
class FundamentalModule:
    module_id = "fundamental.event_surprise"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        instrument = context.instrument
        lookback = context.as_of - timedelta(hours=settings.fundamental_lookback_hours)
        evidences: list[Evidence] = []
        base = instrument.base_currency.upper()
        quote = instrument.quote_currency.upper()

        for event in context.economic_events:
            if event.actual is None or event.forecast is None:
                continue
            if event.available_at > context.as_of or event.event_time < lookback:
                continue
            ratio = event.surprise_ratio
            if ratio is None or abs(ratio) < settings.fundamental_surprise_floor:
                continue
            currency = event.currency.upper()
            if currency == base:
                sign = 1
            elif currency == quote:
                sign = -1
            else:
                continue
            direction = Direction.LONG if ratio * sign > 0 else Direction.SHORT
            weight = _IMPORTANCE_WEIGHT.get(event.importance, 0.5)
            strength = clamp(0.22 + 0.38 * min(1.0, abs(ratio) / 0.25) * weight, 0.15, 0.85)
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.FUNDAMENTAL,
                    direction=direction,
                    strength=strength,
                    confidence=clamp(strength * 0.8, 0, 1),
                    observed_at=event.available_at,
                    available_at=event.available_at,
                    explanation=(
                        f"{event.indicator} ({currency}): actual={format(event.actual, 'f')} در برابر "
                        f"forecast={format(event.forecast, 'f')}؛ غافلگیری {ratio * 100:+.1f}%."
                    ),
                    invalidation={"condition": "revision", "level": "event_revised"},
                    expiry=event.available_at + context.tf.delta * settings.evidence_horizon_bars,
                    source_refs=(f"event:{event.event_id}", f"event_time:{format_ts(event.event_time)}"),
                    params={"importance": event.importance.value, "surprise_floor": settings.fundamental_surprise_floor},
                )
            )
        return evidences
'@

$new = @'
class FundamentalModule:
    """FIX-04-FUNDAMENTAL-HISTORY: Evidence بنیادی برای کل بازه تاریخی.

    هر رویداد وقتی `available_at <= as_of` باشد Evidence مستقل تولید می‌کند.
    این رفتار در بک‌تست باعث می‌شود شواهد بنیادی در همه تصمیم‌های تاریخی دیده شوند،
    نه فقط ۲۴ ساعت آخر دیتاست. چون EvidenceFactory شناسه یکتا بر اساس observed_at
    می‌سازد، هیچ‌گاه دو Evidence هم‌شناسه نخواهیم داشت.
    """
    module_id = "fundamental.event_surprise"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        instrument = context.instrument
        # پنجره ثابت برای پردازش رویدادهای موجود؛ دیگر بر اساس as_of بسته نمی‌شود.
        lookback = context.candles[0].open_time - timedelta(hours=settings.fundamental_lookback_hours) \
            if context.candles else (context.as_of - timedelta(hours=settings.fundamental_lookback_hours))
        evidences: list[Evidence] = []
        base = instrument.base_currency.upper()
        quote = instrument.quote_currency.upper()

        for event in context.economic_events:
            if event.actual is None or event.forecast is None:
                continue
            # فقط رویدادهای در دسترس تا as_of (بدون نگاه به آینده)
            if event.available_at > context.as_of:
                continue
            if event.event_time < lookback:
                continue
            ratio = event.surprise_ratio
            if ratio is None or abs(ratio) < settings.fundamental_surprise_floor:
                continue
            currency = event.currency.upper()
            if currency == base:
                sign = 1
            elif currency == quote:
                sign = -1
            else:
                continue
            direction = Direction.LONG if ratio * sign > 0 else Direction.SHORT
            weight = _IMPORTANCE_WEIGHT.get(event.importance, 0.5)
            strength = clamp(0.22 + 0.38 * min(1.0, abs(ratio) / 0.25) * weight, 0.15, 0.85)
            expiry = event.available_at + context.tf.delta * settings.evidence_horizon_bars
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.FUNDAMENTAL,
                    direction=direction,
                    strength=strength,
                    confidence=clamp(strength * 0.8, 0, 1),
                    observed_at=event.available_at,
                    available_at=event.available_at,
                    explanation=(
                        f"{event.indicator} ({currency}): actual={format(event.actual, 'f')} در برابر "
                        f"forecast={format(event.forecast, 'f')}؛ غافلگیری {ratio * 100:+.1f}%."
                    ),
                    invalidation={"condition": "revision", "level": "event_revised"},
                    expiry=expiry,
                    source_refs=(f"event:{event.event_id}", f"event_time:{format_ts(event.event_time)}"),
                    params={"importance": event.importance.value, "surprise_floor": settings.fundamental_surprise_floor},
                )
            )
        return evidences
'@

if (-not $content.Contains($old)) {
    throw "FundamentalModule block not found — file may have changed. Aborting."
}
$content = $content.Replace($old, $new)
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] fundamental.py patched (historical evidence)" -ForegroundColor Green