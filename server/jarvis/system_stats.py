"""Systemressourcen für das Dashboard: CPU, GPU (nvidia-smi), RAM, Speicher, Netzwerk."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path

from loguru import logger

try:
    import psutil
except ImportError:  # pragma: no cover – psutil ist Pflichtabhängigkeit, Fallback nur für Notbetrieb
    psutil = None


def _gpu() -> dict | None:
    """Auslastung und Speicher der ersten NVIDIA-GPU (falls vorhanden)."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, check=True).stdout
        name, util, used, total, temp = [x.strip() for x in out.splitlines()[0].split(",")]
        return {"name": name, "util": float(util), "mem_used_mb": float(used), "mem_total_mb": float(total),
                "mem_percent": round(100 * float(used) / max(1.0, float(total)), 1), "temp": float(temp)}
    except Exception as e:  # noqa: BLE001
        logger.debug(f"nvidia-smi nicht lesbar: {e}")
        return None


class SystemStats:
    """Misst im Hintergrund alle paar Sekunden und hält einen kurzen Verlauf vor."""

    def __init__(self, paths: dict[str, Path], interval: float = 3.0, history: int = 60):
        self.paths = paths
        self.interval = interval
        self.net_down: deque[float] = deque(maxlen=history)
        self.net_up: deque[float] = deque(maxlen=history)
        self.cpu_hist: deque[float] = deque(maxlen=history)
        self.latest: dict = {}
        self._task: asyncio.Task | None = None
        self._last_net: tuple[float, int, int] | None = None

    def start(self) -> None:
        if self._task is None and psutil is not None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        psutil.cpu_percent(None)
        while True:
            try:
                self.latest = await asyncio.to_thread(self.sample)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Systemwerte nicht lesbar: {e}")
            await asyncio.sleep(self.interval)

    def sample(self) -> dict:
        now = time.time()
        cpu = psutil.cpu_percent(None)
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters()
        down = up = 0.0
        if self._last_net is not None:
            dt = max(0.001, now - self._last_net[0])
            down = (net.bytes_recv - self._last_net[1]) * 8 / dt / 1e6     # Mbit/s
            up = (net.bytes_sent - self._last_net[2]) * 8 / dt / 1e6
        self._last_net = (now, net.bytes_recv, net.bytes_sent)
        self.net_down.append(round(max(0.0, down), 3))
        self.net_up.append(round(max(0.0, up), 3))
        self.cpu_hist.append(cpu)
        disks = {}
        for label, path in self.paths.items():
            try:
                usage = psutil.disk_usage(str(path))
                disks[label] = {"percent": usage.percent, "used_gb": round(usage.used / 1e9, 1),
                                "total_gb": round(usage.total / 1e9, 1)}
            except OSError:
                continue
        return {"ts": now, "cpu": cpu, "cores": psutil.cpu_count(), "ram": mem.percent,
                "ram_used_gb": round(mem.used / 1e9, 1), "ram_total_gb": round(mem.total / 1e9, 1),
                "gpu": _gpu(), "disks": disks, "net_down": self.net_down[-1], "net_up": self.net_up[-1],
                "load": [round(x, 2) for x in psutil.getloadavg()]}

    def snapshot(self) -> dict:
        data = dict(self.latest) if self.latest else (self.sample() if psutil is not None else {})
        data["history"] = {"down": list(self.net_down), "up": list(self.net_up), "cpu": list(self.cpu_hist)}
        return data
