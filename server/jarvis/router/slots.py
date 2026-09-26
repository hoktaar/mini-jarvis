"""Slot-Extraktion ohne LLM: Dauer, Zeitpunkt, Namen."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from difflib import get_close_matches

NUMBER_WORDS = {
    "ein": 1, "eine": 1, "einen": 1, "einer": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwölf": 12, "fünfzehn": 15, "zwanzig": 20, "dreißig": 30,
    "vierzig": 40, "fünfundvierzig": 45, "fünfzig": 50, "sechzig": 60, "neunzig": 90,
}
UNITS = {
    "sekunde": 1, "sekunden": 1, "sek": 1,
    "minute": 60, "minuten": 60, "min": 60,
    "stunde": 3600, "stunden": 3600, "std": 3600,
}
_DURATION_RE = re.compile(
    r"([\d.,]+|[a-zäöüß]+)\s+(sekunden|sekunde|sek|minuten|minute|min|stunden|stunde|std)\b"
)


def _num(token: str) -> float | None:
    token = token.lower().replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", token):
        return float(token)
    return NUMBER_WORDS.get(token)


def parse_duration(text: str) -> int | None:
    """'fünf Minuten', '1,5 Stunden', 'eine halbe Stunde', '2 Stunden 10 Minuten' → Sekunden."""
    t = text.lower()
    if "halbe stunde" in t:
        return 1800
    if "viertelstunde" in t:
        return 900
    total = 0.0
    found = False
    for num, unit in _DURATION_RE.findall(t):
        value = _num(num)
        if value is not None:
            total += value * UNITS[unit]
            found = True
    return int(total) if found and total > 0 else None


def parse_datetime(text: str, now: datetime | None = None) -> datetime | None:
    """Zeitpunkt aus 'morgen um sieben', 'um 6:30', 'heute um 18 Uhr'."""
    now = now or datetime.now()
    t = text.lower()
    m = re.search(r"um\s+(\d{1,2}|[a-zäöüß]+)(?:\s*(?:[:.]|uhr)\s*(\d{1,2}))?", t)
    if m:
        hour_val = _num(m.group(1))
        if hour_val is not None and 0 <= hour_val < 24:
            minute = int(m.group(2) or 0)
            base = now + timedelta(days=1) if "morgen" in t else now
            candidate = base.replace(hour=int(hour_val), minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate
    try:  # Fallback: dateparser für freiere Formulierungen
        from dateparser.search import search_dates

        hits = search_dates(
            text, languages=["de"], settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now}
        )
        if hits:
            return hits[-1][1]
    except Exception:  # noqa: BLE001 – dateparser optional
        pass
    return None


def match_name(text: str, candidates: list[str]) -> str | None:
    """Container-/Skriptnamen unscharf finden ('jelly fin' → 'jellyfin')."""
    # Whisper schreibt oft "Jellyfin-Container" – Bindestriche trennen, aber auch zusammen probieren.
    words = re.findall(r"[a-z0-9_]+", text.lower())
    hyphenated = re.findall(r"[a-z0-9_]+(?:-[a-z0-9_]+)+", text.lower())
    joined = words + hyphenated + ["".join(words[i : i + 2]) for i in range(len(words) - 1)]
    lowered = {c.lower(): c for c in candidates}
    for w in joined:
        if w in lowered:
            return lowered[w]
    for w in joined:
        close = get_close_matches(w, list(lowered), n=1, cutoff=0.8)
        if close:
            return lowered[close[0]]
    return None


ACTION_WORDS = [
    ("restart", ("neu starten", "neustarten", "neustart", "restart", "rebooten")),
    ("stop", ("stoppen", "stopp", "stop", "anhalten", "beenden", "herunterfahren", "ausschalten")),
    ("start", ("starten", "starte", "start", "hochfahren", "einschalten", "anmachen")),
]


def parse_action(text: str) -> str | None:
    """'starte X neu' → restart, 'stopp X' → stop, 'starte X' → start."""
    t = text.lower()
    if " neu" in t and ("start" in t or "boot" in t):
        return "restart"
    for action, words in ACTION_WORDS:
        if any(w in t for w in words):
            return action
    return None
