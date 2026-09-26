"""Jarvis-spezifische Pipecat-Prozessoren.

- WakeWordGate: lässt Audio erst nach „Hey Jarvis“ oder Push-to-Talk durch.
- System1Processor: Router, Schnellweg, Bestätigungen, LLM-Auswahl.
- ClientEventsProcessor: Zustände und Texte an Clients melden.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    FunctionCallResultFrame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMSetToolsFrame,
    ManuallySwitchServiceFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from jarvis.router.confirm import Answer, classify_confirmation
from jarvis.router.router import Route
from jarvis.security.policy import Verdict

if TYPE_CHECKING:
    from jarvis.session import JarvisSession


def _msg(session: "JarvisSession | None" = None, **kwargs) -> Frame:
    """Jarvis-Ereignis an den Client: CYD bekommt rohes JSON, RTVI-Clients eine server-message."""
    if session is not None and session.uses_rtvi:
        from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

        return RTVIServerMessageFrame(data={"jarvis": kwargs})
    return OutputTransportMessageUrgentFrame(message=kwargs)


class WakeWordGate(FrameProcessor):
    """Öffnet das Mikrofon für `listen_seconds` nach Wake-Word oder PTT."""

    def __init__(self, session: "JarvisSession", model: str = "hey_jarvis",
                 threshold: float = 0.5, listen_seconds: float = 8.0, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.threshold = threshold
        self.listen_seconds = listen_seconds
        self._open_until = 0.0
        self._buffer = np.zeros(0, dtype=np.int16)
        self._model = None
        try:
            from openwakeword.model import Model

            self._model = Model(wakeword_models=[model], inference_framework="onnx")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"openWakeWord nicht verfügbar ({e}) – nur Push-to-Talk.")

    def open(self, seconds: float | None = None) -> None:
        self._open_until = time.monotonic() + (seconds or self.listen_seconds)

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until or self.session.pending is not None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputTransportMessageFrame) and isinstance(frame.message, dict):
            if frame.message.get("type") == "ptt":
                if frame.message.get("value") == "start":
                    self.open(30)
                    await self.push_frame(_msg(self.session, type="state", value="listening"))
                else:
                    self._open_until = time.monotonic() + 1.0   # Satzende noch mitnehmen
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, InputAudioRawFrame):
            if self.is_open:
                # Solange gesprochen wird, Fenster verlängern (einfache Pegelschätzung).
                samples = np.frombuffer(frame.audio, dtype=np.int16)
                if samples.size and np.sqrt(np.mean(samples.astype(np.float32) ** 2)) > 500:
                    self._open_until = max(self._open_until, time.monotonic() + 1.5)
                await self.push_frame(frame, direction)
            elif self._model is not None and self._detect(frame.audio):
                logger.info("Wake-Word erkannt")
                self.open()
                await self.push_frame(_msg(self.session, type="state", value="listening"))
            return
        await self.push_frame(frame, direction)

    def _detect(self, audio: bytes) -> bool:
        self._buffer = np.concatenate([self._buffer, np.frombuffer(audio, dtype=np.int16)])
        hit = False
        while len(self._buffer) >= 1280:                      # 80 ms bei 16 kHz
            chunk, self._buffer = self._buffer[:1280], self._buffer[1280:]
            scores = self._model.predict(chunk)
            hit = hit or max(scores.values(), default=0) >= self.threshold
        return hit


class System1Processor(FrameProcessor):
    """Sitzt zwischen STT und LLM-Aggregator."""

    def __init__(self, session: "JarvisSession", **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self._last_text = ""
        self._last_time = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, FunctionCallResultFrame) and frame.function_name in self.session.tainted_tools:
            self.session.turn.tainted = True
        if isinstance(frame, ErrorFrame) and "LLM" in str(getattr(frame, "processor", "") or frame.error):
            # Sprachmodell nicht erreichbar → einmal pro Turn freundlich sagen statt zu schweigen.
            if not self.session.turn.notes:
                self.session.turn.notes.append("llm_error")
                await self._say("Mein Sprachmodell ist gerade nicht erreichbar. Einfache Befehle funktionieren trotzdem.")
        if not (isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM):
            await self.push_frame(frame, direction)
            return

        text = frame.text.strip()
        if not text:
            return
        # Gleiches Transkript doppelt innerhalb kurzer Zeit (VAD/STT-Segmentgrenze) → nur einmal ausführen,
        # sonst würden z. B. zwei Timer gestellt.
        now = time.monotonic()
        if text == self._last_text and now - self._last_time < 3.0:
            return
        self._last_text, self._last_time = text, now
        s = self.session
        s.new_turn()
        await self.push_frame(_msg(self.session, type="text", role="user", content=text))
        await self.push_frame(_msg(self.session, type="state", value="thinking"))

        # 1) Offene Bestätigung?
        if s.pending is not None:
            answer = await classify_confirmation(s.classifier, text, s.cfg.router.confirm_threshold)
            if answer == Answer.YES:
                pending, s.pending = s.pending, None
                result = await s.execute(pending.tool, pending.args, confirmed=True)
                await self._say(result.speech, user_text=text)
            elif answer == Answer.NO:
                s.pending = None
                await self._say("Abgebrochen.", user_text=text)
            else:
                await self._say(f"Bitte sag eindeutig ja oder nein: {s.pending.question}", user_text=text)
            return

        # 2) Router
        if not (s.router and s.cfg.router.enabled):
            await self._to_llm(frame, s.default_tools(), s.local_llm)
            return
        d = await s.router.decide(text)
        logger.debug(f"Router: {d}")

        if d.route == Route.FAST:
            intent = s.router.intents[d.intent]
            if intent.tool == "stop":
                await self.push_frame(_msg(self.session, type="state", value="idle"))
                return
            result = await s.execute(intent.tool, s.slots_to_args(intent.tool, d.slots))
            await self._say(result.speech, user_text=text)
        elif d.route == Route.ASK_SLOT:
            await self._say(d.ask or "Kannst du das genauer sagen?", user_text=text)
        elif d.route == Route.ESCALATE and s.cloud_llm is not None:
            await self.push_frame(_msg(self.session, type="cloud", value=True))
            await self._to_llm(frame, s.tools_for("cloud"), s.cloud_llm)
        elif d.route == Route.FOCUSED:
            await self._to_llm(frame, s.focus_tools(d.candidates), s.local_llm)
        else:
            await self._to_llm(frame, s.default_tools(), s.local_llm)

    async def _to_llm(self, frame: TranscriptionFrame, tools, llm) -> None:
        if llm is not None and self.session.switcher is not None:
            await self.push_frame(ManuallySwitchServiceFrame(service=llm))
        await self.push_frame(LLMSetToolsFrame(tools=tools))
        await self.push_frame(frame)

    async def _say(self, text: str, user_text: str | None = None) -> None:
        """Antwort ohne LLM: direkt sprechen und selbst in den Kontext schreiben."""
        s = self.session
        if s.context is not None:
            if user_text:
                s.context.add_message({"role": "user", "content": user_text})
            if text:
                s.context.add_message({"role": "assistant", "content": text})
        if text:
            s.last_assistant_text = text
            await self.push_frame(_msg(self.session, type="text", role="assistant", content=text))
            await self.push_frame(TTSSpeakFrame(text, append_to_context=False))


class ClientEventsProcessor(FrameProcessor):
    """Meldet Sprechzustand und LLM-Antworttext an den Client."""

    def __init__(self, session: "JarvisSession", **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self._text: list[str] = []
        self._in_llm = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            await self.push_frame(_msg(self.session, type="state", value="speaking"), FrameDirection.DOWNSTREAM)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.push_frame(_msg(self.session, type="state", value="idle"), FrameDirection.DOWNSTREAM)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._in_llm, self._text = True, []
        elif isinstance(frame, TTSTextFrame) and direction == FrameDirection.DOWNSTREAM and self._in_llm:
            self._text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame) and self._text:
            self._in_llm = False
            text = " ".join(self._text).strip()
            self._text = []
            if text and text != self.session.last_assistant_text:     # Schnellweg-Texte nicht doppelt
                self.session.last_assistant_text = text
                await self.push_frame(_msg(self.session, type="text", role="assistant", content=text))
        await self.push_frame(frame, direction)
