"""Chat-Adapter (Telegram, Matrix): Text und Sprachnachrichten über die Text-Pipeline."""

from __future__ import annotations

from loguru import logger


async def start_adapters(services) -> list:
    """Aktivierte Adapter starten. Gibt Stopp-Funktionen zurück."""
    stops = []
    cfg = services.cfg.adapters
    if cfg.telegram.enabled:
        try:
            from jarvis.adapters.telegram import TelegramAdapter

            adapter = TelegramAdapter(services)
            await adapter.start()
            stops.append(adapter.stop)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Telegram-Adapter nicht gestartet: {e}")
    if cfg.matrix.enabled:
        try:
            from jarvis.adapters.matrix import MatrixAdapter

            adapter = MatrixAdapter(services)
            await adapter.start()
            stops.append(adapter.stop)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Matrix-Adapter nicht gestartet: {e}")
    return stops


def alarm_text(event: dict) -> str | None:
    """Ereignisse, die ein Chat-Adapter als Nachricht weitergibt."""
    if event.get("type") == "alarm":
        icon = {"timer": "⏲️", "alarm": "⏰", "reminder": "🔔"}.get(event.get("kind"), "🔔")
        return f"{icon} {event.get('text') or event.get('label')}"
    return None
