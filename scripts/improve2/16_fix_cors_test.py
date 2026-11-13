"""گام ۱۶: اصلاح تست CORS."""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\project\FX")
TF = ROOT / "tests" / "test_security.py"

OLD = '''class CorsPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def test_options_returns_cors_headers(self):
        import urllib.request
        req = urllib.request.Request(
            self.fixture.base + "/api/v1/health",
            method="OPTIONS",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            self.assertIn("access-control-allow-origin", headers)
            self.assertIn("GET", headers["access-control-allow-methods"])
'''

NEW = '''class CorsPreflightTests(unittest.TestCase):
    """FIX-16-CORS-TEST: رفتار امن — ACAO فقط اگر cors_allow_origin تنظیم شده باشد."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def _options(self, url):
        import urllib.request
        req = urllib.request.Request(url, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers

    def test_options_no_acao_when_cors_empty(self):
        """پیش‌فرض: cors_allow_origin خالی → ACAO نباید ارسال شود (امن)."""
        status, headers = self._options(self.fixture.base + "/api/v1/health")
        self.assertEqual(status, 204)
        self.assertNotIn("access-control-allow-origin", headers,
                         "امنیت: ACAO نباید با cors_allow_origin خالی ارسال شود")
        self.assertIn("access-control-allow-headers", headers)
        self.assertIn("access-control-allow-methods", headers)
        self.assertIn("GET", headers["access-control-allow-methods"])

    def test_options_acao_when_cors_configured(self):
        """با cors_allow_origin معتبر → ACAO ارسال شود."""
        from fxars.api.server import ApiApp
        self.fixture.env.platform.settings = self.fixture.env.settings.__class__.from_dict({
            "phase": "READ_ONLY",
            "db_path": ":memory:",
            "environment": "dev",
            "api": {"cors_allow_origin": "https://example.com"},
        })
        self.fixture.server.app = ApiApp(self.fixture.env.platform)
        status, headers = self._options(self.fixture.base + "/api/v1/health")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "https://example.com")
'''

def main():
    print("===[ گام ۱۶: اصلاح تست CORS ]===")
    if not TF.exists():
        print(f"[FAIL] فایل پیدا نشد: {TF}")
        return 2
    t = TF.read_text(encoding="utf-8")
    if "FIX-16-CORS-TEST" in t:
        print("[SKIP] از قبل patch شده")
        return 0
    if OLD not in t:
        print("[FAIL] anchor قدیمی پیدا نشد")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / ".fix-backups" / "improve2" / f"cors-test-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TF, backup / "test_security.py")
    print(f"[OK] backup: {backup}")

    t = t.replace(OLD, NEW)
    t = t.rstrip() + "\n\n# FIX-16-CORS-TEST\n"
    TF.write_text(t, encoding="utf-8")
    print("[PATCH] test_security.py به‌روزرسانی شد")

    import py_compile
    try:
        py_compile.compile(str(TF), doraise=True)
    except py_compile.PyCompileError as e:
        print(f"[FAIL] syntax: {e}")
        shutil.copy2(backup / "test_security.py", TF)
        return 1
    print("[OK] syntax compiles")
    print("===[ DONE: گام ۱۶ ]===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
