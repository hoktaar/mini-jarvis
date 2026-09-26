"""Protobuf-Serializer für Pipecat-JS/Kotlin-Clients: nur Audio und Nachrichten.

Die Client-SDKs verstehen im WebSocket-Transport ausschließlich die Frame-Arten
"audio" und "message". Alles andere (Text, Transkript, Interruption) würde dort
als Fehler geloggt – Transkripte und Unterbrechungen meldet RTVI ohnehin als
Nachrichten.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer

_ALLOWED = (OutputAudioRawFrame, OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)


class RtviProtobufSerializer(ProtobufFrameSerializer):
    def __init__(self, **kwargs):
        # RTVI-Nachrichten müssen hier durch (Basisklasse filtert sie standardmäßig).
        super().__init__(params=ProtobufFrameSerializer.InputParams(ignore_rtvi_messages=False), **kwargs)

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if not isinstance(frame, _ALLOWED):
            return None
        return await super().serialize(frame)
