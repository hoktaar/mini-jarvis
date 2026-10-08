"""Matrix-Bot (matrix-nio). Nur freigegebene Benutzer, unverschlüsselte Räume/Direktchats."""

from __future__ import annotations

import asyncio
import json

from loguru import logger

from jarvis.adapters import alarm_text
from jarvis.textpipe import chat


class MatrixAdapter:
    def __init__(self, services):
        self.services = services
        self.cfg = services.cfg.adapters.matrix
        self.password = services.secrets.get("matrix_password", "")
        self.client = None
        self._task: asyncio.Task | None = None
        self._rooms: dict[str, str] = {}        # Benutzer → letzter Raum
        self._sinks: set[int] = set()

    def allowed(self, sender: str) -> bool:
        return sender in self.cfg.allowed_users

    def session(self, sender: str, room_id: str):
        self._rooms[sender] = room_id
        device = self.services.devices.for_adapter_user("matrix", sender, sender.split(":")[0].lstrip("@"))
        session = self.services.session_for(device)
        if device.id not in self._sinks:
            async def sink(event, _sender=sender):
                text = alarm_text(event)
                if text and self.client is not None and _sender in self._rooms:
                    await self.send(self._rooms[_sender], text)
            session.sinks.append(sink)
            self._sinks.add(device.id)
        return session

    async def send(self, room_id: str, text: str) -> None:
        await self.client.room_send(room_id, "m.room.message", {"msgtype": "m.text", "body": text},
                                    ignore_unverified_devices=True)

    async def start(self) -> None:
        from nio import AsyncClient, InviteMemberEvent, LoginResponse, RoomMessageText

        self.client = AsyncClient(self.cfg.homeserver, self.cfg.user_id)
        stored = None
        token_file = getattr(self.services, "matrix_token_file", None)
        if token_file and token_file.exists():
            stored = json.loads(token_file.read_text())
        if stored:
            self.client.restore_login(self.cfg.user_id, stored["device_id"], stored["access_token"])
        else:
            resp = await self.client.login(self.password, device_name="Mini-Jarvis")
            if not isinstance(resp, LoginResponse):
                raise RuntimeError(f"Matrix-Anmeldung fehlgeschlagen: {resp}")
            if token_file:
                token_file.write_text(json.dumps({"device_id": resp.device_id, "access_token": resp.access_token}))
                token_file.chmod(0o600)
        await self.client.sync(timeout=5000, full_state=True)      # alte Nachrichten überspringen

        async def on_invite(room, event):
            if event.membership == "invite" and event.state_key == self.cfg.user_id and self.allowed(event.sender):
                await self.client.join(room.room_id)

        async def on_message(room, event):
            if event.sender == self.cfg.user_id or not self.allowed(event.sender):
                return
            session = self.session(event.sender, room.room_id)
            await self.client.room_typing(room.room_id, True)
            result = await chat(session, event.body, speak=False)
            await self.client.room_typing(room.room_id, False)
            reply = result.get("reply") or "Erledigt."
            if result.get("needs_confirmation"):
                reply += " (Antworte mit ja oder nein.)"
            await self.send(room.room_id, reply)

        self.client.add_event_callback(on_invite, InviteMemberEvent)
        self.client.add_event_callback(on_message, RoomMessageText)
        self._task = asyncio.create_task(self.client.sync_forever(timeout=30000))
        logger.info("Matrix-Adapter läuft")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        if self.client is not None:
            await self.client.close()
