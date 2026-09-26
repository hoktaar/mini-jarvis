"""Geräteverwaltung: jedes Gerät bekommt ein eigenes, widerrufbares Token."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from jarvis.db import Database

KINDS = {"cyd", "esp32", "pwa", "android", "android_auto", "desktop", "matrix", "telegram", "test"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Device:
    id: int
    name: str
    kind: str
    room: str


class DeviceRegistry:
    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str, kind: str, room: str = "") -> tuple[Device, str]:
        if kind not in KINDS:
            raise ValueError(f"Unbekannter Gerätetyp: {kind}")
        token = secrets.token_urlsafe(24)
        cur = self.db.execute(
            "INSERT INTO devices (name, kind, room, token_hash, created) VALUES (?,?,?,?,?)",
            (name, kind, room, _hash(token), time.time()),
        )
        self.db.audit("admin", "device_create", f"{name} ({kind})")
        return Device(cur.lastrowid, name, kind, room), token

    def verify(self, token: str | None) -> Device | None:
        if not token:
            return None
        rows = self.db.query(
            "SELECT id, name, kind, room FROM devices WHERE token_hash=? AND revoked=0",
            (_hash(token),),
        )
        if not rows:
            return None
        r = rows[0]
        return Device(r["id"], r["name"], r["kind"], r["room"])

    def revoke(self, device_id: int) -> None:
        self.db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device_id,))
        self.db.audit("admin", "device_revoke", str(device_id))

    def list(self) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query(
                "SELECT id, name, kind, room, created, revoked FROM devices ORDER BY id"
            )
        ]
