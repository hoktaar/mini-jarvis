"""Kleiner OpenAI-kompatibler LLM-Server für Tests (Streaming, Tool-Calls, Fehler).

Verhalten nach der letzten Nachricht:
- Tool-Ergebnis zuletzt          → „Erledigt: <Ergebnis>“
- enthält „llm-timer“            → Tool-Call set_timer(120, „Test“)
- enthält „llm-container“        → Tool-Call container_action(jellyfin, restart)
- enthält „llm-fehler“           → HTTP 500
- sonst                          → „Antwort auf: <Text>“
Alle Anfragen landen in REQUESTS (für Prüfungen in Tests).
"""

from __future__ import annotations

import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

REQUESTS: list[dict] = []
app = FastAPI()


def _chunk(delta: dict, finish: str | None = None) -> str:
    body = {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": "mock",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(body)}\n\n"


def _usage() -> str:
    body = {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": "mock",
            "choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    return f"data: {json.dumps(body)}\n\n"


def _text_stream(text: str):
    yield _chunk({"role": "assistant", "content": ""})
    for word in text.split(" "):
        yield _chunk({"content": word + " "})
    yield _chunk({}, "stop")
    yield _usage()
    yield "data: [DONE]\n\n"


def _tool_stream(name: str, args: dict):
    yield _chunk({"role": "assistant", "content": None, "tool_calls": [
        {"index": 0, "id": f"call_{int(time.time() * 1000)}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]})
    yield _chunk({}, "tool_calls")
    yield _usage()
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    REQUESTS.append(body)
    messages = body.get("messages", [])
    last = messages[-1] if messages else {}
    content = last.get("content") or ""
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    if last.get("role") == "tool":
        gen = _text_stream(f"Erledigt: {content[:80]}")
    elif "llm-fehler" in content:
        return JSONResponse({"error": {"message": "kaputt"}}, status_code=500)
    elif "llm-timer" in content:
        gen = _tool_stream("set_timer", {"duration": 120, "label": "Test"})
    elif "llm-container" in content:
        gen = _tool_stream("container_action", {"name": "jellyfin", "action": "restart"})
    else:
        gen = _text_stream(f"Antwort auf: {content}")
    return StreamingResponse(gen, media_type="text/event-stream")


@app.get("/api/tags")
async def tags():
    return {"models": [{"name": "mock"}]}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve_in_thread(port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=11500)
