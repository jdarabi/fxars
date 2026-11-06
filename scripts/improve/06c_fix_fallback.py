import sys
from pathlib import Path

p = Path('C:/FX/fxars/research/backtest.py')
text = p.read_text(encoding='utf-8')

if 'FIX-06-FALLBACK-TRANSPARENT' in text:
    print('[SKIP] fallback transparency already patched')
else:
    # پیدا کردن بلوک init (تفاوت calendar/None)
    candidates = [
        '''        if calendar is not None:
            self._scenario_builder = ScenarioBuilder(analysis, calendar)
            self._trigger_evaluator = TriggerEvaluator(analysis, calendar)
        else:
            self._scenario_builder = ScenarioBuilder(analysis)
            self._trigger_evaluator = TriggerEvaluator(analysis)''',
    ]
    anchor = None
    for c in candidates:
        if c in text:
            anchor = c
            break
    if anchor is None:
        # چاپ context
        print('[FAIL] init anchor not found; showing lines with ScenarioBuilder init:')
        for line in text.splitlines():
            if 'ScenarioBuilder(' in line or 'TriggerEvaluator(' in line:
                print('  ', line)
        sys.exit(1)

    new_anchor = anchor + '''
        # FIX-06-FALLBACK-TRANSPARENT
        self._fallback_count = 0
        self._fallback_errors: dict[str, int] = {}'''
    text = text.replace(anchor, new_anchor)

    old_fb = '''        except Exception as exc:
            # Fail-safe: در صورت خطا، به baseline برمی‌گردیم
            fallback = self._plan(decision, candles, index)
            fallback["mode"] = "baseline_fallback"
            fallback["fallback_error"] = type(exc).__name__
            return fallback'''
    new_fb = '''        except Exception as exc:
            # FIX-06-FALLBACK-TRANSPARENT
            err_name = type(exc).__name__
            self._fallback_count += 1
            self._fallback_errors[err_name] = self._fallback_errors.get(err_name, 0) + 1
            fallback = self._plan(decision, candles, index)
            fallback["mode"] = "baseline_fallback"
            fallback["fallback_error"] = err_name
            return fallback'''
    if old_fb not in text:
        print('[FAIL] fallback anchor not found')
        sys.exit(1)
    text = text.replace(old_fb, new_fb)

    old_stats = '''        metrics = compute_metrics(
            trades, equity_curve,
            initial_equity=float(self.config.initial_equity),
            timeframe=self.timeframe,
        )
        stats["skipped_rate"] = round(stats["skipped"] / max(stats["decisions"], 1), 4)
        return BacktestOutput(trades=trades, equity_curve=equity_curve, metrics=metrics, stats=stats)'''
    new_stats = '''        # FIX-06-FALLBACK-TRANSPARENT
        stats["fallback_count"] = self._fallback_count
        stats["fallback_errors"] = dict(self._fallback_errors)
        metrics = compute_metrics(
            trades, equity_curve,
            initial_equity=float(self.config.initial_equity),
            timeframe=self.timeframe,
        )
        stats["skipped_rate"] = round(stats["skipped"] / max(stats["decisions"], 1), 4)
        return BacktestOutput(trades=trades, equity_curve=equity_curve, metrics=metrics, stats=stats)'''
    if old_stats not in text:
        print('[FAIL] stats anchor not found')
        sys.exit(1)
    text = text.replace(old_stats, new_stats)

    p.write_text(text, encoding='utf-8')
    print('[PATCH 06c] fallback transparent in stats')
print('[DONE 06c]')
