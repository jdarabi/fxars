"""FIX-TELEGRAM-CONFIG: ذخیره‌سازی تنظیمات تلگرام در فایل JSON."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH = Path("data/telegram.json")


@dataclass
class TelegramSettings:
    token: str = ""
    chat_id: str = ""
    enabled: bool = False

    @classmethod
    def load(cls) -> TelegramSettings:
        if not CONFIG_PATH.exists():
            return cls()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return cls(
                token=str(data.get("token", "")),
                chat_id=str(data.get("chat_id", "")),
                enabled=bool(data.get("enabled", False)),
            )
        except Exception:
            return cls()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def masked(self) -> dict:
        token = self.token or ""
        masked_token = token[:8] + "..." + token[-4:] if len(token) > 12 else ("***" if token else "")
        return {
            "token_masked": masked_token,
            "chat_id": self.chat_id,
            "enabled": self.enabled,
            "configured": bool(self.token and self.chat_id),
        }
