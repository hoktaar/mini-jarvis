"""Wetter über Open-Meteo (kostenlos, ohne API-Key) – für heute bis +15 Tage und beliebige Orte."""

from __future__ import annotations

import httpx

from jarvis.config import LocationCfg
from jarvis.tools.registry import Tool, ToolContext, ToolResult

WMO = {0: "klar", 1: "überwiegend klar", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Nebel",
       51: "leichter Niesel", 53: "Niesel", 55: "starker Niesel", 56: "gefrierender Niesel", 57: "gefrierender Niesel",
       61: "leichter Regen", 63: "Regen", 65: "starker Regen", 66: "gefrierender Regen", 67: "gefrierender Regen",
       71: "leichter Schnee", 73: "Schnee", 75: "starker Schnee", 77: "Schneegriesel",
       80: "Regenschauer", 81: "Regenschauer", 82: "heftige Schauer", 85: "Schneeschauer", 86: "Schneeschauer",
       95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel"}
DAY_NAMES = {0: "Heute", 1: "Morgen", 2: "Übermorgen"}
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

_geo_cache: dict[str, tuple[float, float, str, str] | None] = {}


async def geocode(name: str, client: httpx.AsyncClient) -> tuple[float, float, str, str] | None:
    """Ort → (lat, lon, Name, Zeitzone) über die Open-Meteo-Geocoding-API (mit Cache)."""
    key = name.lower().strip()
    if key in _geo_cache:
        return _geo_cache[key]
    r = await client.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": name, "count": 1, "language": "de", "format": "json"})
    r.raise_for_status()
    hits = r.json().get("results") or []
    value = (hits[0]["latitude"], hits[0]["longitude"], hits[0]["name"], hits[0].get("timezone", "auto")) \
        if hits else None
    _geo_cache[key] = value
    return value


def describe(data: dict, day: int, place: str | None, home: bool) -> str:
    d = data["daily"]
    desc = WMO.get(d["weather_code"][day], "wechselhaft")
    if day in DAY_NAMES:
        when = DAY_NAMES[day]
    else:
        from datetime import date

        when = f"Am {WEEKDAYS[date.fromisoformat(d['time'][day]).weekday()]}"
    where = "" if home or not place else f" in {place}"
    rain = d["precipitation_probability_max"][day]
    speech = (f"{when}{where} {desc}, {round(d['temperature_2m_min'][day])} bis "
              f"{round(d['temperature_2m_max'][day])} Grad")
    speech += f", Regenrisiko {rain} Prozent." if rain is not None else "."
    if day == 0 and "current" in data:
        speech = f"Gerade {round(data['current']['temperature_2m'])} Grad. " + speech
    if rain is not None and rain >= 50:
        speech += " Nimm lieber einen Schirm mit."
    return speech


def make_weather_tool(loc: LocationCfg) -> Tool:
    async def handler(args: dict, ctx: ToolContext) -> ToolResult:
        try:
            day = max(0, min(15, int(args.get("day_offset") or 0)))
        except (TypeError, ValueError):
            day = 0
        place = (args.get("place") or "").strip() or None
        try:
            return await _fetch(day, place)
        except httpx.HTTPError:
            return ToolResult(False, "Der Wetterdienst ist gerade nicht erreichbar.")

    async def _fetch(day: int, place: str | None) -> ToolResult:
        async with httpx.AsyncClient(timeout=8) as client:
            lat, lon, tz, name = loc.latitude, loc.longitude, loc.timezone, loc.name
            if place:
                hit = await geocode(place, client)
                if hit is None:
                    return ToolResult(False, f"Ich kenne keinen Ort namens {place}.")
                lat, lon, name, tz = hit
            params = {
                "latitude": lat, "longitude": lon, "timezone": tz,
                "current": "temperature_2m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": max(2, day + 1),
            }
            r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            r.raise_for_status()
            data = r.json()
        return ToolResult(True, describe(data, day, name, home=place is None),
                          {"place": name, "day_offset": day, "daily": data.get("daily", {})})

    return Tool(
        "get_weather", "Wetter am eigenen Standort oder an einem genannten Ort, heute bis in 15 Tagen.",
        {"day_offset": {"type": "integer", "description": "0 = heute, 1 = morgen …"},
         "place": {"type": "string", "description": "Ortsname, leer = Zuhause"}},
        [], handler, risk="read",
    )
