"""Eigene Pipecat-Frames von Jarvis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipecat.frames.frames import SystemFrame, TranscriptionFrame


@dataclass
class JarvisEventFrame(SystemFrame):
    """Ereignis an den Client (state, text, alarm, timers …).

    Läuft durch die Pipeline bis zum EventOutput, der es je nach Client in eine
    CYD-JSON-Nachricht oder eine RTVI-Server-Message verwandelt.
    """

    event: dict[str, Any] = field(default_factory=dict)


@dataclass
class TypedTextFrame(TranscriptionFrame):
    """Getippter Text (PWA, Chat-Bots) – wie ein Transkript, optional ohne Sprachausgabe."""

    silent: bool = False
