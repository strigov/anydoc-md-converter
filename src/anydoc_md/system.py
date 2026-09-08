"""Метрики машины для регулировки нагрузки (macOS; на других ОС — безопасные значения)."""

from __future__ import annotations

import os
import subprocess
import sys


def _sysctl_int(name: str) -> int | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=3)
        return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def physical_cores() -> int:
    return _sysctl_int("hw.physicalcpu") or os.cpu_count() or 2


def memory_gb() -> float:
    b = _sysctl_int("hw.memsize")
    return b / (1024 ** 3) if b else 8.0


def memory_level_percent() -> int | None:
    """kern.memorystatus_level: сколько памяти ещё «свободно» по мнению ядра, 0–100. None — неизвестно."""
    return _sysctl_int("kern.memorystatus_level")


def load_1min() -> float:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return 0.0


def auto_workers(cap: int) -> tuple[int, str]:
    cores = physical_cores()
    mem = memory_gb()
    load = load_1min()
    by_cores = max(1, cores // 2)
    by_mem = max(1, int(mem // 4))
    n = max(1, min(cap, by_cores, by_mem))
    reason = f"ядер={cores}, RAM={mem:.0f}ГБ, load1={load:.1f}"
    if load > cores * 0.75 and n > 1:
        n = max(1, n // 2)
        reason += " (система нагружена — уменьшил вдвое)"
    return n, reason
