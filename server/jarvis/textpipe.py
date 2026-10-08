"""Text-Pipeline ohne Audio – für /api/chat, Telegram und Matrix.

Dieselben Bausteine wie im Sprachweg (Router, Schnellweg, Bestätigungen, LLM mit
Tools), nur ohne VAD/STT/TTS. Antworten werden eingesammelt, bis der Schritt fertig ist.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

from jarvis.frames import JarvisEventFrame, TypedTextFrame
from jarvis.processors import ClientEventsProcessor, MetricsCollector, System1Processor

IDLE_SECONDS = 15 * 60


class _Collector(FrameProcessor):
    def __init__(self, owner: TextPipeline, **kwargs):
        super().__init__(**kwargs)
        self.owner = owner

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, JarvisEventFrame):
            self.owner.on_event(frame.event)
            return
        await self.push_frame(frame, direction)


class TextPipeline:
    def __init__(self, session):
        self.session = session
        self.task: PipelineWorker | None = None
        self.local_llm = None
        self.cloud_llm = None
        self.switcher = None
        self.stt = None
        self.tts = None
        self._runner: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._events: list[dict] = []
        self._done: asyncio.Future | None = None
        self.last_used = time.time()

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._runner.done()

    async def start(self) -> None:
        from jarvis.pipeline import build_llms

        s = self.session
        self.local_llm, self.cloud_llm, self.switcher = build_llms(s, s.services)
        context = s.ensure_context()
        s.refresh_system_prompt()
        aggregators = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(empty_user_turn=None))
        stages = [
            System1Processor(s, voice=False, conn=self),
            aggregators.user(),
            self.switcher or self.local_llm,
            ClientEventsProcessor(s, voice=False),
            MetricsCollector(s, conn=self),
            _Collector(self),
            aggregators.assistant(),
        ]
        self.task = PipelineWorker(Pipeline(stages), params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
                                 enable_rtvi=False, idle_timeout_secs=None)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(self.task)
        self._runner = asyncio.create_task(runner.run())
        await asyncio.sleep(0)

    async def stop(self) -> None:
        if self.task is not None:
            try:
                await self.task.cancel()
            except Exception:  # noqa: BLE001
                pass
        self.task = None

    def on_event(self, event: dict) -> None:
        self._events.append(event)
        if event.get("type") == "turn_done" and self._done is not None and not self._done.done():
            self._done.set_result(True)

    async def ask(self, text: str, timeout: float = 90.0) -> dict:
        async with self._lock:
            if not self.running:
                await self.start()
            self.last_used = time.time()
            self._events = []
            self._done = asyncio.get_running_loop().create_future()
            await self.task.queue_frames([TypedTextFrame(text, f"device:{self.session.device.id}", "", silent=True)])
            try:
                await asyncio.wait_for(self._done, timeout)
            except TimeoutError:
                logger.warning(f"Textantwort für {self.session.device.name} nach {timeout:.0f} s abgebrochen")
            events, self._events = self._events, []
        replies = [e for e in events if e.get("type") == "text" and e.get("role") == "assistant"]
        meta = replies[-1].get("meta", {}) if replies else {}
        return {
            "reply": " ".join(e["content"] for e in replies).strip(),
            "route": meta.get("route", ""), "intent": meta.get("intent", ""),
            "cloud": any(e.get("type") == "cloud" for e in events),
            "needs_confirmation": self.session.pending_valid(),
            "events": [e for e in events if e.get("type") in ("notice", "cloud", "private")],
        }


async def chat(session, text: str, speak: bool = True) -> dict:
    """Text an eine Sitzung: über die Sprachverbindung (wenn vorhanden) oder die Text-Pipeline."""
    if session.voice is not None:
        await session.voice.task.queue_frames([TypedTextFrame(text, f"device:{session.device.id}", "",
                                                              silent=not speak)])
        return {"queued": True}
    if session.text is None:
        session.text = TextPipeline(session)
    return await session.text.ask(text)


async def reap_idle(services) -> None:
    """Unbenutzte Text-Pipelines nach einer Weile beenden (Speicher)."""
    while True:
        await asyncio.sleep(60)
        for s in list(services.sessions.values()):
            if s.text is not None and time.time() - s.text.last_used > IDLE_SECONDS:
                await s.text.stop()
                s.text = None
