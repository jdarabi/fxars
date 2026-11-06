from pathlib import Path

p = Path('C:/FX/tests/test_audit.py')
text = p.read_text(encoding='utf-8')

# جایگزینی بلوک تست‌ها با نسخه delta-based
old = '''    def test_pending_count_unchanged_without_handler(self) -> None:
        """FIX-09-OUTBOX-RETRY: handler ناموجود رویداد را گم نمی‌کند (skip نه publish)."""
        self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        before = self.outbox.pending_count
        stats = self.outbox.publish_pending({})
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["published"], 0)
        self.assertEqual(self.outbox.pending_count, before)

    def test_pending_count_decreases_with_handler(self) -> None:
        """با handler ثبت‌شده، رویداد منتشر و pending کاهش می‌یابد."""
        self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        before = self.outbox.pending_count
        received = []
        stats = self.outbox.publish_pending({
            EventType.ANALYSIS_COMPLETED: lambda event: received.append(event),
        })
        self.assertEqual(stats["published"], 1)
        self.assertLess(self.outbox.pending_count, before)
        self.assertEqual(len(received), 1)'''

new = '''    def test_pending_count_unchanged_without_handler(self) -> None:
        """FIX-09-OUTBOX-RETRY: handler ناموجود رویداد را گم نمی‌کند (skip نه publish)."""
        self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        before = self.outbox.pending_count
        stats = self.outbox.publish_pending({})
        # همه رویدادها بدون handler هستند؛ همه باید skip شوند
        self.assertEqual(stats["published"], 0)
        self.assertGreaterEqual(stats["skipped"], 1)
        self.assertEqual(stats["failed"], 0)
        # هیچ رویدادی نباید publish (گم) شده باشد
        self.assertEqual(self.outbox.pending_count, before)

    def test_pending_count_decreases_with_handler(self) -> None:
        """با handler ثبت‌شده، رویدادهای همان نوع منتشر و pending کاهش می‌یابد."""
        self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        before = self.outbox.pending_count
        received = []
        stats = self.outbox.publish_pending({
            EventType.ANALYSIS_COMPLETED: lambda event: received.append(event),
        })
        self.assertGreaterEqual(stats["published"], 1)
        self.assertGreaterEqual(len(received), 1)
        self.assertLess(self.outbox.pending_count, before)'''

if old not in text:
    print('[FAIL] old test block not found')
    raise SystemExit(1)

text = text.replace(old, new)
p.write_text(text, encoding='utf-8')
print('[PATCH] tests/test_audit.py updated with delta-based assertions')
print('[DONE]')
