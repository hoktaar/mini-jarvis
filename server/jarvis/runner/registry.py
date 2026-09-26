"""Skript-Registry und Parameterprüfung (ohne Seiteneffekte, gut testbar)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    pass


@dataclass
class ParamSpec:
    type: str = "str"                  # str | int | bool | enum
    required: bool = False
    pattern: str | None = None
    min: int | None = None
    max: int | None = None
    choices: list[str] = field(default_factory=list)


@dataclass
class ScriptSpec:
    id: str
    path: str
    description: str = ""
    confirm: bool = True
    car_allowed: bool = False
    timeout: int = 60
    params: dict[str, ParamSpec] = field(default_factory=dict)


def load_registry(data: dict, scripts_root: str = "/scripts") -> dict[str, ScriptSpec]:
    registry: dict[str, ScriptSpec] = {}
    root = Path(scripts_root).resolve()
    for sid, spec in (data.get("scripts") or {}).items():
        path = Path(spec["path"]).resolve()
        if root not in path.parents and path != root:
            raise ValidationError(f"Skript {sid} liegt außerhalb von {root}")
        params = {name: ParamSpec(**p) for name, p in (spec.get("params") or {}).items()}
        registry[sid] = ScriptSpec(
            id=sid, path=str(path), description=spec.get("description", ""),
            confirm=spec.get("confirm", True), car_allowed=spec.get("car_allowed", False),
            timeout=int(spec.get("timeout", 60)), params=params,
        )
    return registry


def validate_params(spec: ScriptSpec, args: dict[str, Any]) -> list[str]:
    """Gibt die Argumentliste in fester Reihenfolge zurück oder wirft ValidationError."""
    unknown = set(args) - set(spec.params)
    if unknown:
        raise ValidationError(f"Unbekannte Parameter: {', '.join(sorted(unknown))}")
    argv: list[str] = []
    for name, p in spec.params.items():
        if name not in args or args[name] in (None, ""):
            if p.required:
                raise ValidationError(f"Parameter fehlt: {name}")
            continue
        value = args[name]
        if p.type == "int":
            try:
                value = int(value)
            except (TypeError, ValueError) as e:
                raise ValidationError(f"{name} muss eine Zahl sein") from e
            if (p.min is not None and value < p.min) or (p.max is not None and value > p.max):
                raise ValidationError(f"{name} außerhalb des erlaubten Bereichs")
        elif p.type == "bool":
            value = "1" if str(value).lower() in ("1", "true", "ja", "yes") else "0"
        elif p.type == "enum":
            if str(value) not in p.choices:
                raise ValidationError(f"{name} muss einer von {p.choices} sein")
        else:
            value = str(value)
            if len(value) > 200:
                raise ValidationError(f"{name} ist zu lang")
            if p.pattern and not re.fullmatch(p.pattern, value):
                raise ValidationError(f"{name} hat ein ungültiges Format")
        argv.append(str(value))
    return argv
