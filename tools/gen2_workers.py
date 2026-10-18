"""CPU allocation for verification processes, including their child interpreters.

Read cgroup v2/v1 quotas (including visible ancestors) and affinity. Never use
the host's cpu_count. An explicit allocation can lower, but cannot raise, the
detected budget. Engine and gateway modes execute sequentially; each owns the
whole allocation while running. Mutation workers leave one slot for children.
"""
from __future__ import annotations

import os
from pathlib import Path


def quota_at(directory: Path, version: int) -> float | None:
    try:
        if version == 2:
            quota, period = (directory / "cpu.max").read_text().split()
            return None if quota == "max" else int(quota) / int(period)
        quota = int((directory / "cpu.cfs_quota_us").read_text())
        period = int((directory / "cpu.cfs_period_us").read_text())
        return None if quota < 0 else quota / period
    except FileNotFoundError:
        return None


def cpu_budget(*, proc: Path = Path("/proc"), affinity: int | None = None,
               allocation: str | None = None) -> int:
    """Conservative whole CPU slots; fractional quotas still allow one process.

    Mount roots matter for cgroup namespaces. An inaccessible quota fails
    visibly rather than silently substituting the host's CPU count.
    """
    if affinity is None:
        affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else 1
    limits = [float(affinity)]
    groups = [line.split(":", 2) for line in (proc / "self/cgroup").read_text().splitlines()]
    for line in (proc / "self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        fields, filesystem = before.split(), after.split()
        version = 2 if filesystem[0] == "cgroup2" else 1
        if filesystem[0] != "cgroup2" and not (filesystem[0] == "cgroup" and "cpu" in filesystem[2].split(",")):
            continue
        root, mount = Path(fields[3]), Path(fields[4])
        for _, controllers, relative in groups:
            if (version == 2 and controllers) or (version == 1 and "cpu" not in controllers.split(",")):
                continue
            group = Path(relative)
            # A private cgroup namespace can expose a membership outside the
            # mounted hierarchy (including /../..). Only inspect visible paths;
            # the mount root still carries the container's effective quota.
            current = (mount / group.relative_to(root) if group.is_relative_to(root)
                       and ".." not in group.parts else mount)
            while True:
                quota = quota_at(current, version)
                if quota is not None:
                    if quota <= 0:
                        raise ValueError(f"invalid CPU quota at {current}")
                    limits.append(quota)
                if current == mount:
                    break
                current = current.parent
    value = allocation if allocation is not None else os.environ.get("GEN2_CPU_BUDGET")
    if value is not None:
        explicit = int(value)
        if explicit < 1:
            raise ValueError("GEN2_CPU_BUDGET must be positive")
        limits.append(float(explicit))
    return max(1, int(min(limits)))


def mutation_workers(requested: int | None = None) -> int:
    available = max(1, cpu_budget() - 1)
    if requested is not None and requested < 1:
        raise ValueError("--jobs must be positive")
    return available if requested is None else min(requested, available)
