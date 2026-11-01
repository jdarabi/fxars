"""بررسی صحت زنجیره ممیزی و نمایش وضعیت."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxars.platform import Platform


def main() -> int:
    platform = Platform()
    result = platform.audit_verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"killswitch: {platform.kill_switch_status()}")
    print(f"pending outbox: {platform.outbox.pending_count}")
    platform.close()
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
