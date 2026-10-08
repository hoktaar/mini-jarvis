"""Jarvis-spezifische Pipecat-Prozessoren.

- ClientInputProcessor: Nachrichten vom Client (PTT, Alarm quittieren, Text, hello …)
- WakeWordGate: lässt Audio erst nach „Hey Jarvis“, Push-to-Talk oder als Folgefrage durch
- System1Processor: Router, Schnellweg, Bestätigungen, Rückfragen, LLM-Auswahl, Failover
- ClientEventsProcessor: Zustände, Antworttexte und Latenzen
- SilentTurnFilter: verwirft Sprachausgabe bei getippten Fragen ohne Vorlesen
- MetricsCollector: TTFB/Verarbeitungszeiten und Cloud-Verbrauch
- EventOutput: Jarvis-Ereignisse → CYD-JSON bzw. RTVI-Server-Message
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    LLMSetToolsFrame,
    LLMTextFrame,
    ManuallySwitchServiceFrame,
    MetricsFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSTextFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from jarvis.frames import JarvisEventFrame, TypedTextFrame
from jarvis.router.confirm import Answer, classify_confirmation
from jarvis.router.router import Route

if TYPE_CHECKING:
    from jarvis.config import WakeWordCfg
    from jarvis.session import JarvisSession

# Typische Whisper-Halluzinationen bei Stille/Rauschen (deutsche Untertitel-Trainingsdaten)
HALLUCINATIONS = re.compile(
    r"^(untertitel(ung)?( im auftrag)?( des| der)? (zdf|ard|swr|wdr|br|ndr)|vielen dank fürs zuschauen|"
    r"bis zum nächsten mal|tschüss|copyright|www\.|danke fürs zuschauen|untertitel von)",
    re.IGNORECASE,
)
WAKE_PREFIX = re.compile(r"^\s*(?:(?:hey|hi|hallo|he|hei|okay|ok)[,\s]+)?(?:j|dsch|tsch)?[aä]rvis\b[,.!?\s]*",
                         re.IGNORECASE)


def ev(**kwargs) -> JarvisEventFrame:
    return JarvisEventFrame(event=kwargs)


def _msg(session: JarvisSession | None = None, **kwargs) -> Frame:
    """Kompatibilität: Jarvis-Ereignis als Frame (wird vom EventOutput umgesetzt)."""
    return ev(**kwargs)


def clean_transcript(text: str) -> str:
    text = WAKE_PREFIX.sub("", text.strip()).strip()
    if HALLUCINATIONS.match(text):
        return ""
    return text


class ClientInputProcessor(FrameProcessor):
    """Steuer-Nachrichten der Clients auswerten (CYD: JSON, PWA: RTVI client-message 'jarvis')."""

    def __init__(self, session: JarvisSession, **kwargs):
        super().__init__(**kwargs)
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        msg = None
        if isinstance(frame, InputTransportMessageFrame) and isinstance(frame.message, dict):
            msg = frame.message
        else:
            try:
                from pipecat.processors.frameworks.rtvi.frames import RTVIClientMessageFrame

                if isinstance(frame, RTVIClientMessageFrame) and frame.type == "jarvis" and isinstance(frame.data, dict):
                    msg = frame.data
            except ImportError:  # pragma: no cover
                pass
        if msg is None or "type" not in msg:
            await self.push_frame(frame, direction)
            return
        try:
            await self.handle(msg)
        except Exception:  # noqa: BLE001
            logger.exception(f"Client-Nachricht {msg.get('type')} fehlgeschlagen")

    async def handle(self, msg: dict) -> None:
        s = self.session
        services = s.services
        kind = msg.get("type")
        if kind == "hello":
            fw = str(msg.get("fw") or "")[:32]
            services.devices.touch(s.device.id, fw or None)
            s.device.fw = fw
            if services.firmware is not None and s.device.satellite:
                await services.firmware.maybe_offer(s, str(msg.get("board") or "cyd"), fw)
        elif kind == "ptt":
            start = msg.get("value") == "start"
            if start:
                await self.broadcast_interruption()     # Jarvis verstummt sofort
            if s.voice is not None and s.voice.gate is not None:
                await s.voice.gate.ptt(start)
            elif start:
                await s.emit({"type": "state", "value": "listening"})
        elif kind == "alarm_ack":
            acked = services.timers.ack(msg.get("id"))
            for tid in acked:
                await services.broadcast({"type": "alarm_stop", "id": tid})
            await services.broadcast_timers()
        elif kind == "alarm_snooze":
            minutes = max(1, min(60, int(msg.get("minutes") or 5)))
            tid = msg.get("id")
            if tid is None:
                ringing = services.timers.ringing()
                tid = ringing[0]["id"] if ringing else None
            if tid is not None and services.timers.snooze(int(tid), minutes):
                await services.broadcast({"type": "alarm_stop", "id": int(tid)})
                await s.emit({"type": "notice", "text": f"Schlummern: {minutes} Minuten"})
        elif kind == "text":
            content = str(msg.get("content") or "").strip()[:2000]
            if content:
                await self.push_frame(TypedTextFrame(content, f"device:{s.device.id}", "", silent=not msg.get("speak", True)))
        elif kind == "private":
            await s.set_private(bool(msg.get("value")))
        elif kind == "volume":
            await s.set_volume(msg.get("value"))
        elif kind == "ota_status" and services.firmware is not None:
            services.firmware.status_update(s.device, msg)
        elif kind == "stop":
            await s.stop_output()


class WakeWordGate(FrameProcessor):
    """Öffnet das Mikrofon nach Wake-Word oder PTT – mit Vorlauf, Rauschanpassung und Folgefragen."""

    PREROLL_SECONDS = 0.3

    def __init__(self, session: JarvisSession, cfg: WakeWordCfg, sample_rate: int = 16000, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.cfg = cfg
        self.threshold = cfg.threshold
        self.sample_rate = sample_rate
        self._open_until = 0.0
        self._opened_at = 0.0
        self._floor = 300.0
        self._buffer = np.zeros(0, dtype=np.int16)
        self._preroll: deque[InputAudioRawFrame] = deque()
        self._preroll_samples = 0
        self._model = None
        if cfg.enabled:
            try:
                from openwakeword.model import Model

                self._model = Model(wakeword_models=[cfg.model], inference_framework="onnx")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"openWakeWord nicht verfügbar ({e}) – nur Push-to-Talk.")

    # ---- Steuerung ----
    def open(self, seconds: float | None = None) -> None:
        now = time.monotonic()
        if not self.is_open:
            self._opened_at = now
        self._open_until = max(self._open_until, now + (seconds or self.cfg.listen_seconds))

    def close(self) -> None:
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until or self.session.pending_valid()

    async def ptt(self, start: bool) -> None:
        if start:
            self.open(30)
            await self.push_frame(ev(type="state", value="listening"))
        else:
            self._open_until = time.monotonic() + 1.0     # Satzende noch mitnehmen

    def after_utterance(self) -> None:
        """Nach einem erkannten Satz nicht unnötig lange weiter zuhören."""
        self._open_until = min(self._open_until, time.monotonic() + 1.0)

    # ---- Frames ----
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStoppedSpeakingFrame):
            mode = self.cfg.follow_up
            if mode == "always" or (mode == "question" and self.session.expecting_answer()):
                self.open(self.cfg.follow_up_seconds)
                await self.push_frame(ev(type="state", value="listening"))
            await self.push_frame(frame, direction)
            return
        if not isinstance(frame, InputAudioRawFrame):
            await self.push_frame(frame, direction)
            return

        samples = np.frombuffer(frame.audio, dtype=np.int16)
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0
        now = time.monotonic()
        if self.is_open:
            if rms > max(400.0, self._floor * 3):
                limit = self._opened_at + self.cfg.max_listen_seconds
                self._open_until = max(self._open_until, min(now + 1.5, limit))
            await self.push_frame(frame, direction)
            return
        # Geschlossen: Grundrauschen lernen, Vorlauf puffern, auf das Wake-Word hören
        self._floor = min(3000.0, 0.97 * self._floor + 0.03 * rms)
        self._preroll.append(frame)
        self._preroll_samples += samples.size
        while self._preroll and self._preroll_samples > self.PREROLL_SECONDS * self.sample_rate:
            self._preroll_samples -= len(self._preroll.popleft().audio) // 2
        if self._model is not None and self._detect(samples):
            logger.info(f"Wake-Word erkannt ({self.session.device.name})")
            self.open()
            await self.push_frame(ev(type="state", value="listening"))
            while self._preroll:
                await self.push_frame(self._preroll.popleft(), direction)
            self._preroll_samples = 0

    def _detect(self, samples: np.ndarray) -> bool:
        self._buffer = np.concatenate([self._buffer, samples])
        hit = False
        while len(self._buffer) >= 1280:                      # 80 ms bei 16 kHz
            chunk, self._buffer = self._buffer[:1280], self._buffer[1280:]
            scores = self._model.predict(chunk)
            hit = hit or max(scores.values(), default=0) >= self.threshold
        if hit:
            self._model.reset()
            self._buffer = np.zeros(0, dtype=np.int16)
        return hit


class System1Processor(FrameProcessor):
    """Sitzt zwischen STT und LLM-Aggregator und entscheidet jeden Gesprächsschritt."""

    def __init__(self, session: JarvisSession, voice: bool = True, conn=None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.voice = voice
        self.conn = conn                 # Connection bzw. TextPipeline: welche LLMs gehören zu dieser Pipeline
        self._last_text = ""
        self._last_time = 0.0

    @property
    def local_llm(self):
        return getattr(self.conn, "local_llm", None) if self.conn else self.session.local_llm

    @property
    def cloud_llm(self):
        return getattr(self.conn, "cloud_llm", None) if self.conn else self.session.cloud_llm

    @property
    def switcher(self):
        return getattr(self.conn, "switcher", None) if self.conn else self.session.switcher

    def cloud_block_reason(self) -> str | None:
        if self.cloud_llm is None:
            return "Ein Cloud-Modell ist nicht eingerichtet."
        return self.session.cloud_block_reason(check_llm=False)

    def default_provider(self) -> str | None:
        """Wer beantwortet normale Fragen? providers.llm.primary, sonst das jeweils andere."""
        cloud_ok = self.cloud_block_reason() is None
        if self.session.cfg.providers.llm.primary == "cloud" and cloud_ok:
            return "cloud"
        if self.local_llm is not None:
            return "local"
        return "cloud" if cloud_ok else None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        s = self.session
        if isinstance(frame, FunctionCallResultFrame) and frame.function_name in s.tainted_tools:
            s.mark_tainted()
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            s.turn.user_stopped = time.monotonic()
        if isinstance(frame, ErrorFrame) and direction == FrameDirection.UPSTREAM:
            await self._handle_error(frame)
        if not (isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM):
            await self.push_frame(frame, direction)
            return
        await self.handle_text(frame.text, silent=getattr(frame, "silent", False),
                               typed=isinstance(frame, TypedTextFrame))

    # ------------------------------------------------------------- Text
    async def handle_text(self, raw: str, silent: bool = False, typed: bool = False) -> None:
        s = self.session
        text = raw.strip() if typed else clean_transcript(raw)
        if not text:
            return
        # Gleiches Transkript doppelt innerhalb kurzer Zeit (VAD/STT-Segmentgrenze) → nur einmal.
        now = time.monotonic()
        if text == self._last_text and now - self._last_time < 3.0:
            return
        self._last_text, self._last_time = text, now
        user_stopped = s.turn.user_stopped
        s.previous_answer = s.last_assistant_text or s.previous_answer
        s.new_turn()
        s.turn.silent = silent or not self.voice
        s.turn.user_stopped = user_stopped or now
        if s.voice is not None and s.voice.gate is not None:
            s.voice.gate.after_utterance()
        await self.push_frame(ev(type="text", role="user", content=text))
        await self.push_frame(ev(type="state", value="thinking"))

        # 1) Offene Bestätigung?
        if s.pending_valid():
            await self._confirm(text)
            return

        # 2) Router
        if not (s.router and s.cfg.router.enabled):
            await self._to_llm(text, s.default_tools(), "local")
            return
        d = await s.router.decide(text, dialog=s.dialog, device_id=s.device.id)
        s.turn.route, s.turn.intent = d.route.value, d.intent
        if s.services.metrics is not None:
            s.services.metrics.add("router", d.latency_ms)
            s.services.metrics.count(f"route_{d.route.value}")
        logger.debug(f"Router: {d.route.value} {d.intent} {d.confidence:.2f} {d.slots}")
        s.dialog = d.dialog if d.route == Route.ASK_SLOT else None

        if d.route == Route.FAST:
            await self._fast(text, d)
        elif d.route == Route.ASK_SLOT:
            await self._say(d.ask or "Kannst du das genauer sagen?", user_text=text, meta={"route": "ask"})
        elif d.route == Route.ESCALATE:
            reason = self.cloud_block_reason()
            if reason is None:
                await self._to_llm(text, s.tools_for("cloud"), "cloud")
            elif self.local_llm is not None:
                await self.push_frame(ev(type="notice", text=reason))
                await self._to_llm(text, s.tools_for("local"), "local")
            else:
                await self._say(reason, user_text=text)
        else:
            provider = self.default_provider()
            cloud = s.cfg.providers.llm.cloud
            if provider == "local" and cloud.escalation == "auto" and len(text.split()) >= cloud.auto_min_words \
                    and self.cloud_block_reason() is None:
                provider = "cloud"
            if provider is None:
                reason = self.cloud_block_reason() or "Ein Sprachmodell ist nicht eingerichtet."
                await self._say(f"{reason} Einfache Befehle wie Timer oder Wetter funktionieren trotzdem.",
                                user_text=text)
            elif d.route == Route.FOCUSED:
                await self._to_llm(text, s.focus_tools(d.candidates, provider), provider)
            else:
                await self._to_llm(text, s.tools_for(provider), provider)

    async def _fast(self, text: str, d) -> None:
        s = self.session
        intent = s.router.intents[d.intent]
        if intent.tool == "stop":
            s.ensure_context()
            await s.stop_output()
            await self._done()
            return
        args = {**intent.args, **s.slots_to_args(intent.tool, d.slots)}
        result = await s.execute(intent.tool, args)
        await self._say(result.speech, user_text=text, meta={"route": "fast", "intent": d.intent})

    async def _confirm(self, text: str) -> None:
        s = self.session
        pending = s.pending
        answer = await classify_confirmation(s.classifier, text, s.cfg.router.confirm_threshold)
        if answer == Answer.YES:
            s.pending = None
            result = await s.execute(pending.tool, pending.args, confirmed=True, provider=pending.provider)
            await self._say(result.speech or "Erledigt.", user_text=text, meta={"route": "confirm"})
        elif answer == Answer.NO:
            s.pending = None
            await self._say("Okay, abgebrochen.", user_text=text, meta={"route": "confirm"})
        elif answer == Answer.REPEAT:
            pending.expires = time.time() + s.cfg.router.confirm_timeout
            await self._say(f"{pending.question} Soll ich das tun? Bitte sag ja oder nein.", user_text=text)
        else:
            pending.unclear += 1
            if pending.unclear >= 2:
                s.pending = None
                await self._say("Ich habe nicht eindeutig ja gehört und breche lieber ab.", user_text=text)
            else:
                pending.expires = time.time() + s.cfg.router.confirm_timeout
                await self._say(f"Bitte sag eindeutig ja oder nein: {pending.question}", user_text=text)

    # -------------------------------------------------------------- LLM
    async def _to_llm(self, text: str, tools, provider: str) -> None:
        s = self.session
        llm = self.cloud_llm if provider == "cloud" else self.local_llm
        if llm is None:
            await self._say("Ein Sprachmodell ist nicht eingerichtet. Einfache Befehle funktionieren trotzdem.",
                            user_text=text)
            return
        s.turn.provider = provider
        s.refresh_system_prompt()
        s.trim_context()
        if self.switcher is not None:
            await self.push_frame(ManuallySwitchServiceFrame(service=llm))
        if provider == "cloud":
            await self.push_frame(ev(type="cloud", value=True))
        await self.push_frame(LLMSetToolsFrame(tools=tools))
        await self.push_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}], run_llm=True))

    async def _handle_error(self, frame: ErrorFrame) -> None:
        """LLM-Fehler: auf die Cloud ausweichen (falls erlaubt) oder freundlich Bescheid sagen."""
        s = self.session
        source = getattr(frame, "processor", None)
        is_llm = source is not None and source in (self.local_llm, self.cloud_llm)
        if not is_llm and "LLM" not in str(source or "") and "llm" not in str(frame.error).lower():
            return
        cloud = s.cfg.providers.llm.cloud
        target = None
        if "failover" not in s.turn.notes and self.switcher is not None:
            if source is self.local_llm and s.turn.provider == "local" and cloud.failover \
                    and self.cloud_block_reason() is None:
                target = "cloud"
            elif source is self.cloud_llm and s.turn.provider == "cloud" and self.local_llm is not None:
                target = "local"
        if target is not None:
            s.turn.notes.append("failover")
            s.turn.provider = target
            logger.warning(f"LLM ({'lokal' if target == 'cloud' else 'Cloud'}) nicht erreichbar – "
                           f"Failover auf {target} ({frame.error})")
            if s.services.metrics is not None:
                s.services.metrics.count("failover")
            llm = self.cloud_llm if target == "cloud" else self.local_llm
            await self.push_frame(ManuallySwitchServiceFrame(service=llm))
            await self.push_frame(ev(type="cloud", value=target == "cloud"))
            await self.push_frame(LLMSetToolsFrame(tools=s.tools_for(target)))
            await self.push_frame(LLMRunFrame())
            return
        if "llm_error" not in s.turn.notes:
            s.turn.notes.append("llm_error")
            await self._say("Mein Sprachmodell ist gerade nicht erreichbar. Einfache Befehle funktionieren trotzdem.")

    # -------------------------------------------------------------- Ausgabe
    async def _say(self, text: str, user_text: str | None = None, meta: dict | None = None) -> None:
        """Antwort ohne LLM: direkt sprechen und selbst in den Kontext schreiben."""
        s = self.session
        ctx = s.ensure_context()
        if user_text:
            ctx.add_message({"role": "user", "content": user_text})
        if text:
            ctx.add_message({"role": "assistant", "content": text})
            s.last_assistant_text = text
            meta = {**(meta or {}), "confirm": s.pending_valid()}
            await self.push_frame(ev(type="text", role="assistant", content=text, meta=meta))
            if self._speaks():
                await self.push_frame(TTSSpeakFrame(text, append_to_context=False))
        await self._done(spoken=bool(text) and self._speaks())

    def _speaks(self) -> bool:
        s = self.session
        return self.voice and not s.turn.silent and s.voice is not None and s.voice.tts is not None

    async def _done(self, spoken: bool = False) -> None:
        if not spoken:
            await self.push_frame(ev(type="state", value="idle"))
        await self.push_frame(ev(type="turn_done"))


class ClientEventsProcessor(FrameProcessor):
    """Meldet Sprechzustand, LLM-Antworttext und das Ende eines Gesprächsschritts."""

    def __init__(self, session: JarvisSession, voice: bool = True, tts: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.voice = voice
        self.tts = voice and tts          # ohne TTS: Text direkt aus dem LLM sammeln
        self._text: list[str] = []
        self._in_llm = False
        self._outstanding = 0
        self._done_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        s = self.session
        if isinstance(frame, BotStartedSpeakingFrame):
            if s.turn.user_stopped and s.services.metrics is not None:
                s.services.metrics.add("turn_total", (time.monotonic() - s.turn.user_stopped) * 1000)
                s.turn.user_stopped = 0.0
            await self.push_frame(ev(type="state", value="speaking"), FrameDirection.DOWNSTREAM)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            gate_open = s.voice is not None and s.voice.gate is not None and s.voice.gate.is_open
            if not gate_open:
                await self.push_frame(ev(type="state", value="idle"), FrameDirection.DOWNSTREAM)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._in_llm, self._text = True, []
            self._cancel_done()
        elif isinstance(frame, FunctionCallInProgressFrame) and direction == FrameDirection.DOWNSTREAM:
            self._outstanding += 1
            self._cancel_done()
        elif isinstance(frame, FunctionCallResultFrame) and direction == FrameDirection.DOWNSTREAM:
            self._outstanding = max(0, self._outstanding - 1)
        elif direction == FrameDirection.DOWNSTREAM and self._in_llm and (
                (self.tts and isinstance(frame, TTSTextFrame)) or
                (not self.tts and isinstance(frame, LLMTextFrame))):
            self._text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._in_llm = False
            sep = " " if self.tts else ""
            text = re.sub(r"\s+", " ", sep.join(self._text)).strip()
            self._text = []
            if text and text != s.last_assistant_text:     # Schnellweg-Texte nicht doppelt
                s.last_assistant_text = text
                meta = {"route": s.turn.route or "llm", "intent": s.turn.intent, "provider": s.turn.provider,
                        "confirm": s.pending_valid()}
                await self.push_frame(ev(type="text", role="assistant", content=text, meta=meta))
            if s.services.gpu is not None:
                s.services.gpu.llm_used()
            self._schedule_done(spoken=bool(text) and self.tts and not s.turn.silent)
        await self.push_frame(frame, direction)

    def _cancel_done(self) -> None:
        if self._done_task is not None:
            self._done_task.cancel()
            self._done_task = None

    def _schedule_done(self, spoken: bool) -> None:
        self._cancel_done()

        async def later():
            await asyncio.sleep(0.4)
            if self._outstanding == 0 and not self._in_llm:
                if not spoken:
                    await self.push_frame(ev(type="state", value="idle"))
                await self.push_frame(ev(type="turn_done"))

        self._done_task = asyncio.create_task(later())


class SilentTurnFilter(FrameProcessor):
    """Getippte Fragen mit „nicht vorlesen“: Audio der Antwort verwerfen."""

    def __init__(self, session: JarvisSession, **kwargs):
        super().__init__(**kwargs)
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if self.session.turn.silent and isinstance(frame, (TTSAudioRawFrame, OutputAudioRawFrame)) \
                and direction == FrameDirection.DOWNSTREAM:
            return
        await self.push_frame(frame, direction)


class MetricsCollector(FrameProcessor):
    """Pipecat-Metriken einsammeln: TTFB von LLM/TTS, STT-Dauer, Cloud-Tokens → Budget."""

    def __init__(self, session: JarvisSession, conn=None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.conn = conn

    def _kind(self, processor: str) -> str | None:
        conn = self.conn or self.session.voice or self.session.text
        if conn is None:
            return None
        for name, svc in (("stt", getattr(conn, "stt", None)), ("tts", getattr(conn, "tts", None)),
                          ("llm_local", conn.local_llm), ("llm_cloud", conn.cloud_llm)):
            if svc is not None and getattr(svc, "name", None) == processor:
                return name
        return None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            try:
                self._collect(frame)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Metrik nicht auswertbar: {e}")
        await self.push_frame(frame, direction)

    def _collect(self, frame: MetricsFrame) -> None:
        from pipecat.metrics.metrics import LLMUsageMetricsData, ProcessingMetricsData, TTFBMetricsData

        services = self.session.services
        for data in frame.data:
            kind = self._kind(data.processor)
            if kind is None:
                continue
            if isinstance(data, TTFBMetricsData) and data.value > 0 and kind != "stt":
                services.metrics.add(f"{kind}_ttfb", data.value * 1000)
            elif isinstance(data, ProcessingMetricsData) and kind == "stt":
                services.metrics.add("stt", data.value * 1000)
            elif isinstance(data, LLMUsageMetricsData) and kind == "llm_cloud" and services.budget is not None:
                usage = data.value
                services.budget.record("cloud", data.model or "", usage.prompt_tokens, usage.completion_tokens)


class EventOutput(FrameProcessor):
    """Jarvis-Ereignisse in Transportnachrichten verwandeln (CYD: rohes JSON, sonst RTVI)."""

    def __init__(self, session: JarvisSession, rtvi: bool, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.rtvi = rtvi

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, JarvisEventFrame):
            if self.rtvi:
                from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

                await self.push_frame(RTVIServerMessageFrame(data={"jarvis": frame.event}), direction)
            else:
                await self.push_frame(OutputTransportMessageUrgentFrame(message=frame.event), direction)
            return
        await self.push_frame(frame, direction)
