"""ComfyUI-Modus: GPU für Bildgenerierung freigeben.

- on:   Whisper läuft auf der CPU, Ollama entlädt das Modell kurz nach jeder Antwort.
- auto: wie `on`, solange der ComfyUI-Container läuft (Abfrage über den Docker-Proxy).
- off:  alles auf der GPU.
"""

from __future__ import annotations

import asyncio

import httpx
from loguru import logger

from jarvis.config import JarvisConfig


class GpuMonitor:
    def __init__(self, cfg: JarvisConfig, docker_enabled: bool):
        self.cfg = cfg
        self.mode = cfg.gpu.comfyui_mode
        self.docker_enabled = docker_enabled
        self.comfy_running = False
        self._task: asyncio.Task | None = None
        self._unload: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.mode == "on" or (self.mode == "auto" and self.comfy_running)

    def start(self) -> None:
        if self.mode == "auto" and self.docker_enabled and self._task is None:
            self._task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        from jarvis.mcp_servers.docker_mcp import PROXY

        name = self.cfg.gpu.comfyui_container
        while True:
            try:
                async with httpx.AsyncClient(base_url=PROXY, timeout=5) as c:
                    r = await c.get(f"/containers/{name}/json")
                running = r.status_code == 200 and bool(r.json().get("State", {}).get("Running"))
                if running != self.comfy_running:
                    self.comfy_running = running
                    logger.info(f"ComfyUI {'läuft – GPU-Sparmodus an' if running else 'gestoppt – GPU-Sparmodus aus'}")
                    if running:
                        await self.unload_llm()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"ComfyUI-Status nicht abrufbar: {e}")
            await asyncio.sleep(30)

    def llm_used(self) -> None:
        """Nach jeder LLM-Antwort: im Sparmodus das Modell bald entladen."""
        if not self.busy:
            return
        if self._unload is not None:
            self._unload.cancel()
        self._unload = asyncio.create_task(self._delayed_unload())

    async def _delayed_unload(self) -> None:
        await asyncio.sleep(self.cfg.gpu.unload_after_seconds)
        await self.unload_llm()

    async def unload_llm(self) -> None:
        lc = self.cfg.providers.llm.local
        base = lc.base_url.rstrip("/").removesuffix("/v1")
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{base}/api/generate", json={"model": lc.model, "keep_alive": 0})
            logger.info("Ollama-Modell entladen (GPU frei)")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Ollama entladen fehlgeschlagen: {e}")

    def status(self) -> dict:
        return {"mode": self.mode, "comfyui_running": self.comfy_running, "busy": self.busy}
