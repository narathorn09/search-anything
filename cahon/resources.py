"""Keep scanning from making the computer sluggish.

* Performance profiles decide how many threads a scan may use.
* ``Brake`` samples CPU and memory twice a second and makes scan threads
  pause while the app uses more than its share, or while the machine itself
  is short of RAM or busy with other work.
* Scan threads lower their own OS priority, so interactive apps win.
* In a container (Docker / Kubernetes) the limits of the container (cgroup
  CPU quota and memory limit) are used instead of the host's, so the scan
  stays inside the pod's budget and is never OOM-killed together with it.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import psutil
except ImportError:  # optional: without it the brake only limits threads
    psutil = None

log = logging.getLogger(__name__)

CGROUP_ROOT = "/sys/fs/cgroup"
UNLIMITED = 1 << 60


@dataclass(frozen=True)
class ContainerLimits:
    cpus: float | None = None  # CPU quota in cores (None = no quota)
    memory_bytes: int | None = None  # memory limit (None = no limit)
    root: str = CGROUP_ROOT

    def memory_used(self) -> int | None:
        for rel in ("memory.current", "memory/memory.usage_in_bytes"):  # cgroup v2, v1
            value = _read_int(Path(self.root) / rel)
            if value is not None:
                return value
        return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    text = _read(path)
    try:
        return int(text) if text not in (None, "", "max") else None
    except ValueError:
        return None


def read_container_limits(root: str = CGROUP_ROOT, host_memory: int | None = None) -> ContainerLimits:
    """CPU quota and memory limit of this container (cgroup v2 or v1)."""
    base = Path(root)
    cpus = None
    cpu_max = _read(base / "cpu.max")  # v2: "max 100000" or "200000 100000"
    if cpu_max:
        quota, _, period = cpu_max.partition(" ")
        if quota != "max" and period:
            cpus = int(quota) / int(period)
    else:  # v1
        quota, period = _read_int(base / "cpu/cpu.cfs_quota_us"), _read_int(base / "cpu/cpu.cfs_period_us")
        if quota and quota > 0 and period:
            cpus = quota / period
    memory = _read_int(base / "memory.max")
    if memory is None:
        memory = _read_int(base / "memory/memory.limit_in_bytes")
    if host_memory is None and psutil is not None:
        host_memory = psutil.virtual_memory().total
    if memory is not None and (memory >= UNLIMITED or (host_memory and memory >= host_memory)):
        memory = None  # "no limit" is reported as a huge number
    return ContainerLimits(cpus, memory, root)


CONTAINER = read_container_limits() if sys.platform.startswith("linux") else ContainerLimits()
HOST_CPUS = os.cpu_count() or 2
CPU_CAPACITY = min(HOST_CPUS, CONTAINER.cpus) if CONTAINER.cpus else float(HOST_CPUS)  # cores we may use
CPU_COUNT = max(1, math.ceil(CPU_CAPACITY))
MIN_FREE_RAM_MB = 400  # pause if the machine (or container) has less free RAM than this
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


def ram_limits_mb(profile: Profile, limits: ContainerLimits = CONTAINER) -> tuple[int, int]:
    """(soft, hard) RAM limits for the scanner. Soft: the brake pauses.
    Hard: the supervisor kills the worker. Inside a container both stay well
    below the container limit, so the kernel never kills the whole app."""
    soft, hard = profile.max_ram_mb, profile.max_ram_mb * 1.5
    if limits.memory_bytes:
        pod_mb = limits.memory_bytes / 1e6
        soft, hard = min(soft, pod_mb * 0.5), min(hard, pod_mb * 0.7)
    return int(soft), int(hard)


def min_free_ram_mb(limits: ContainerLimits = CONTAINER) -> float:
    if limits.memory_bytes:
        return min(MIN_FREE_RAM_MB, limits.memory_bytes / 1e6 * 0.15)
    return MIN_FREE_RAM_MB


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

    def __init__(self, profile: Profile, stop: threading.Event, sampler=None, limits: ContainerLimits = CONTAINER):
        self.profile = profile
        self.limits = limits
        self.max_ram_mb = ram_limits_mb(profile, limits)[0]
        self.min_free_mb = min_free_ram_mb(limits)
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
        cpu = self._proc.cpu_percent(None) / CPU_CAPACITY
        # In a container with a CPU quota, how busy the *host* is says nothing
        # about our budget (the quota already caps us), so don't yield to it.
        system = 0.0 if self.limits.cpus else psutil.cpu_percent(None)
        ram = self._proc.memory_info().rss / 1e6
        used = self.limits.memory_used() if self.limits.memory_bytes else None
        if used is not None:
            free = (self.limits.memory_bytes - used) / 1e6
        else:
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
        if self.ram_mb > self.max_ram_mb:
            return f"ตัวสแกนใช้ RAM {self.ram_mb:.0f} MB เกินขีดจำกัด {self.max_ram_mb} MB"
        if self.free_ram_mb < self.min_free_mb:
            where = "ของคอนเทนเนอร์" if self.limits.memory_bytes else "ของเครื่อง"
            return f"RAM ว่าง{where}เหลือ {self.free_ram_mb:.0f} MB"
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
