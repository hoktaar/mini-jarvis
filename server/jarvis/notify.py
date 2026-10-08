"""Push-Benachrichtigungen über ntfy (selbst gehostet oder ntfy.sh)."""

from __future__ import annotations

import httpx
from loguru import logger

from jarvis.config import NtfyCfg

TITLES = {"timer": "Timer abgelaufen", "alarm": "Wecker", "reminder": "Erinnerung"}


class Notifier:
    def __init__(self, cfg: NtfyCfg, secrets: dict[str, str]):
        self.cfg = cfg
        self.token = secrets.get(cfg.token_secret, "")

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled and bool(self.cfg.topic)

    def wants(self, kind: str, device_online: bool) -> bool:
        if not self.enabled or kind not in self.cfg.kinds:
            return False
        return not (self.cfg.only_when_offline and device_online)

    async def send(self, title: str, message: str, tags: str = "alarm_clock", priority: int = 4) -> bool:
        if not self.enabled:
            return False
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Tags": tags,
                   "Priority": str(priority)}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.cfg.base_url.rstrip('/')}/{self.cfg.topic}"
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.post(url, content=message.encode("utf-8"), headers=headers)
                r.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ntfy-Benachrichtigung fehlgeschlagen: {e}")
            return False
