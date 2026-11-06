import sys
from pathlib import Path

p = Path("C:/FX/fxars/cli/main.py")
text = p.read_text(encoding="utf-8")

if "FIX-08-OUTBOX-CLI" in text:
    print("[SKIP] cli/main.py already patched")
else:
    anchor_cmd = "def cmd_reconcile(args: argparse.Namespace) -> None:\n"
    if anchor_cmd not in text:
        print("[FAIL] cmd_reconcile anchor not found")
        sys.exit(1)

    new_cmds = '''def cmd_outbox(args: argparse.Namespace) -> None:
    """FIX-08-OUTBOX-CLI: مدیریت Outbox."""
    platform = _platform(args)
    try:
        repo = platform.outbox_repo
        if args.action == "pending":
            items = repo.pending(limit=args.limit)
            if not items:
                print("(هیچ رویداد pending وجود ندارد)")
            else:
                rows = [{
                    "event_id": item["event_id"],
                    "event_type": item["event_type"],
                    "occurred_at": item["occurred_at"],
                    "attempts": item.get("attempts", 0),
                } for item in items[:args.limit]]
                _print_table(rows, [
                    ("event_id", "شناسه"), ("event_type", "نوع"),
                    ("occurred_at", "زمان"), ("attempts", "تلاش"),
                ])
            print(f"\\nتعداد pending: {len(items)}")

        elif args.action == "dead-letters":
            items = repo.dead_letters(limit=args.limit)
            if not items:
                print("(هیچ رویداد dead-letter وجود ندارد)")
            else:
                rows = [{
                    "event_id": item["event_id"],
                    "event_type": item["event_type"],
                    "dead_letter_at": item["dead_letter_at"],
                    "attempts": item.get("attempts", 0),
                    "last_error": (item.get("last_error") or "")[:40],
                } for item in items[:args.limit]]
                _print_table(rows, [
                    ("event_id", "شناسه"), ("event_type", "نوع"),
                    ("dead_letter_at", "زمان"), ("attempts", "تلاش"),
                    ("last_error", "خطا"),
                ])
            print(f"\\nتعداد dead-letter: {len(items)}")

        elif args.action == "publish":
            stats = platform.outbox.publish_pending(
                platform.outbox_handlers, limit=args.limit,
            )
            print(json.dumps({
                "stats": stats,
                "consumer": platform.outbox_stats.snapshot(),
            }, ensure_ascii=False, indent=2))

        elif args.action == "retry-dead-letters":
            items = repo.dead_letters(limit=args.limit)
            count = 0
            with platform.db.transaction():
                for item in items:
                    platform.db.execute(
                        "UPDATE outbox SET dead_letter_at=NULL, attempts=0, last_error=NULL "
                        "WHERE event_id=?",
                        (item["event_id"],),
                    )
                    count += 1
            print(f"تعداد {count} رویداد از dead-letter به pending بازگشت.")
            if count:
                stats = platform.outbox.publish_pending(
                    platform.outbox_handlers, limit=count,
                )
                print(json.dumps(stats, ensure_ascii=False, indent=2))
    finally:
        platform.close()


def cmd_reconcile(args: argparse.Namespace) -> None:
'''
    text = text.replace(anchor_cmd, new_cmds)

    anchor_parser = '    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")\n'
    if anchor_parser not in text:
        print("[FAIL] ac parser anchor not found")
        sys.exit(1)

    new_parser = '''    outbox = sub.add_parser("outbox", parents=[common], help="مدیریت Outbox")
    outbox.add_argument("action", choices=["pending", "dead-letters", "publish", "retry-dead-letters"])
    outbox.add_argument("--limit", type=int, default=100)
    outbox.set_defaults(func=cmd_outbox)

    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")
'''
    text = text.replace(anchor_parser, new_parser)

    text = text.rstrip() + "\n\n# FIX-08-OUTBOX-CLI\n"
    p.write_text(text, encoding="utf-8")
    print("[PATCH] cli/main.py: outbox CLI added")
