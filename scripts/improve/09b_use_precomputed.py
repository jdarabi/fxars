import sys
from pathlib import Path

p = Path("C:/FX/fxars/research/backtest.py")
text = p.read_text(encoding="utf-8")

if "FIX-09-USE-PRECOMPUTED" in text:
    print("[SKIP] already patched")
else:
    # پیدا کردن بلوک _plan_from_scenario
    old = '''        try:
            from fxars.analysis.engine import AnalysisOutcome
            from fxars.analysis.context import IndicatorSet
            window = candles[max(0, index - 600): index + 1]
            indicators = IndicatorSet.build(window, self.analysis)
            # ساخت StructureResult حداقلی برای builder
            from fxars.analysis.structure import StructureResult, Swing
            structure = StructureResult()
            if window:
                highs = max(window[-20:], key=lambda c: c.high)
                lows = min(window[-20:], key=lambda c: c.low)
                structure.last_swing_high = Swing(index=0, price=highs.high, kind="HIGH", confirmed_index=0)
                structure.last_swing_low = Swing(index=0, price=lows.low, kind="LOW", confirmed_index=0)'''

    new = '''        try:
            from fxars.analysis.engine import AnalysisOutcome
            from fxars.analysis.context import IndicatorSet
            from fxars.analysis.structure import StructureResult, Swing
            # FIX-09-USE-PRECOMPUTED: IndicatorSet از cache یا ساخت مجدد
            if self._precomputed_indicators is not None:
                # ساخت یک IndicatorSet با آرایه‌های برش‌خورده تا index
                from fxars.analysis.context import IndicatorSet as _IS
                pre = self._precomputed_indicators
                indicators = _IS(
                    ema_fast=tuple(pre.ema_fast[:index + 1]),
                    ema_slow=tuple(pre.ema_slow[:index + 1]),
                    ema_trend=tuple(pre.ema_trend[:index + 1]),
                    rsi=tuple(pre.rsi[:index + 1]),
                    roc=tuple(pre.roc[:index + 1]),
                    atr=tuple(pre.atr[:index + 1]),
                    atr_percentile=tuple(pre.atr_percentile[:index + 1]),
                    real_vol_short=tuple(pre.real_vol_short[:index + 1]),
                    real_vol_long=tuple(pre.real_vol_long[:index + 1]),
                )
                window = candles[max(0, index - 600): index + 1]
            else:
                window = candles[max(0, index - 600): index + 1]
                indicators = IndicatorSet.build(window, self.analysis)
            # FIX-09-PARITY: Structure واقعی از Swingهای پنجره، نه max/min 20 کندل
            structure = StructureResult()
            if window:
                # swingهای معتبر با تأیید در پنجره فعلی
                from fxars.analysis.structure import find_swings
                swings = find_swings(window, self.analysis.swing_k)
                # فقط swingهایی که confirmed_index + swing_k <= len(window) - 1
                # find_swings خودش این را بررسی می‌کند
                if swings:
                    highs = [s for s in swings if s.kind == "HIGH"]
                    lows = [s for s in swings if s.kind == "LOW"]
                    structure.last_swing_high = highs[-1] if highs else None
                    structure.last_swing_low = lows[-1] if lows else None'''

    if old not in text:
        print("[FAIL] _plan_from_scenario try block not found")
        # چاپ context
        for i, line in enumerate(text.splitlines(), 1):
            if "max(window[-20:], key=lambda c: c.high)" in line:
                for j in range(max(0, i-5), min(len(text.splitlines()), i+5)):
                    print(f"  {j+1}: {text.splitlines()[j]}")
                break
        sys.exit(1)
    text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")
    print("[PATCH 09b] use precomputed + real swings")
