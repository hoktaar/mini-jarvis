"""Wetter über Open-Meteo (kostenlos, ohne API-Key)."""

from __future__ import annotations

import httpx

from jarvis.config import LocationCfg
from jarvis.tools.registry import Tool, ToolContext, ToolResult

WMO = {0: "klar", 1: "überwiegend klar", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Nebel",
       51: "leichter Niesel", 53: "Niesel", 55: "starker Niesel", 61: "leichter Regen", 63: "Regen",
       65: "starker Regen", 71: "leichter Schnee", 73: "Schnee", 75: "starker Schnee",
       80: "Regenschauer", 81: "Regenschauer", 82: "heftige Schauer", 95: "Gewitter"}


def make_weather_tool(loc: LocationCfg) -> Tool:
    async def handler(args: dict, ctx: ToolContext) -> ToolResult:
        day = int(args.get("day_offset", 0))
        params = {
            "latitude": loc.latitude, "longitude": loc.longitude, "timezone": loc.timezone,
            "current": "temperature_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": max(2, day + 1),
        }
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            r.raise_for_status()
            data = r.json()
        d = data["daily"]
        desc = WMO.get(d["weather_code"][day], "wechselhaft")
        when = "Heute" if day == 0 else "Morgen" if day == 1 else f"In {day} Tagen"
        speech = (f"{when} {desc}, {round(d['temperature_2m_min'][day])} bis "
                  f"{round(d['temperature_2m_max'][day])} Grad, Regenrisiko "
                  f"{d['precipitation_probability_max'][day]} Prozent.")
        if day == 0:
            speech = f"Gerade {round(data['current']['temperature_2m'])} Grad. " + speech
        return ToolResult(True, speech, data)

    return Tool(
        "get_weather", "Wetter am konfigurierten Standort.",
        {"day_offset": {"type": "integer", "description": "0 = heute, 1 = morgen …"}},
        [], handler, risk="read",
    )
