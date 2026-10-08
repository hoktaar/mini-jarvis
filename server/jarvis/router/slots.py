"""Slot-Extraktion ohne LLM: Dauer, Zeitpunkt, Tag, Ort, Namen, freie Texte.

Alle Zeitfunktionen arbeiten mit zeitzonenbewussten Datumswerten (`now` aus der
konfigurierten Zeitzone), damit Wecker nicht von der Container-Zeitzone abhängen.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from difflib import get_close_matches

# ---------------------------------------------------------------------------
# Zahlen
# ---------------------------------------------------------------------------
_UNITS = {
    "null": 0, "ein": 1, "eins": 1, "eine": 1, "einen": 1, "einer": 1, "einem": 1, "ner": 1, "nen": 1,
    "zwei": 2, "zwo": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
    "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
}
_TENS = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
         "siebzig": 70, "achtzig": 80, "neunzig": 90}
_FRACTIONS = {"halb": 0.5, "halbe": 0.5, "halben": 0.5, "anderthalb": 1.5, "viertel": 0.25,
              "dreiviertel": 0.75}

# Für Abwärtskompatibilität (wird von Tests/anderen Modulen genutzt)
NUMBER_WORDS = {**_UNITS, **_TENS}


def word_to_number(word: str) -> float | None:
    """'fünfundzwanzig' → 25, 'zweieinhalb' → 2.5, '1,5' → 1.5."""
    w = word.lower().strip(".,!?")
    if re.fullmatch(r"\d+([.,]\d+)?", w):
        return float(w.replace(",", "."))
    if w in _UNITS:
        return float(_UNITS[w])
    if w in _TENS:
        return float(_TENS[w])
    if w in _FRACTIONS:
        return _FRACTIONS[w]
    if w == "hundert" or w == "einhundert":
        return 100.0
    if w.endswith("einhalb") and len(w) > 7:
        base = word_to_number(w[:-7]) if w[:-7] != "ein" else 1.0
        return base + 0.5 if base is not None else None
    m = re.fullmatch(r"([a-zäöüß]+?)und([a-zäöüß]+)", w)
    if m and m.group(2) in _TENS:
        unit = _UNITS.get(m.group(1))
        if unit is not None and 0 < unit < 10:
            return float(_TENS[m.group(2)] + unit)
    return None


# Kompatibler Helfer für ältere Aufrufer
def _num(token: str) -> float | None:
    return word_to_number(token)


# ---------------------------------------------------------------------------
# Dauer
# ---------------------------------------------------------------------------
UNITS = {
    "sekunde": 1, "sekunden": 1, "sek": 1, "s": 1,
    "minute": 60, "minuten": 60, "min": 60, "minütchen": 60,
    "stunde": 3600, "stunden": 3600, "std": 3600, "h": 3600,
    "tag": 86400, "tage": 86400, "tagen": 86400,
}
_COMPOUND_UNITS = {"viertelstunde": 900, "dreiviertelstunde": 2700, "halbestunde": 1800}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß0-9]+(?:[.,][0-9]+)?", text.lower())


def parse_duration(text: str, allow_days: bool = False) -> int | None:
    """'fünf Minuten', '1,5 Stunden', 'eine halbe Stunde', 'anderthalb Stunden',
    '2 Stunden 10 Minuten', 'fünfundzwanzig Minuten' → Sekunden."""
    toks = _tokens(text)
    total = 0.0
    found = False
    for i, tok in enumerate(toks):
        if tok in _COMPOUND_UNITS:
            factor = word_to_number(toks[i - 1]) if i else None
            total += _COMPOUND_UNITS[tok] * (factor if factor and factor >= 1 else 1)
            found = True
            continue
        if tok not in UNITS or (not allow_days and UNITS[tok] == 86400):
            continue
        if tok in ("s", "h") and not (i and re.fullmatch(r"\d+([.,]\d+)?", toks[i - 1])):
            continue
        value = None
        if i:
            prev = toks[i - 1]
            value = word_to_number(prev)
            # "zwei halbe Stunden" ist selten – "eine halbe Stunde" = 0,5
            if prev in ("halbe", "halben"):
                value = 0.5
            elif prev == "dreiviertel":
                value = 0.75
        if value is None:
            continue
        total += value * UNITS[tok]
        found = True
    return int(round(total)) if found and total > 0 else None


# ---------------------------------------------------------------------------
# Tag, Datum, Uhrzeit
# ---------------------------------------------------------------------------
WEEKDAYS = {"montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
            "samstag": 5, "sonnabend": 5, "sonntag": 6}
MONTHS = {"januar": 1, "jänner": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
          "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
# Tageszeit → (Standardstunde, PM-Verschiebung für 1–11 Uhr)
DAYPARTS = {
    "früh": (7, False), "morgens": (8, False), "morgen früh": (8, False), "vormittags": (10, False),
    "vormittag": (10, False), "mittags": (12, False), "mittag": (12, False),
    "nachmittags": (15, True), "nachmittag": (15, True), "abends": (19, True), "abend": (19, True),
    "nachts": (22, True), "nacht": (22, True),
}
_WD_RE = "|".join(WEEKDAYS)
_MONTH_RE = "|".join(MONTHS)
_NUMWORD = r"[a-zäöüß]+|\d{1,2}"
_MORGEN = re.compile(r"(?<!guten )\bmorgen\b")   # "morgen" = Tag, nicht "Guten Morgen"/"morgens"


def _daypart(t: str) -> str | None:
    if re.search(r"\bmorgen\s+früh\b", t):
        return "morgen früh"
    for word in ("nachmittags", "nachmittag", "vormittags", "vormittag", "abends", "abend", "nachts", "nacht",
                 "morgens", "mittags", "mittag", "früh"):
        if re.search(rf"\b{word}\b", t):
            return word
    return None


def parse_day_offset(text: str, now: datetime, max_days: int = 15) -> int | None:
    """'heute' → 0, 'morgen' → 1, 'übermorgen' → 2, 'am Samstag' → Tage bis Samstag."""
    t = text.lower()
    if re.search(r"\bübermorgen\b", t):
        return 2
    if _MORGEN.search(t):
        return 1
    if re.search(r"\bheute\b|\bjetzt\b|\bgerade\b", t):
        return 0
    m = re.search(rf"\b(nächsten?\s+|kommenden?\s+)?({_WD_RE})\b", t)
    if m:
        delta = (WEEKDAYS[m.group(2)] - now.weekday()) % 7
        if delta == 0 and m.group(1):
            delta = 7
        return delta
    if re.search(r"\bwochenende\b", t):
        return (5 - now.weekday()) % 7
    m = re.search(r"\bin\s+(" + _NUMWORD + r")\s+tag(?:en)?\b", t)
    if m:
        n = word_to_number(m.group(1))
        if n is not None and 0 <= n <= max_days:
            return int(n)
    return None


def _parse_date(t: str, now: datetime) -> tuple[datetime | None, bool]:
    """Datum (ohne Uhrzeit). Rückgabe: (Datum oder None, 'nächsten' erwähnt)."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\bübermorgen\b", t):
        return today + timedelta(days=2), False
    if _MORGEN.search(t):
        return today + timedelta(days=1), False
    if re.search(r"\bheute\b", t):
        return today, False
    m = re.search(r"\b(\d{1,2})\.\s*(\d{1,2})\.(\d{2,4})?", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            d = today.replace(year=year, month=month, day=day)
        except ValueError:
            return None, False
        if not m.group(3) and d < today:
            d = d.replace(year=d.year + 1)
        return d, False
    m = re.search(rf"\b(\d{{1,2}}|[a-zäöüß]+?)(?:\.|ten|sten)?\s+({_MONTH_RE})\b", t)
    if m:
        day = word_to_number(m.group(1))
        if day is not None and 1 <= day <= 31:
            try:
                d = today.replace(month=MONTHS[m.group(2)], day=int(day))
            except ValueError:
                return None, False
            if d < today:
                d = d.replace(year=d.year + 1)
            return d, False
    m = re.search(rf"\b(nächsten?\s+|kommenden?\s+)?({_WD_RE})\b", t)
    if m:
        delta = (WEEKDAYS[m.group(2)] - now.weekday()) % 7
        return today + timedelta(days=delta), bool(m.group(1))
    m = re.search(r"\bin\s+(" + _NUMWORD + r")\s+tag(?:en)?\b", t)
    if m:
        n = word_to_number(m.group(1))
        if n is not None:
            return today + timedelta(days=int(n)), False
    return None, False


def _hour_word(word: str) -> int | None:
    n = word_to_number(word)
    if n is None or n != int(n) or not 0 <= n <= 24:
        return None
    return int(n) % 24


def _parse_time(t: str) -> tuple[int, int] | None:
    """Uhrzeit (Stunde, Minute) aus dem Text – ohne Tageszeit-Korrektur."""
    # halb sieben → 6:30
    m = re.search(rf"\b(?:um\s+)?halb\s+({_NUMWORD})\b", t)
    if m and (h := _hour_word(m.group(1))) is not None:
        return (h - 1) % 24, 30
    # viertel nach acht / viertel vor acht / dreiviertel acht / zehn nach sieben / fünf vor acht
    m = re.search(rf"\b(viertel|{_NUMWORD})\s+(nach|vor)\s+(?:halb\s+)?({_NUMWORD})\b", t)
    if m:
        mins = 15 if m.group(1) == "viertel" else word_to_number(m.group(1))
        h = _hour_word(m.group(3))
        if mins is not None and h is not None and 0 < mins < 60:
            half = " halb " in f" {m.group(0)} "
            base_h, base_m = ((h - 1) % 24, 30) if half else (h, 0)
            total = base_h * 60 + base_m + (int(mins) if m.group(2) == "nach" else -int(mins))
            total %= 24 * 60
            return total // 60, total % 60
    m = re.search(rf"\bdreiviertel\s+({_NUMWORD})\b", t)
    if m and (h := _hour_word(m.group(1))) is not None:
        return (h - 1) % 24, 45
    # 6:30 / 6.30 / 6 uhr 30 / sechs uhr dreißig / um 18 uhr / um sieben
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b(?!\.)", t)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)), int(m.group(2))
    m = re.search(rf"\b({_NUMWORD})\s*uhr(?:\s+({_NUMWORD}))?\b", t)
    if m and (h := _hour_word(m.group(1))) is not None:
        minute = word_to_number(m.group(2)) if m.group(2) else 0
        if minute is None or not 0 <= minute < 60 or minute != int(minute):
            minute = 0
        return h, int(minute)
    m = re.search(rf"\bum\s+({_NUMWORD})\b", t)
    if m and (h := _hour_word(m.group(1))) is not None:
        return h, 0
    return None


def parse_datetime(text: str, now: datetime | None = None, prefer: str = "next") -> datetime | None:
    """Zeitpunkt aus 'morgen um sieben', 'um halb sieben', 'Montag um acht',
    'heute Abend', 'in zwanzig Minuten', 'am 12. Oktober um 9'.

    prefer='next': mehrdeutiges '7' = nächstes 7 Uhr (Wecker);
    prefer='soonest': 7 oder 19 Uhr, je nachdem was früher kommt (Erinnerungen).
    """
    now = now or datetime.now().astimezone()
    t = text.lower()

    # Relativ: "in 20 Minuten", "in zwei Stunden" (Tage behandelt das Datum)
    m = re.search(r"\bin\s+(.{1,40}?(?:sekunden?|minuten?|stunden?|viertelstunde|halben stunde))\b", t)
    if m and not re.search(r"\btag(?:en)?\b", m.group(1)):
        seconds = parse_duration(m.group(1))
        if seconds:
            return (now + timedelta(seconds=seconds)).replace(microsecond=0)

    date, _ = _parse_date(t, now)
    tm = _parse_time(t)
    dp = _daypart(t)

    if tm is None:
        if dp is None:
            return None
        if date is None and dp == "morgen früh":
            date = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        hour = DAYPARTS[dp][0]
        base = date or now.replace(hour=0, minute=0, second=0, microsecond=0)
        candidate = base.replace(hour=hour, minute=0)
        return candidate if candidate > now else None

    hour, minute = tm
    explicit_date = date is not None
    if dp is not None and DAYPARTS[dp][1] and 1 <= hour < 12:
        if not (dp in ("nachts", "nacht") and hour <= 4):
            hour += 12
    base = date or now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not explicit_date:
        if prefer == "soonest" and dp is None and 1 <= hour < 12:
            options = [candidate, candidate.replace(hour=hour + 12)]
            options = [c if c > now else c + timedelta(days=1) for c in options]
            return min(options)
        if candidate <= now:
            candidate += timedelta(days=1)
    elif candidate <= now:
        # Wochentag heute, Uhrzeit schon vorbei → nächste Woche
        if re.search(rf"\b({_WD_RE})\b", t):
            candidate += timedelta(days=7)
        else:
            return None
    return candidate


# ---------------------------------------------------------------------------
# Namen, Orte, Texte
# ---------------------------------------------------------------------------
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
        if len(w) < 4:
            continue
        close = get_close_matches(w, list(lowered), n=1, cutoff=0.8)
        if close:
            return lowered[close[0]]
    return None


_NOT_PLACES = {
    "ordnung", "grad", "celsius", "zukunft", "morgen", "heute", "übermorgen", "minuten", "stunden",
    "sekunden", "wochenende", "woche", "nacht", "abend", "früh", "uhr", "zeit", "moment", "deutsch",
    "urlaub", "ruhe", "bett", "küche", "wohnzimmer", "garten", "garage", "büro", "schlafzimmer",
    *WEEKDAYS,
}


def parse_place(text: str) -> str | None:
    """Ortsname nach 'in/für/bei' ('Wetter in Hamburg', 'in Frankfurt am Main')."""
    m = re.search(
        r"\b(?:in|für|bei|nach)\s+((?:[A-ZÄÖÜ][\wäöüß-]+)(?:\s+(?:am|an der|im|ob der|an)\s+[A-ZÄÖÜ][\wäöüß-]+)?)",
        text,
    )
    if not m:
        return None
    place = m.group(1).strip()
    if place.split()[0].lower() in _NOT_PLACES:
        return None
    return place


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


_TIME_EXPR = [
    r"\bin\s+\S+\s+(?:sekunden?|minuten?|stunden?|tagen?)\b",
    rf"\b(?:um\s+)?(?:halb|viertel|dreiviertel)\s+(?:nach\s+|vor\s+)?(?:{_NUMWORD})\b",
    rf"\b(?:{_NUMWORD})\s+(?:nach|vor)\s+(?:{_NUMWORD})\b",
    r"\b\d{1,2}[:.]\d{2}\b",
    rf"\b(?:um\s+)?(?:{_NUMWORD})\s*uhr(?:\s+\d{{1,2}})?\b",
    rf"\bum\s+(?:{_NUMWORD})\b",
    rf"\b(?:am\s+)?(?:nächsten?\s+|kommenden?\s+)?(?:{_WD_RE})\b",
    rf"\b(?:am\s+)?\d{{1,2}}\.?\s*(?:{_MONTH_RE}|\d{{1,2}}\.(?:\d{{2,4}})?)",
    r"\b(?:heute|morgen|übermorgen)\b",
    r"\b(?:früh|morgens|vormittags?|mittags?|nachmittags?|abends?|nachts?)\b",
]


def _strip(text: str, patterns: list[str]) -> str:
    out = text
    for p in patterns:
        out = re.sub(p, " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip(" ,.!?")


def extract_reminder_text(text: str) -> str | None:
    """'Erinnere mich morgen um zehn an den Zahnarzt' → 'Zahnarzt'."""
    m = re.search(r"\b(?:daran,?\s+dass|dass|an)\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        candidate = _strip(m.group(1), _TIME_EXPR)
    else:
        candidate = _strip(text, [
            r"\berinner(?:e|ung|st)?\b", r"\bmich\b", r"\bbitte\b", r"\bjarvis\b", r"\bkannst du\b",
            r"\bstell(?:e)?\b", r"\beine?n?\b(?=\s+erinnerung)", *_TIME_EXPR,
        ])
    candidate = re.sub(r"^(?:den|die|das|dem|der|meinen|meine|mein|meinem|ich)\s+", "", candidate,
                       flags=re.IGNORECASE)
    candidate = re.sub(r"\b(?:zu erinnern|erinnern)\b", "", candidate, flags=re.IGNORECASE).strip(" ,.!?")
    return candidate if len(candidate) >= 3 else None


_GENERIC_TIMER = {"ein", "einen", "den", "der", "stell", "stelle", "neuer", "neuen", "kurz", "kurzen", "mein",
                  "meinen", "zweiten", "einem"}


def extract_timer_label(text: str) -> str | None:
    """'Timer für die Eier' → 'Eier', 'Pizza-Timer' → 'Pizza'."""
    m = re.search(r"\bfür\s+(?:die|den|das|meine?n?)\s+([\wäöüß-]+)", text, flags=re.IGNORECASE)
    if m and m.group(1).lower() not in UNITS:
        return m.group(1).capitalize()
    m = re.search(r"\b([\wäöüß]{3,}?)-?timer\b", text, flags=re.IGNORECASE)
    if m and m.group(1).lower() not in _GENERIC_TIMER:
        return m.group(1).capitalize()
    return None


def extract_memory_text(text: str) -> str | None:
    """'Merk dir, dass ich Kaffee schwarz trinke' → 'ich Kaffee schwarz trinke'."""
    m = re.search(r"\b(?:merk(?:e)?\s+dir|speicher(?:e)?|notier(?:e)?)\s*,?\s+(?:bitte\s+)?(?:dass\s+)?(.+)$",
                  text, flags=re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip(" ,.!?")
    return value if len(value) >= 3 else None


def parse_volume(text: str) -> int | str | None:
    """'lauter' → '+', 'leiser' → '-', 'Lautstärke auf 40' → 40."""
    t = text.lower()
    m = re.search(r"(\d{1,3})\s*(?:prozent|%)?", t)
    if "lautstärke" in t and m:
        return max(0, min(100, int(m.group(1))))
    if re.search(r"\b(?:stumm|ton aus)\b", t):
        return 0
    if re.search(r"\bganz\s+laut\b|\bmaximal\b", t):
        return 100
    if re.search(r"\bganz\s+leise\b", t):
        return 15
    if "lauter" in t:
        return "+"
    if "leiser" in t:
        return "-"
    return None


def parse_toggle(text: str) -> bool | None:
    """An/Aus für Schalter wie den Privatmodus."""
    t = text.lower()
    if re.search(r"\b(?:aus|ausschalten|deaktivier\w*|beend\w*|abschalten|verlass\w*)\b", t):
        return False
    if re.search(r"\b(?:an|ein|einschalten|aktivier\w*|anschalten|start\w*)\b", t):
        return True
    return None
