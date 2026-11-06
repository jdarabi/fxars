import sys
from pathlib import Path

p = Path("C:/FX/fxars/research/backtest.py")
text = p.read_text(encoding="utf-8")

if "FIX-09-PRECOMPUTE" in text:
    print("[SKIP] backtest.py already patched")
else:
    # 1) افزودن فیلدهای cache به __init__
    anchor_init = '''        # FIX-06-SWAP: مدت هر کندل به دقیقه، برای محاسبه دقیق Swap
        from fxars.domain.enums import Timeframe as _TF
        self._tf_minutes = _TF.parse(timeframe).minutes'''
    new_init = '''        # FIX-06-SWAP: مدت هر کندل به دقیقه، برای محاسبه دقیق Swap
        from fxars.domain.enums import Timeframe as _TF
        self._tf_minutes = _TF.parse(timeframe).minutes
        # FIX-09-PRECOMPUTE: کش Structure و Indicator
        self._precomputed_indicators = None
        self._precomputed_structure_per_bar = None'''
    if anchor_init not in text:
        print("[FAIL] __init__ swap anchor not found")
        sys.exit(1)
    text = text.replace(anchor_init, new_init)

    # 2) افزودن متد _precompute قبل از simulate
    anchor_sim = "    def simulate(\n"
    if anchor_sim not in text:
        print("[FAIL] simulate anchor not found")
        sys.exit(1)

    precompute_method = '''    def _precompute(self, candles: Sequence[Candle]) -> None:
        """FIX-09-PRECOMPUTE: محاسبه یک‌بار Structure و Indicator روی کل سری.

        نتیجه: در هر کندل، Structure فقط تا همان کندل دیده می‌شود (بدون look-ahead)
        اما محاسبه از قبل انجام شده و در simulate فقط «نگاه» می‌کنیم.
        """
        from fxars.analysis.context import IndicatorSet
        from fxars.analysis.structure import StructureModule
        from fxars.analysis.engine import AnalysisOutcome
        from fxars.analysis.structure import StructureResult

        # یک بار Indicator روی کل سری
        self._precomputed_indicators = IndicatorSet.build(list(candles), self.analysis)

        # برای Structure: در هر کندل i، ما یک پنجره [0..i] داریم.
        # ساده‌ترین راه: پنجره کامل را بگیریم، اما StructureModule خودش causal است
        # (swing فقط بعد از تأیید در i+k ثبت می‌شود). پس یک بار روی کل سری اجرا می‌کنیم
        # و در هر کندل، فیلتر می‌کنیم که فقط شواهد با available_at <= available_at[i] را ببینیم.
        from fxars.analysis.context import AnalysisContext
        from fxars.analysis.evidence import EvidenceFactory

        # ساده‌تر: در هر کندل، یک AnalysisContext سبک با کندل‌های [0..i] بسازیم
        # اما برای performance، فقط از StructureModule استفاده می‌کنیم، نه کل Engine.
        # راه‌حل: یک بار Structure روی کل سری، سپس در هر کندل فقط swingهای تأییدشده تا i.
        # این کار در simulate انجام می‌شود که هر بار یک پنجره کوچک می‌گیرد.
        # فعلاً فقط indicators را precompute می‌کنیم.
        self._precomputed_structure_per_bar = None  # فعلاً پیاده نشده

    def simulate(
'''
    text = text.replace(anchor_sim, precompute_method)

    # 3) فراخوانی _precompute در ابتدای simulate
    anchor_sim_body = '''        candles = list(candles)
        if end_index - start_index < 2:'''
    new_sim_body = '''        candles = list(candles)
        # FIX-09-PRECOMPUTE
        self._precompute(candles)
        if end_index - start_index < 2:'''
    if anchor_sim_body not in text:
        print("[FAIL] simulate body anchor not found")
        sys.exit(1)
    text = text.replace(anchor_sim_body, new_sim_body)

    p.write_text(text, encoding="utf-8")
    print("[PATCH 09a] precompute added")
