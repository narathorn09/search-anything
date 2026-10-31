"""Keep scanning from making the computer sluggish.

* Performance profiles decide how many threads a scan may use.
* ``Brake`` samples CPU and memory twice a second and makes scan threads
  pause while the app uses more than its share, or while the machine itself
  is short of RAM or busy with other work.
* Scan threads lower their own OS priority, so interactive apps win.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass

try:
    import psutil
except ImportError:  # optional: without it the brake only limits threads
    psutil = None

log = logging.getLogger(__name__)

CPU_COUNT = os.cpu_count() or 2
MIN_FREE_RAM_MB = 400  # pause if the whole machine has less free RAM than this
BUSY_SYSTEM_CPU = 90  # pause (eco/balanced) while the machine is this busy


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    extract_workers: int  # threads reading files
    write_parallel: int  # index shards written at the same time
    max_cpu: int  # % of the whole machine this app may use while scanning
    max_ram_mb: int  # memory (RSS) of this app before scanning pauses
    yield_to_system: bool  # also pause while other apps keep the CPU busy


PROFILES: dict[str, Profile] = {
    "eco": Profile("eco", "ประหยัด", 1, 1, 25, 400, True),
    "balanced": Profile("balanced", "สมดุล", 2, 2, 50, 800, True),
    "fast": Profile("fast", "เร็วสุด", min(8, CPU_COUNT * 2), 4, 90, 2000, False),
}
DEFAULT_PROFILE = "balanced"


def lower_thread_priority() -> None:
    """Best effort: make the calling thread a background/low-priority thread."""
    try:
        if sys.platform.startswith("linux"):
            # On Linux, niceness is per thread.
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        elif sys.platform.startswith("win"):
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # THREAD_MODE_BACKGROUND_BEGIN also lowers disk and memory priority.
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 0x00010000)
    except Exception as exc:  # unsupported platform / permissions
        log.debug("could not lower thread priority: %s", exc)


class Brake:
    """Pauses scan threads while resource use is above the profile's limits."""

    SAMPLE_EVERY = 0.5

    def __init__(self, profile: Profile, stop: threading.Event, sampler=None):
        self.profile = profile
        self.stop = stop
        self._lock = threading.Lock()
        self._last = 0.0
        self._sampler = sampler or self._psutil_sample
        self.cpu = 0.0  # this app, % of the whole machine
        self.system_cpu = 0.0
        self.ram_mb = 0.0  # this app
        self.free_ram_mb = float("inf")
        self.reason = ""
        self.paused_seconds = 0.0
        self.enabled = sampler is not None or psutil is not None
        if psutil is not None and sampler is None:
            self._proc = psutil.Process()
            self._proc.cpu_percent(None)
            psutil.cpu_percent(None)

    def _psutil_sample(self) -> tuple[float, float, float, float]:
        cpu = self._proc.cpu_percent(None) / CPU_COUNT
        system = psutil.cpu_percent(None)
        ram = self._proc.memory_info().rss / 1e6
        free = psutil.virtual_memory().available / 1e6
        return cpu, system, ram, free

    def sample(self, force: bool = False) -> None:
        if not self.enabled:
            return
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last < self.SAMPLE_EVERY:
                return
            self._last = now
            self.cpu, self.system_cpu, self.ram_mb, self.free_ram_mb = self._sampler()

    def over_limit(self, memory_only: bool = False) -> str:
        """Why scanning should pause right now ('' = go ahead)."""
        p = self.profile
        if self.ram_mb > p.max_ram_mb:
            return f"ตัวสแกนใช้ RAM {self.ram_mb:.0f} MB เกินขีดจำกัด {p.max_ram_mb} MB"
        if self.free_ram_mb < MIN_FREE_RAM_MB:
            return f"RAM ว่างของเครื่องเหลือ {self.free_ram_mb:.0f} MB"
        if memory_only:
            return ""
        if self.cpu > p.max_cpu:
            return f"ตัวสแกนใช้ CPU {self.cpu:.0f}% เกินขีดจำกัด {p.max_cpu}%"
        if p.yield_to_system and self.system_cpu > BUSY_SYSTEM_CPU:
            return f"เครื่องกำลังทำงานหนัก (CPU รวม {self.system_cpu:.0f}%)"
        return ""

    def wait(self, memory_only: bool = False, max_wait: float | None = None) -> None:
        """Block while over the limits. Returns at once when stopped."""
        if not self.enabled:
            return
        started = None
        while not self.stop.is_set():
            self.sample()
            why = self.over_limit(memory_only)
            if not why:
                break
            if started is None:
                started = time.monotonic()
            self.reason = why
            if max_wait is not None and time.monotonic() - started >= max_wait:
                break
            time.sleep(0.2)
        if started is not None:
            self.paused_seconds += time.monotonic() - started
            self.reason = ""

    def snapshot(self) -> dict:
        return {
            "cpu": round(self.cpu), "system_cpu": round(self.system_cpu),
            "ram_mb": round(self.ram_mb), "free_ram_mb": None if self.free_ram_mb == float("inf") else round(self.free_ram_mb),
            "throttled": self.reason, "paused_seconds": round(self.paused_seconds, 1),
        }
