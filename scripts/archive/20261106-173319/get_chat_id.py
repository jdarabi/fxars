"""Get Telegram chat_id from bot updates. Run after sending a message to the bot."""
import os
import sys

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

token = os.environ.get("FXARS_TELEGRAM_TOKEN", "").strip()
if not token:
    print("ERROR: FXARS_TELEGRAM_TOKEN not set")
    print("Run: $env:FXARS_TELEGRAM_TOKEN = '...'")
    sys.exit(1)

print(f"Token: {token[:20]}... (len={len(token)})")
print()

# 1) webhook info
print("=== Webhook Info ===")
try:
    r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=30)
    wh = r.json()
    if wh.get("ok"):
        url = wh["result"].get("url", "")
        print(f"  url: {url or '(none)'}")
    else:
        print(f"  ERROR: {wh}")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(2)

# 2) getUpdates
print()
print("=== Updates ===")
try:
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"limit": 10, "timeout": 5},
        timeout=30,
    )
    data = r.json()
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(3)

if not data.get("ok"):
    print(f"ERROR: {data}")
    sys.exit(4)

updates = data.get("result", [])
if not updates:
    print("  No messages found.")
    print()
    print("  → Steps:")
    print("    1. Open Telegram")
    print("    2. Find your bot (search by its @username)")
    print("    3. Send any message (e.g. 'hello')")
    print("    4. Re-run this script")
    sys.exit(0)

print(f"  Found {len(updates)} update(s):")
print()
for update in updates:
    msg = update.get("message") or update.get("edited_message") or update.get("channel_post")
    if not msg:
        continue
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "?")
    name = chat.get("first_name") or chat.get("title") or chat.get("username") or "?"
    if chat_id is not None:
        print(f"  chat_id = {chat_id}")
        print(f"    type = {chat_type}")
        print(f"    name = {name}")
        print()

print("=" * 50)
print("Use the chat_id (number) in FXARS_TELEGRAM_CHAT_ID")
