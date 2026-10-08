"""Geräteverwaltung: jedes Gerät bekommt ein eigenes, widerrufbares Token."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.db import Database

KINDS = {"cyd", "esp32", "pwa", "android", "android_auto", "desktop", "matrix", "telegram", "test"}
SATELLITES = {"cyd", "esp32"}
TICKET_TTL = 60.0


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Device:
    id: int
    name: str
    kind: str
    room: str
    settings: dict[str, Any] = field(default_factory=dict)
    fw: str = ""

    @property
    def satellite(self) -> bool:
        return self.kind in SATELLITES


def _row_to_device(r) -> Device:
    try:
        settings = json.loads(r["settings"] or "{}")
    except (TypeError, ValueError):
        settings = {}
    return Device(r["id"], r["name"], r["kind"], r["room"] or "", settings, r["fw"] or "")


class DeviceRegistry:
    def __init__(self, db: Database):
        self.db = db
        self._tickets: dict[str, tuple[int, float]] = {}

    def create(self, name: str, kind: str, room: str = "") -> tuple[Device, str]:
        if kind not in KINDS:
            raise ValueError(f"Unbekannter Gerätetyp: {kind}")
        name = name.strip()[:60] or kind
        token = secrets.token_urlsafe(24)
        cur = self.db.execute(
            "INSERT INTO devices (name, kind, room, token_hash, created) VALUES (?,?,?,?,?)",
            (name, kind, room.strip()[:60], _hash(token), time.time()),
        )
        self.db.audit("admin", "device_create", f"{name} ({kind})")
        return Device(cur.lastrowid, name, kind, room), token

    def get(self, device_id: int) -> Device | None:
        rows = self.db.query("SELECT * FROM devices WHERE id=?", (device_id,))
        return _row_to_device(rows[0]) if rows else None

    def verify(self, token: str | None) -> Device | None:
        if not token:
            return None
        rows = self.db.query("SELECT * FROM devices WHERE token_hash=? AND revoked=0", (_hash(token),))
        return _row_to_device(rows[0]) if rows else None

    def rotate(self, device_id: int) -> str:
        """Neues Token erzeugen (altes wird sofort ungültig)."""
        token = secrets.token_urlsafe(24)
        n = self.db.execute("UPDATE devices SET token_hash=?, revoked=0 WHERE id=?",
                            (_hash(token), device_id)).rowcount
        if not n:
            raise KeyError(device_id)
        self.db.audit("admin", "device_rotate", str(device_id))
        return token

    def update(self, device_id: int, name: str | None = None, room: str | None = None,
               settings: dict[str, Any] | None = None) -> Device:
        device = self.get(device_id)
        if device is None:
            raise KeyError(device_id)
        if name is not None:
            device.name = name.strip()[:60] or device.name
        if room is not None:
            device.room = room.strip()[:60]
        if settings is not None:
            device.settings = {**device.settings, **settings}
        self.db.execute("UPDATE devices SET name=?, room=?, settings=? WHERE id=?",
                        (device.name, device.room, json.dumps(device.settings), device_id))
        return device

    def touch(self, device_id: int, fw: str | None = None) -> None:
        if fw is None:
            self.db.execute("UPDATE devices SET last_seen=? WHERE id=?", (time.time(), device_id))
        else:
            self.db.execute("UPDATE devices SET last_seen=?, fw=? WHERE id=?", (time.time(), fw[:32], device_id))

    def revoke(self, device_id: int) -> None:
        self.db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device_id,))
        self.db.audit("admin", "device_revoke", str(device_id))

    def list(self) -> list[dict]:
        out = []
        for r in self.db.query("SELECT id, name, kind, room, created, revoked, last_seen, settings, fw "
                               "FROM devices ORDER BY revoked, id"):
            d = dict(r)
            try:
                d["settings"] = json.loads(d.get("settings") or "{}")
            except ValueError:
                d["settings"] = {}
            out.append(d)
        return out

    # ---- Einmal-Tickets für WebSockets (Browser können keine Header setzen) ----
    def issue_ticket(self, device: Device) -> str:
        now = time.time()
        self._tickets = {t: v for t, v in self._tickets.items() if v[1] > now}
        ticket = secrets.token_urlsafe(18)
        self._tickets[ticket] = (device.id, now + TICKET_TTL)
        return ticket

    def redeem_ticket(self, ticket: str | None) -> Device | None:
        if not ticket:
            return None
        for known in list(self._tickets):
            if hmac.compare_digest(known, ticket):
                device_id, expires = self._tickets.pop(known)
                if expires < time.time():
                    return None
                device = self.get(device_id)
                rows = self.db.query("SELECT revoked FROM devices WHERE id=?", (device_id,))
                return device if device and rows and not rows[0]["revoked"] else None
        return None

    # ---- Chat-Konten (Telegram/Matrix) → Gerät ----
    def for_adapter_user(self, adapter: str, user_id: str, display: str) -> Device:
        rows = self.db.query("SELECT device_id FROM adapter_users WHERE adapter=? AND user_id=?",
                             (adapter, user_id))
        if rows:
            device = self.get(rows[0]["device_id"])
            if device is not None:
                return device
        device, _ = self.create(f"{adapter.capitalize()} {display}"[:60], adapter)
        self.db.execute("INSERT OR REPLACE INTO adapter_users (adapter, user_id, device_id) VALUES (?,?,?)",
                        (adapter, user_id, device.id))
        return device
