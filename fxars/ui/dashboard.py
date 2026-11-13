"""داشبورد تک‌صفحه‌ای فارسی (RTL) — FIX-06-DASHBOARD-FILE.

HTML در fxars/ui/dashboard.html نگهداری می‌شود و در زمان import خوانده می‌شود.
"""
from __future__ import annotations

from pathlib import Path

_DASHBOARD_HTML_PATH = Path(__file__).with_name("dashboard.html")
DASHBOARD_HTML = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
