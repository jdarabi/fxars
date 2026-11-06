from pathlib import Path

p = Path('C:/FX/tests/test_audit.py')
text = p.read_text(encoding='utf-8')

old = '''    def test_pending_count_decreases(self) -> None:
        self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        before = self.outbox.pending_count
        self.outbox.publish_pending({})
        self.assertLess(self.outbox.pending_count, before)'''

new = '''    def test_pending_count_unchanged_without_handler(self) -> None:
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

if old not in text:
    print('[FAIL] old test not found')
    raise SystemExit(1)

text = text.replace(old, new)
p.write_text(text, encoding='utf-8')
print('[PATCH] tests/test_audit.py updated')
print('[DONE]')
