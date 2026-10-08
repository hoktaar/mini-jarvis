"""Pipecat-Sprachpipeline pro Geräteverbindung."""

from __future__ import annotations

import asyncio
import time

from fastapi import WebSocket
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

from jarvis.devices import Device
from jarvis.processors import (
    ClientEventsProcessor,
    ClientInputProcessor,
    EventOutput,
    MetricsCollector,
    SilentTurnFilter,
    System1Processor,
    WakeWordGate,
)
from jarvis.providers import make_cloud_llm, make_local_llm, make_stt, make_tts
from jarvis.session import Connection, JarvisSession, Services
from jarvis.transports.cyd_serializer import CydFrameSerializer
from jarvis.transports.rtvi_serializer import RtviProtobufSerializer


def hotwords(services: Services) -> list[str]:
    names = list(services.router.known_names) if services.router else []
    return names + [sid.replace("_", " ") for sid in services.scripts]


def build_llms(session: JarvisSession, services: Services):
    local = make_local_llm(services.cfg)
    cloud = make_cloud_llm(services.cfg, services.secrets)
    llms = [local] + ([cloud] if cloud else [])
    for llm, provider in zip(llms, ["local", "cloud"], strict=False):
        session.register_functions(llm, provider)
    switcher = LLMSwitcher(llms) if len(llms) > 1 else None
    return local, cloud, switcher


async def send_initial_state(session: JarvisSession) -> None:
    """Nach dem Verbinden: Privatmodus, Lautstärke, Timer und klingelnde Alarme melden."""
    services = session.services
    from jarvis import __version__

    await session.emit({"type": "hello", "device": session.device.name, "kind": session.device.kind,
                        "room": session.device.room, "version": __version__})
    await session.emit({"type": "private", "value": session.private})
    if session.device.satellite:
        await session.emit({"type": "volume", "value": int(session.device.settings.get("volume", 70))})
    await session.emit({"type": "timers", "items": services.timers.items(), "now": time.time()})
    for row in services.timers.ringing():
        if row["device_id"] in (None, session.device.id):
            label = row["label"] or {"timer": "Timer", "alarm": "Wecker", "reminder": "Erinnerung"}.get(row["kind"])
            await session.emit({"type": "alarm", "id": row["id"], "kind": row["kind"], "label": label})
    await session.emit({"type": "state", "value": "idle"})


async def run_device_session(websocket: WebSocket, device: Device, services: Services) -> None:
    cfg = services.cfg
    rate = cfg.audio.sample_rate
    session = services.session_for(device)
    satellite = device.satellite
    # Der Browser-Player (WavMediaManager) spielt fest mit 24 kHz; der CYD bekommt 16 kHz.
    out_rate = rate if satellite else 24000

    serializer = CydFrameSerializer(rate) if satellite else RtviProtobufSerializer()
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True,
            audio_in_sample_rate=rate, audio_out_sample_rate=out_rate,
            add_wav_header=False, serializer=serializer,
        ),
    )

    gpu_busy = bool(services.gpu and services.gpu.busy)
    stt = await asyncio.to_thread(make_stt, cfg, services.secrets, hotwords(services), gpu_busy)
    tts = await asyncio.to_thread(make_tts, cfg, services.secrets)
    local_llm, cloud_llm, switcher = build_llms(session, services)
    context = session.ensure_context()
    session.refresh_system_prompt()
    aggregators = LLMContextAggregatorPair(
        context,
        # VAD sitzt als eigener Prozessor VOR Whisper (segmentierte STT braucht die VAD-Frames);
        # leere Turns lösen kein LLM aus – der System1Processor schreibt die Nutzerfrage selbst.
        user_params=LLMUserAggregatorParams(empty_user_turn=None),
    )

    conn = Connection(task=None, websocket=websocket, uses_rtvi=not satellite, local_llm=local_llm,
                      cloud_llm=cloud_llm, switcher=switcher, stt=stt, tts=tts)
    conn.system1 = System1Processor(session, voice=True, conn=conn)
    stages = [transport.input(), ClientInputProcessor(session)]
    if satellite:
        conn.gate = WakeWordGate(session, cfg.audio.wake_word, rate)
        stages.append(conn.gate)
    stages.append(VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.6))))
    if stt is not None:
        stages.append(stt)
    stages += [conn.system1, aggregators.user(), switcher or local_llm]
    if tts is not None:
        stages.append(tts)
    stages += [
        ClientEventsProcessor(session, voice=True, tts=tts is not None),
        SilentTurnFilter(session),
        MetricsCollector(session, conn=conn),
        EventOutput(session, rtvi=not satellite),
        transport.output(),
        aggregators.assistant(),
    ]

    task = PipelineWorker(
        Pipeline(stages),
        params=PipelineParams(audio_in_sample_rate=rate, audio_out_sample_rate=out_rate,
                              enable_metrics=True, enable_usage_metrics=True),
        enable_rtvi=not satellite,
        # Geräte warten oft lange auf „Hey Jarvis“ – Pipecats 5-Minuten-Leerlaufabbruch aus.
        idle_timeout_secs=None,
    )
    conn.task = task

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport, _ws):
        await task.cancel()

    if not satellite:
        @task.rtvi.event_handler("on_client_ready")
        async def _ready(rtvi):
            # bot-ready schickt der PipelineTask selbst (eigener Handler) – hier nur den Zustand
            await send_initial_state(session)
    else:
        @task.event_handler("on_pipeline_started")
        async def _started(_task, _frame):
            await send_initial_state(session)

    await session.attach_voice(conn)
    logger.info(f"Sitzung gestartet: {device.name} ({device.kind})")
    try:
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(task)
        await runner.run()
    finally:
        session.detach_voice(conn)
        logger.info(f"Sitzung beendet: {device.name}")
