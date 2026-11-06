"""رژیم بازار: روند، مومنتوم، نوسان و حجم (Tick Volume با برچسب منبع)."""

from __future__ import annotations

from fxars.analysis.context import AnalysisContext
from fxars.analysis.evidence import EvidenceFactory
from fxars.core.numerics import clamp
from fxars.domain.enums import Direction, EvidenceFamily
from fxars.domain.models import Evidence

MODULE_VERSION = "1.0.0"


class TrendModule:
    module_id = "trend.ema_structure"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        evidences: list[Evidence] = []
        for index in range(settings.min_bars, context.n):
            fast = context.indicators.ema_fast[index]
            slow = context.indicators.ema_slow[index]
            trend = context.indicators.ema_trend[index]
            atr = context.indicators.atr[index]
            if fast is None or slow is None or trend is None or not atr:
                continue
            candle = context.candles[index]
            slope = fast - context.indicators.ema_fast[index - 5] if context.indicators.ema_fast[index - 5] is not None else 0.0
            separation = abs(fast - slow) / atr
            if fast > slow > trend and slope > 0:
                direction = Direction.LONG
                strength = clamp(0.30 + 0.45 * min(1.0, separation) + 0.10 * min(1.0, abs(slope) / atr), 0.2, 0.90)
                explanation = f"ساختار میانگین‌ها صعودی است (EMA{settings.ema_fast} > EMA{settings.ema_slow} > EMA{settings.ema_trend})."
            elif fast < slow < trend and slope < 0:
                direction = Direction.SHORT
                strength = clamp(0.30 + 0.45 * min(1.0, separation) + 0.10 * min(1.0, abs(slope) / atr), 0.2, 0.90)
                explanation = f"ساختار میانگین‌ها نزولی است (EMA{settings.ema_fast} < EMA{settings.ema_slow} < EMA{settings.ema_trend})."
            else:
                direction = Direction.NEUTRAL
                strength = 0.12
                explanation = "میانگین‌ها هم‌راستا نیستند؛ رژیم روند نامشخص است."
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.TREND,
                    direction=direction,
                    strength=strength,
                    confidence=clamp(strength * 0.9, 0, 1),
                    observed_at=candle.open_time,
                    available_at=candle.available_at,
                    explanation=explanation,
                    invalidation=({"condition": "close_below", "level": format(candle.close, "f")} if direction is Direction.LONG
                                  else {"condition": "close_above", "level": format(candle.close, "f")} if direction is Direction.SHORT else None),
                    expiry=context.expiry(index, bars=4),
                    source_refs=(context.bar_ref(index),),
                    params={"ema_fast": settings.ema_fast, "ema_slow": settings.ema_slow,
                            "ema_trend": settings.ema_trend, "atr_period": settings.atr_period},
                )
            )
        return evidences


class MomentumModule:
    module_id = "momentum.rsi_roc"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        evidences: list[Evidence] = []
        for index in range(settings.min_bars, context.n):
            rsi = context.indicators.rsi[index]
            roc = context.indicators.roc[index]
            atr = context.indicators.atr[index]
            if rsi is None or roc is None or not atr:
                continue
            candle = context.candles[index]
            atr_pct = atr / max(float(candle.close), 1e-9)
            roc_ratio = abs(roc) / max(atr_pct, 1e-9)
            if rsi >= settings.rsi_bull and roc > 0:
                direction = Direction.LONG
                strength = clamp(0.28 + 0.45 * min(1.0, (rsi - 50.0) / 25.0) + 0.15 * min(1.0, roc_ratio), 0.2, 0.90)
                explanation = f"مومنتوم صعودی: RSI={rsi:.1f} و ROC مثبت ({roc * 100:.2f}%)."
            elif rsi <= settings.rsi_bear and roc < 0:
                direction = Direction.SHORT
                strength = clamp(0.28 + 0.45 * min(1.0, (50.0 - rsi) / 25.0) + 0.15 * min(1.0, roc_ratio), 0.2, 0.90)
                explanation = f"مومنتوم نزولی: RSI={rsi:.1f} و ROC منفی ({roc * 100:.2f}%)."
            else:
                direction = Direction.NEUTRAL
                strength = 0.10
                explanation = f"مومنتوم خنثی: RSI={rsi:.1f} و ROC={roc * 100:.2f}%."
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.MOMENTUM,
                    direction=direction,
                    strength=strength,
                    confidence=clamp(strength * 0.85, 0, 1),
                    observed_at=candle.open_time,
                    available_at=candle.available_at,
                    explanation=explanation,
                    expiry=context.expiry(index, bars=3),
                    source_refs=(context.bar_ref(index),),
                    params={"rsi_period": settings.rsi_period, "roc_period": settings.roc_period,
                            "rsi_bull": settings.rsi_bull, "rsi_bear": settings.rsi_bear},
                )
            )
        return evidences


class VolatilityModule:
    module_id = "volatility.regime"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        evidences: list[Evidence] = []
        for index in range(settings.min_bars, context.n):
            atr = context.indicators.atr[index]
            percentile = context.indicators.atr_percentile[index]
            short_vol = context.indicators.real_vol_short[index]
            long_vol = context.indicators.real_vol_long[index]
            if atr is None or percentile is None:
                continue
            candle = context.candles[index]
            atr_pips = float(atr / float(context.instrument.pip_size))
            if percentile >= 80:
                label = "نوسان بالا"
                strength = clamp(0.35 + (percentile - 80) / 100 * 1.5, 0.3, 0.85)
            elif percentile <= 20:
                label = "نوسان پایین/فشرده"
                strength = clamp(0.30 + (20 - percentile) / 100 * 1.5, 0.25, 0.75)
            else:
                label = "نوسان متعادل"
                strength = 0.20
            ratio = (short_vol / long_vol) if short_vol and long_vol else None
            detail = f"؛ نسبت نوسان کوتاه/بلند={ratio:.2f}" if ratio else ""
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.VOLATILITY,
                    direction=Direction.NEUTRAL,
                    strength=strength,
                    confidence=clamp(strength, 0, 1),
                    observed_at=candle.open_time,
                    available_at=candle.available_at,
                    explanation=f"{label}: ATR={atr_pips:.1f} پیپ، صدک={percentile:.0f}{detail}.",
                    expiry=context.expiry(index, bars=4),
                    source_refs=(context.bar_ref(index),),
                    params={"atr_period": settings.atr_period, "window": settings.atr_percentile_window},
                )
            )
        return evidences


class VolumeModule:
    module_id = "volume.tick_activity"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        evidences: list[Evidence] = []
        window = settings.vol_window
        recent: list[float] = []
        total = 0.0
        total_sq = 0.0
        for index in range(context.n):
            candle = context.candles[index]
            value = candle.tick_volume
            if value is not None:
                numeric = float(value)
                recent.append(numeric)
                total += numeric
                total_sq += numeric * numeric
                if len(recent) > window:
                    removed = recent.pop(0)
                    total -= removed
                    total_sq -= removed * removed
            if index < settings.min_bars or candle.tick_volume is None or len(recent) < 10:
                continue
            n = len(recent)
            mean = total / n
            variance = max(0.0, (total_sq - total * total / n) / (n - 1)) if n > 1 else 0.0
            std = variance ** 0.5
            z = (float(candle.tick_volume) - mean) / std if std > 0 else 0.0
            body = float(abs(candle.close - candle.open) / context.instrument.pip_size)
            if z < 0.5 or body < 1.0:
                continue
            direction = Direction.LONG if candle.close > candle.open else Direction.SHORT
            strength = clamp(0.18 + 0.12 * min(z, 3.0), 0.15, 0.55)
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.VOLUME,
                    direction=direction,
                    strength=strength,
                    confidence=clamp(strength * 0.7, 0, 1),
                    observed_at=candle.open_time,
                    available_at=candle.available_at,
                    explanation=(
                        f"فعالیت تیک {z:.2f} انحراف معیار بالاتر از میانگین ۲۰ کندل؛ "
                        "Tick Volume شمارش همان منبع است و حجم کل بازار نیست."
                    ),
                    expiry=context.expiry(index, bars=2),
                    source_refs=(context.bar_ref(index),),
                    params={"window": window, "source_id": candle.source_id},
                )
            )
        return evidences
