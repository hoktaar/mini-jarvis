"""Pipecat-Pipeline pro Geräteverbindung."""

from __future__ import annotations

import inspect
import os

from fastapi import WebSocket
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from jarvis.devices import Device
from jarvis.processors import ClientEventsProcessor, System1Processor, WakeWordGate
from jarvis.providers import make_cloud_llm, make_local_llm, make_stt, make_tts
from jarvis.session import JarvisSession, Services
from jarvis.transports.cyd_serializer import CydFrameSerializer
from jarvis.transports.rtvi_serializer import RtviProtobufSerializer

SATELLITES = {"cyd", "esp32"}
# MCP-Server, die Jarvis selbst in-process abbildet (Policy!), nicht per MCPClient.
IN_PROCESS_MCP = {"docker"}


async def _start_mcp(session: JarvisSession, llms: list) -> None:
    """Externe MCP-Server (z. B. SearXNG) starten und ihre Tools registrieren."""
    from mcp import StdioServerParameters
    from pipecat.services.mcp_service import MCPClient

    for m in session.cfg.mcp_servers:
        if not m.enabled or m.name in IN_PROCESS_MCP or m.transport != "stdio":
            continue
        env = {"PATH": os.environ.get("PATH", ""), **m.env}
        client = MCPClient(StdioServerParameters(command=m.command, args=m.args, env=env))
        try:
            await client.start()
            schema = await client.register_tools(llms[0])
            for other in llms[1:]:
                res = client.register_tools_schema(schema, other)
                if inspect.isawaitable(res):
                    await res
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MCP-Server {m.name} nicht verfügbar: {e}")
            continue
        session.mcp_clients.append(client)
        session.extra_tools += [(fn, m.risk) for fn in schema.standard_tools]
        if m.taint:
            session.tainted_tools |= {fn.name for fn in schema.standard_tools}


async def run_device_session(websocket: WebSocket, device: Device, services: Services) -> None:
    cfg = services.cfg
    rate = cfg.audio.sample_rate
    session = JarvisSession(services, device)
    services.sessions[device.id] = session

    serializer = CydFrameSerializer(rate) if device.kind in SATELLITES else RtviProtobufSerializer()
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True,
            audio_in_sample_rate=rate, audio_out_sample_rate=rate,
            add_wav_header=False, serializer=serializer,
        ),
    )

    stt = make_stt(cfg, services.secrets, services.router.known_names if services.router else [])
    tts = make_tts(cfg, services.secrets)
    session.local_llm = make_local_llm(cfg)
    session.cloud_llm = make_cloud_llm(cfg, services.secrets)
    llms = [session.local_llm] + ([session.cloud_llm] if session.cloud_llm else [])
    for llm, provider in zip(llms, ["local", "cloud"]):
        session.register_functions(llm, provider)
    await _start_mcp(session, llms)
    llm_stage = LLMSwitcher(llms) if len(llms) > 1 else session.local_llm
    session.switcher = llm_stage if len(llms) > 1 else None

    context = LLMContext(
        messages=[{"role": "system", "content": cfg.persona}],
        tools=session.default_tools(),
    )
    session.context = context
    aggregators = LLMContextAggregatorPair(
        context,
        # VAD sitzt als eigener Prozessor VOR Whisper (segmentierte STT braucht die VAD-Frames);
        # leere Turns lösen kein LLM aus (wichtig nach Schnellweg-Antworten).
        user_params=LLMUserAggregatorParams(empty_user_turn=None),
    )

    stages = [transport.input()]
    if device.kind in SATELLITES and cfg.audio.wake_word.enabled:
        ww = cfg.audio.wake_word
        stages.append(WakeWordGate(session, ww.model, ww.threshold, ww.listen_seconds))
    stages += [
        VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.6))),
        stt,
        System1Processor(session),
        aggregators.user(),
        llm_stage,
        tts,
        ClientEventsProcessor(session),
        transport.output(),
        aggregators.assistant(),
    ]

    task = PipelineTask(
        Pipeline(stages),
        params=PipelineParams(audio_in_sample_rate=rate, audio_out_sample_rate=rate,
                              allow_interruptions=device.kind not in SATELLITES),
        enable_rtvi=device.kind not in SATELLITES,
    )
    session.task = task
    logger.info(f"Sitzung gestartet: {device.name} ({device.kind})")
    try:
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        for client in session.mcp_clients:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        services.sessions.pop(device.id, None)
        logger.info(f"Sitzung beendet: {device.name}")
