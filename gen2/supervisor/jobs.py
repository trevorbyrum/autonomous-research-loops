"""Supervisor-owned jobs on this host (task 1c): one directory per job, the
launcher that runs it in its own session, lookup by the stable job handle,
process identity, and the termination of an execution group.

Trace: design review §5 ("Crash fencing": record launch intent before
spawning; identity is a stable job handle, host/container identity, boot
identity and process start fingerprint, never a PID alone; a crash between
spawn and identity record is resolved by idempotent job lookup or by
terminating and reconciling the owned execution group; pause and
cancellation need confirmed descendant handling), §6 (supervisor-owned jobs
outside any harness's child lifetime; submission and reconnect under the same
invocation ID); BOUNDARIES.md Station supervisor; INVARIANTS L-2, L-3, L-4,
L-7, L-8.

A job directory (<jobs root>/<job handle>/) holds: order.json (what to run,
written before the invocation is claimed), scratch/ (the executor's working
directory, the only place it writes), lock (held by a live launcher),
spawn.json (written immediately before each launcher start), identity.json
and exit.json (written by the launcher, jobshim.py), abandoned (written by a
lookup that found the job never started), journal.json (the supervisor's own
record of what it has observed and delivered).

Lookup reads only these files and /proc: a job is found by its handle, its
launcher verified by pid, start time and boot id together, its execution
group by the session the launcher leads, members counted only if they
started no earlier than the launcher. Nothing is adopted by pid alone or by
matching a command line (INVARIANTS §11.2).

Structural limits: a descendant that leaves the session (setsid) is not a
member and is neither seen nor terminated; a pid reused by a new session
leader started after the launcher, within the job's life, would be counted
as a member; a process in uninterruptible sleep is not confirmed gone within
the grace periods, and the supervisor then says so (unconfirmed) instead of
releasing capacity. Linux only (/proc). A kill is not power loss: a host
reboot ends every member, which lookup reports as a boot mismatch.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path

PROC = Path("/proc")


def boot_id() -> str:
    return (PROC / "sys" / "kernel" / "random" / "boot_id").read_text().strip()


def proc_stat(pid: int) -> tuple[str, int, int] | None:
    """(state, session, start time in ticks) of a live pid, or None."""
    try:
        text = (PROC / str(pid) / "stat").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    fields = text[text.rindex(")") + 2:].split()
    return fields[0], int(fields[3]), int(fields[19])


def fingerprint(identity: dict) -> str:
    return f"pid={identity['pid']};starttime={identity['starttime']};session={identity['session']}"


def members(identity: dict) -> list[int]:
    """Live (not zombie) processes of the job's session started no earlier
    than its launcher, on this boot."""
    if identity.get("boot_id") != boot_id():
        return []
    found = []
    for entry in PROC.iterdir():
        if entry.name.isdigit():
            stat = proc_stat(int(entry.name))
            if stat is not None and stat[0] != "Z" and stat[1] == identity["session"] and stat[2] >= identity["starttime"]:
                found.append(int(entry.name))
    return sorted(found)


def atomic_write(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Job:
    def __init__(self, root: Path, handle: str) -> None:
        self.handle = handle
        self.dir = Path(root) / handle
        self.scratch = self.dir / "scratch"

    def read(self, name: str) -> dict | None:
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def write(self, name: str, value: dict) -> None:
        atomic_write(self.dir / name, value)

    def prepare(self, order: dict) -> None:
        """Create the job directory with its order, once; the same order again
        is a no-op, another order under this handle is refused."""
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.scratch.mkdir(mode=0o700, exist_ok=True)
        existing = self.read("order.json")
        if existing is None:
            self.write("order.json", order)
        elif existing != order:
            raise ValueError(f"job {self.handle} was prepared with another order")

    def spawn(self, launcher: list[str], before_start=lambda: None) -> subprocess.Popen:
        """Start the launcher in a new session (its execution group). spawn.json
        is written first, so a lookup after a crash knows a start was tried."""
        record = self.read("spawn.json") or {"attempts": 0, "failed": 0}
        record = {"attempts": record["attempts"] + 1, "failed": record["failed"]}
        self.write("spawn.json", record)
        before_start()
        try:
            with open(self.dir / "launcher.log", "ab") as log:
                return subprocess.Popen([*launcher, str(self.dir)], cwd=self.dir, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                        start_new_session=True, close_fds=True)
        except OSError:
            self.write("spawn.json", {**record, "failed": record["failed"] + 1})  # this start is known not to have happened
            raise

    def _lock_free(self) -> bool:
        """True if no launcher holds the job's lock (taking and dropping it)."""
        fd = os.open(self.dir / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        finally:
            os.close(fd)  # closing drops a lock taken here
        return True

    def lookup(self) -> dict:
        """What this job is, from its handle alone (idempotent; writes
        nothing). verdict: not_started (no start tried), starting (a live
        launcher has not recorded its identity yet), unstarted (a start was
        tried, no launcher is alive and none recorded an identity: the
        executor never ran — see abandon()), running (the verified launcher is
        alive and the executor has not ended), exited (its exit is recorded),
        vanished (the launcher is gone with no exit record: killed, or the
        host rebooted)."""
        identity = self.read("identity.json")
        view = {"identity": identity, "exit": None, "members": [], "same_boot": None}
        spawn = self.read("spawn.json")
        if identity is None and (spawn is None or spawn["failed"] >= spawn["attempts"]):  # no start tried, or every one refused by the OS
            return {**view, "verdict": "not_started"}
        if identity is None:
            return {**view, "verdict": "unstarted" if self._lock_free() else "starting"}
        view["same_boot"] = identity["boot_id"] == boot_id()
        stat = proc_stat(identity["pid"]) if view["same_boot"] else None
        alive = stat is not None and stat[0] != "Z" and stat[2] == identity["starttime"]
        # liveness before the exit record: a launcher writes its exit record before it ends, so one found
        # dead with no exit record never wrote it (read the other way round, a launcher ending in between
        # would look vanished)
        view["exit"] = self.read("exit.json")
        view["members"] = members(identity)
        if view["exit"] is not None:
            return {**view, "verdict": "exited"}
        return {**view, "verdict": "running" if alive else "vanished"}

    def abandon(self) -> bool:
        """Settle a start that left no identity: mark the job abandoned, then
        check that no launcher holds the lock and none recorded an identity. A
        launcher that takes the lock later reads the mark and never starts the
        executor (jobshim.py step 2). True when the executor never ran and
        never will; False when a launcher got there first."""
        try:
            os.close(os.open(self.dir / "abandoned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            pass
        return self._lock_free() and self.read("identity.json") is None

    def terminate(self, identity: dict, *, term_grace: float, kill_grace: float, reap=lambda: None) -> dict:
        """End every member of the execution group: SIGTERM, then SIGKILL after
        term_grace, then wait kill_grace for the group to be empty. Members
        are listed again (session, start time, not a zombie) before each
        round of signals. Returns {"found": members at the start,
        "confirmed": group empty}."""
        found = members(identity)
        for sig, grace in ((signal.SIGTERM, term_grace), (signal.SIGKILL, kill_grace)):
            for pid in members(identity):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + grace
            while True:
                reap()
                if not members(identity) or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            if not members(identity):
                break
        return {"found": len(found), "confirmed": not members(identity)}
