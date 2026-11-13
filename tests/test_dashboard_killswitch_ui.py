"""آزمون رگرسیون UI: Kill Switch باید هم فعال و هم غیرفعال شود.

باگ قبلی: کارت «عملیات» فقط دکمهٔ فعال‌سازی داشت و کلیک دوباره کاربر هم دوباره
فعال می‌کرد؛ نتیجه اینکه معاملات قفل می‌ماند و از داشبورد راه بازگشتی نبود.
"""

from __future__ import annotations

import re
import unittest

from fxars.ui.dashboard import DASHBOARD_HTML


class KillSwitchUiTests(unittest.TestCase):
    def test_ops_card_exposes_both_directions(self) -> None:
        self.assertIn('onclick="toggleKill(true)"', DASHBOARD_HTML)
        self.assertIn('onclick="toggleKill(false)"', DASHBOARD_HTML)

    def test_toggle_sends_requested_state_not_hardcoded(self) -> None:
        body = re.search(r"async function toggleKill\(active\) \{(.*?)\n\}", DASHBOARD_HTML, re.S)
        self.assertIsNotNone(body)
        code = body.group(1)
        self.assertIn("JSON.stringify({ active, reason })", code)
        self.assertIn("confirm(", code)

    def test_status_is_rendered_from_server_state(self) -> None:
        self.assertIn("async function refreshKillState()", DASHBOARD_HTML)
        self.assertIn('id="killStateText"', DASHBOARD_HTML)
        self.assertIn('id="tradingKill"', DASHBOARD_HTML)
        self.assertIn("await refreshKillState();", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
