from datetime import date
from pathlib import Path

p = Path('C:/FX/CHANGELOG.md')
text = p.read_text(encoding='utf-8')

today = date.today().isoformat()

entry = f"""## [v1.4.11] — {today}

### Fixed (P0 — Security & Data Correctness)
- **FIX-08 Rate Limit:** IP bucket before auth + user bucket after auth. Removed `_rate_key` prefix-based bypass.
- **FIX-03 Demo harden:** `FXARS_ENABLE_DEMO=1` required explicitly; production rejects weak/default `secret_key` (fail-fast).
- **FIX-04 SUSPECT/INVALID:** closed candle with `available_at < close_time` → INVALID (prevents look-ahead); only VALID enters analysis/backtest; `DataQualityRun.verdict=FAIL` → `NO TRADE/DATA_QUALITY_FAIL`.
- **FIX-09 Outbox:** handler-missing events are no longer lost (skip not publish); retry with attempts, last_error, dead_letter_at.
- **FIX-09 Idempotency:** atomic state machine (pending/completed/failed); replay returns stored response; parallel requests return 409; failed retries allowed with new body.

### Fixed (P1 — Research Validity)
- **FIX-06a Swap:** `bars × timeframe_minutes / 1440` (was `bars/24`, only correct for H1).
- **FIX-06b Gap Stop:** gap-aware exit at `open` when the bar opens beyond stop.
- **FIX-06c Fallback transparency:** `fallback_count` and `fallback_errors` in `stats`.

### Fixed (Discovered)
- `AnalysisService` did not receive `quality_runs` despite DQ gate requiring it (silent `AttributeError` → every analysis returned `NO_TRADE/DATA_QUALITY_FAIL`). Wired through `__init__` and `Platform`.
- `DataQualityRepository.list()` does not accept `timeframe` kwarg; DQ gate now calls `list(instrument_id=..., limit=10)` and filters in Python.
- `_with_idempotency` documented "inside domain transaction" but was not. Now atomic via state machine.
- Old tests (`test_pending_count_decreases`, `test_analysis_and_idempotent_replay`) aligned with new behavior (delta-based / handler-required).

### Changed (semantics)
- `no_trade_reason` priority: `NO_DATA` < `INSUFFICIENT_DATA` < `DATA_STALE` < `DATA_QUALITY_FAIL`.
- DQ gate only blocks on `verdict=FAIL`; access errors log + allow.
- Idempotency: `failed` allows retry with any body; `completed/pending` with different hash → 409.

---

"""

if '[v1.4.11]' not in text:
    # درج بالای فایل، بعد از هدر
    if '# Changelog — FX-ARS' in text:
        header_end = text.find('\n\n', text.find('# Changelog'))
        if header_end > 0:
            text = text[:header_end+2] + entry + text[header_end+2:]
        else:
            text = entry + text
    else:
        text = entry + text

p.write_text(text, encoding='utf-8')
print('[PATCH] CHANGELOG.md updated with v1.4.11')
