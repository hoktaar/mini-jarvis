"""Langzeitgedächtnis: „Merk dir, dass …“ – Fakten landen im Systemprompt des LLM."""

from __future__ import annotations

import re
import time

from jarvis.db import Database
from jarvis.tools.registry import Tool, ToolContext, ToolResult

_SUBJECT_PRONOUNS = {"ich", "du", "er", "sie", "es", "wir", "ihr", "man"}
_DETERMINERS = {"mein", "meine", "meinen", "meinem", "meiner", "der", "die", "das", "unser", "unsere", "dein",
                "deine", "sein", "seine", "ihr", "ihre"}
_IRREGULAR = {"bin": "bist", "habe": "hast", "hab": "hast", "kann": "kannst", "mag": "magst", "muss": "musst",
              "will": "willst", "darf": "darfst", "soll": "sollst", "weiß": "weißt", "werde": "wirst",
              "heiße": "heißt", "sitze": "sitzt", "esse": "isst", "lese": "liest", "sehe": "siehst",
              "fahre": "fährst", "schlafe": "schläfst", "trage": "trägst", "laufe": "läufst", "gebe": "gibst",
              "nehme": "nimmst", "spreche": "sprichst", "treffe": "triffst", "helfe": "hilfst",
              "vergesse": "vergisst", "arbeite": "arbeitest", "finde": "findest"}
_SWAP = {"ich": "du", "mich": "dich", "mir": "dir", "mein": "dein", "meine": "deine", "meinen": "deinen",
         "meinem": "deinem", "meiner": "deiner", "meines": "deines", "wir": "ihr", "uns": "euch", "unser": "euer"}


def _verb_like(word: str) -> bool:
    w = word.lower()
    return word.islower() and (w in _IRREGULAR or w.endswith(("e", "t", "en")))


def normalize_fact(text: str) -> str:
    """'ich Kaffee schwarz trinke' (Nebensatz nach „dass“) → 'ich trinke Kaffee schwarz'."""
    words = text.split()
    if len(words) < 3:
        return text
    subject = 2 if words[0].lower() in _DETERMINERS else 1
    if words[0].lower() not in _SUBJECT_PRONOUNS and subject == 1 and not words[0][:1].isupper():
        return text
    if len(words) > subject + 1 and _verb_like(words[-1]) and not _verb_like(words[subject]):
        words = words[:subject] + [words[-1]] + words[subject:-1]
    return " ".join(words)


def to_second_person(text: str) -> str:
    """'ich trinke Kaffee' → 'du trinkst Kaffee' (für die gesprochene Antwort)."""
    words = text.split()
    out = []
    for i, w in enumerate(words):
        low = w.lower()
        if low in _SWAP:
            out.append(_SWAP[low])
        elif i > 0 and words[i - 1].lower() == "ich" and w.islower():
            out.append(_IRREGULAR.get(low) or (low[:-1] + "st" if low.endswith("e") else low + "st"))
        else:
            out.append(w)
    return " ".join(out)


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    def add(self, text: str, device_id: int | None = None) -> int:
        text = normalize_fact(re.sub(r"\s+", " ", text).strip(" .!?"))[:300]
        existing = self.db.query("SELECT id FROM memories WHERE lower(text)=lower(?)", (text,))
        if existing:
            return existing[0]["id"]
        return self.db.execute("INSERT INTO memories (device_id, text, created) VALUES (?,?,?)",
                               (device_id, text, time.time())).lastrowid

    def list(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,))]

    def delete(self, memory_id: int) -> bool:
        return bool(self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,)).rowcount)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        words = [w for w in re.findall(r"[a-zäöüß0-9]{3,}", query.lower())]
        if not words:
            return self.list(limit)
        scored = []
        for m in self.list(500):
            score = sum(1 for w in words if w in m["text"].lower())
            if score:
                scored.append((score, m))
        return [m for _, m in sorted(scored, key=lambda x: (-x[0], -x[1]["id"]))[:limit]]

    def forget(self, query: str) -> int:
        hits = self.search(query, 1)
        return sum(self.delete(h["id"]) for h in hits)

    def prompt_lines(self, limit: int = 20) -> list[str]:
        return [m["text"] for m in reversed(self.list(limit))]


def make_memory_tools(store: MemoryStore) -> list[Tool]:
    async def remember(args: dict, ctx: ToolContext) -> ToolResult:
        text = str(args.get("memory") or args.get("text") or "").strip()
        if len(text) < 3:
            return ToolResult(False, "Was soll ich mir merken?")
        store.add(text, ctx.device_id)
        return ToolResult(True, "Okay, habe ich mir gemerkt.")

    async def recall(args: dict, ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        items = store.search(query) if query else store.list(5)
        if not items:
            return ToolResult(True, "Dazu habe ich mir nichts gemerkt." if query else "Ich habe mir noch nichts gemerkt.")
        facts = [to_second_person(m["text"]) for m in items]
        return ToolResult(True, "Ich weiß: " + "; ".join(facts) + ".", {"items": [m["text"] for m in items]})

    async def forget(args: dict, ctx: ToolContext) -> ToolResult:
        n = store.forget(str(args.get("query") or ""))
        return ToolResult(bool(n), "Vergessen." if n else "Dazu habe ich nichts gespeichert.")

    return [
        Tool("remember", "Eine Information dauerhaft merken.",
             {"memory": {"type": "string", "description": "Was gemerkt werden soll, als kurzer Satz"}},
             ["memory"], remember, risk="write"),
        Tool("recall", "Gemerkte Informationen abrufen (optional mit Suchbegriff).",
             {"query": {"type": "string"}}, [], recall, risk="read"),
        Tool("forget", "Eine gemerkte Information löschen.",
             {"query": {"type": "string"}}, ["query"], forget, risk="write"),
    ]
