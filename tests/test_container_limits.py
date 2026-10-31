import threading
from pathlib import Path

from search_anything.resources import (PROFILES, Brake, ContainerLimits, min_free_ram_mb, ram_limits_mb,
                                       read_container_limits)

GiB = 1024 ** 3


def write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_cgroup_v2_limits(tmp_path):
    write(tmp_path, "cpu.max", "150000 100000\n")
    write(tmp_path, "memory.max", f"{GiB}\n")
    write(tmp_path, "memory.current", f"{300 * 1024 * 1024}\n")
    lim = read_container_limits(str(tmp_path), host_memory=16 * GiB)
    assert lim.cpus == 1.5 and lim.memory_bytes == GiB
    assert lim.memory_used() == 300 * 1024 * 1024


def test_cgroup_v2_unlimited(tmp_path):
    write(tmp_path, "cpu.max", "max 100000")
    write(tmp_path, "memory.max", "max")
    lim = read_container_limits(str(tmp_path), host_memory=16 * GiB)
    assert lim.cpus is None and lim.memory_bytes is None


def test_cgroup_v1_limits_and_unlimited(tmp_path):
    write(tmp_path, "cpu/cpu.cfs_quota_us", "200000")
    write(tmp_path, "cpu/cpu.cfs_period_us", "100000")
    write(tmp_path, "memory/memory.limit_in_bytes", str(2 * GiB))
    write(tmp_path, "memory/memory.usage_in_bytes", str(GiB))
    lim = read_container_limits(str(tmp_path), host_memory=16 * GiB)
    assert lim.cpus == 2.0 and lim.memory_bytes == 2 * GiB and lim.memory_used() == GiB
    write(tmp_path, "cpu/cpu.cfs_quota_us", "-1")
    write(tmp_path, "memory/memory.limit_in_bytes", "9223372036854771712")  # "no limit"
    lim = read_container_limits(str(tmp_path), host_memory=16 * GiB)
    assert lim.cpus is None and lim.memory_bytes is None


def test_no_cgroup_files(tmp_path):
    assert read_container_limits(str(tmp_path), host_memory=16 * GiB) == ContainerLimits(None, None, str(tmp_path))


def test_ram_limits_follow_the_pod():
    balanced = PROFILES["balanced"]  # 800 MB soft, 1200 MB hard on a normal machine
    assert ram_limits_mb(balanced, ContainerLimits()) == (800, 1200)
    small_pod = ContainerLimits(memory_bytes=1_000_000_000)  # 1000 MB pod
    assert ram_limits_mb(balanced, small_pod) == (500, 700)  # stays inside the pod
    assert min_free_ram_mb(small_pod) == 150
    assert ram_limits_mb(balanced, ContainerLimits(memory_bytes=8_000_000_000)) == (800, 1200)


def test_brake_uses_container_free_memory(tmp_path):
    write(tmp_path, "memory.max", str(1_000_000_000))
    write(tmp_path, "memory.current", str(900_000_000))
    lim = read_container_limits(str(tmp_path), host_memory=16 * GiB)
    brake = Brake(PROFILES["balanced"], threading.Event(), limits=lim,
                  sampler=lambda: (5.0, 0.0, 200.0, (lim.memory_bytes - lim.memory_used()) / 1e6))
    brake.sample(force=True)
    assert "คอนเทนเนอร์" in brake.over_limit(memory_only=True)  # 100 MB free < 150 MB
    write(tmp_path, "memory.current", str(300_000_000))
    brake = Brake(PROFILES["balanced"], threading.Event(), limits=lim,
                  sampler=lambda: (5.0, 0.0, 200.0, (lim.memory_bytes - lim.memory_used()) / 1e6))
    brake.sample(force=True)
    assert brake.over_limit() == ""
