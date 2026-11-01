# معیارهای پذیرش MVP-1 و نگاشت آزمون‌ها

اجرا:

```powershell
python -m unittest tests.test_acceptance -v
python -m fxars ac
```

| شناسه | معیار | آزمون | مدرک |
|---|---|---|---|
| AC-01 | کندل INVALID وارد AnalysisRun نشود | `test_ac01_invalid_candle_never_enters_analysis` | قرنطینه + بررسی مخزن |
| AC-02 | تحلیل با snapshot/config/code یکسان بازتولید شود | `test_ac02_analysis_reproducible` | برابری `run_id` و `result_hash` |
| AC-03 | هر سناریو Trigger/Invalidation/Expiry داشته باشد | `test_ac03_scenario_has_trigger_invalidation_expiry` | قرارداد Scenario |
| AC-04 | هر تصمیم Evidence و correlation_id داشته باشد | `test_ac04_decision_has_correlation_and_evidence` | Evidenceهای ذخیره‌شده |
| AC-05 | هیچ OrderIntent در MVP-1 ارسال‌شدنی نباشد | `test_ac05_no_order_path_in_mvp1` | `PHASE_VIOLATION` + نبود مسیر API |
| AC-06 | Risk Gate بدون مشخصات نماد/حساب/داده تازه رد کند | `test_ac06_risk_gate_rejects_missing_account` | `checks_failed` |
| AC-07 | گزارش بک‌تست هزینه‌ها را تفکیک کند | `test_ac07_backtest_costs_are_separated` | `costs.spread/commission/swap/slippage` |
| AC-08 | OOS از Train/Validation مستقل باشد | `test_ac08_oos_segments_independent` | `split_segments` + Embargo |
| AC-09 | احتمال بدون کالیبراسیون نمایش داده نشود | `test_ac09_no_probability_without_calibration` | نبود `probability` |
| AC-10 | Audit قابل حذف/ویرایش عادی نباشد | `test_ac10_audit_append_only` | Trigger + `verify` |
| AC-11 | خطای منبع/کهنگی ⇒ NO TRADE | `test_ac11_stale_data_yields_no_trade` | `DATA_STALE` |
| AC-12 | مستندات نصب/پیکربندی/پشتیبان‌گیری تحویل شود | `test_ac12_operational_docs_exist` | README + docs/OPERATIONS |

## پوشش تکمیلی

| حوزه | فایل آزمون |
|---|---|
| Core (زمان/Decimal/هش/خطا) | `tests/test_core.py` |
| دامنه | `tests/test_domain.py` |
| داده و کیفیت | `tests/test_data.py` |
| تحلیل و ضد Look-ahead | `tests/test_analysis.py` |
| تصمیم/سناریو/Trigger | `tests/test_decision.py` |
| ریسک و Kill Switch | `tests/test_risk.py` |
| ممیزی و Outbox | `tests/test_audit.py` |
| هویت و RBAC | `tests/test_identity.py` |
| پژوهش و بک‌تست | `tests/test_research.py` |
| اجرا (فاز) | `tests/test_execution.py` |
| API | `tests/test_api.py` |

## معیارهای عبور فازهای بعد (خلاصه)

- **MVP-2:** Forward test، تطبیق کامل سفارش، partial fill، قطع اتصال و idempotency.
- **MVP-3:** OOS/Forward تصویب‌شده، سیاست ریسک امضاشده، آزمون Kill Switch و امنیت، اجرای محدود با سقف سخت.
- **MVP-4:** حقوق داده، جداسازی Tenant، امنیت، پشتیبانی و انطباق حقوقی.
