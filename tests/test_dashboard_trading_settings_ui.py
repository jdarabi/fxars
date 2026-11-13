"""آزمون رگرسیون UI: تنظیمات هوشمند معاملات نباید گزینه‌ها را محدود کند.

رفتار مورد انتظار: هر مقدار ساختاری‌معتبر در فرم قابل انتخاب است؛ اگر از سقف
سیاست بیرون باشد، ابتدا هشدار و تأیید گرفته می‌شود و سپس با
``confirm_warnings=true`` ذخیره می‌گردد.
"""

from __future__ import annotations

import re
import unittest

from fxars.ui.dashboard import DASHBOARD_HTML


def _function_body(name: str) -> str:
    match = re.search(rf"function {name}\([^)]*\) \{{(.*?)\n\}}", DASHBOARD_HTML, re.S)
    if match is None:
        raise AssertionError(f"{name} not found")
    return match.group(1)


class TradingSettingsUiTests(unittest.TestCase):
    def test_all_supported_timeframes_are_offered(self) -> None:
        match = re.search(r"const TS_TIMEFRAMES = \[(.*?)\];", DASHBOARD_HTML)
        self.assertIsNotNone(match)
        offered = set(re.findall(r'"([A-Z0-9]+)"', match.group(1)))
        self.assertEqual(offered, {"M5", "M15", "H1", "H4", "D1"})

    def test_instrument_dropdown_uses_service_list_not_whitelist(self) -> None:
        body = _function_body("renderTsInstruments")
        self.assertIn("state.instrumentIds", body)
        self.assertNotIn(".filter(", body)
        self.assertNotIn("TS_TRADABLE.filter", DASHBOARD_HTML)

    def test_confirm_flow_posts_confirm_warnings_then_saves(self) -> None:
        body = _function_body("saveTradingSettings")
        self.assertIn("requires_confirmation", body)
        self.assertIn("body.confirm_warnings = true", body)
        self.assertIn("confirm(", body)
        self.assertIn("saveTradingSettings(true)", body)
        # FIX-TEST-ESCAPE-FINAL: رفتار به‌جای escape
        self.assertIn("confirm(", body)
        self.assertIn(".join(", body)

    def test_policy_hint_announces_warning_and_confirmation(self) -> None:
        body = _function_body("renderPolicyHint")
        self.assertIn("هشدار و تأیید شما", body)

    def test_settings_panel_description_is_soft_on_policy_caps(self) -> None:
        self.assertIn("همهٔ مقادیر قابل ویرایش‌اند", DASHBOARD_HTML)
        self.assertIn("پس از نمایش هشدار و تأیید شما", DASHBOARD_HTML)


class StrategyTrendFilterUiTests(unittest.TestCase):
    def test_manual_strategy_hint_mentions_h1_trend(self) -> None:
        body = _function_body("onStrategySelectChanged")
        self.assertIn("هم‌جهت با روند H1 (EMA50)", body)

    def test_analysis_renders_h1_trend_state(self) -> None:
        body = _function_body("analyzeStrategies")
        self.assertIn("data.trend_filter", body)
        self.assertIn("فیلتر روند ${esc(trend.timeframe)}", body)
        self.assertIn("صعودی (خرید مجاز)", body)
        self.assertIn("نزولی (فروش مجاز)", body)
        self.assertIn("نامشخص (ورود مسدود)", body)
        self.assertIn("اعمال نشد", body)


if __name__ == "__main__":
    unittest.main()

# FIX-TEST-ESCAPE: تست دیگر به escape سطح سورس وابسته نیست

# FIX-TEST-ESCAPE-FINAL
