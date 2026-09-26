"""Serializer für schlanke ESP32-Clients (CYD): rohes PCM + kleine JSON-Nachrichten.

Siehe docs/PROTOCOL.md, Abschnitt 2.
"""

from __future__ import annotations

import json

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer


class CydFrameSerializer(FrameSerializer):
    def __init__(self, sample_rate: int = 16000, **kwargs):
        super().__init__(**kwargs)
        self.sample_rate = sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputAudioRawFrame):
            # Pipeline läuft mit 16 kHz Ausgabe (PipelineParams), daher kein Resampling nötig.
            return frame.audio
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "clear"})
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            msg = frame.message
            if isinstance(msg, dict) and "type" in msg:
                return json.dumps(msg, ensure_ascii=False)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes):
            if not data:
                return None
            return InputAudioRawFrame(audio=data, sample_rate=self.sample_rate, num_channels=1)
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return None
        if isinstance(msg, dict) and "type" in msg:
            return InputTransportMessageFrame(message=msg)
        return None
