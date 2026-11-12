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
record of what it has observed and delivered), journal.lock (held by the one
supervisor caller advancing or recovering the job: Job.hold).

Lookup reads only these files and /proc: a job is found by its handle, its
launcher verified by pid, start time and boot id together, its execution
group by the session the launcher leads, members counted only if they
started no earlier than the launcher. Nothing is adopted by pid alone or by
matching a command line (INVARIANTS §11.2).

Structural limits: a descendant that leaves the session (setsid) is not a
member and is neither seen nor terminated; a pid reused by a new session
leader started after the launcher, within the job's life, would be counted
as a member; members are listed, then signalled by pid, and in between a
listed pid can exit and be reused by an unrelated process, which would then
receive the signal; a process in uninterruptible sleep is not confirmed gone within
the grace periods, and the supervisor then says so (unconfirmed) instead of
releasing capacity. Linux only (/proc). A kill is not power loss: a host
reboot ends every member, which lookup reports as a boot mismatch.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import re
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path

PROC = Path("/proc")
FLOCK = "hhqqi4x"  # struct flock on Linux: l_type, l_whence, l_start, l_len, l_pid (jobshim.py takes the job's lock with the same layout)
_HELD = threading.local()  # the journal locks this thread holds, by (device, inode): Job.hold


class Taken(Exception):
    """Another holder kept a job's journal lock until the wait's deadline."""


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


VALID, FOREIGN, PRE_PREPARE, CORRUPT = "valid", "foreign", "pre_prepare", "corrupt"
INVOCATION_ID = re.compile(r"inv_[A-Za-z0-9_-]{8,64}")  # common.schema.json#/$defs/invocation_id: also the job's directory name
HARNESS_ORDER_KEYS = frozenset({"command", "env"})  # the whole of a qualification harness's order (the T9 harness's Job.prepare)


class Entry:
    """One jobs-root entry as the station reads it: its `kind`, its order when VALID, the journal when it has one, and why when CORRUPT."""
    def __init__(self, name: str, kind: str, order: dict | None = None, journal: dict | None = None, reason: str = "") -> None:
        self.name, self.kind, self.order, self.journal, self.reason = name, kind, order, journal or {}, reason


def _present(path: Path) -> tuple[bool, object]:
    try:
        return True, json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, None


def _count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _obj(v: object) -> bool:
    return isinstance(v, dict)


def _dated(v: object) -> bool:
    return isinstance(v, dict) and "since" in v


def _opt(check):
    return lambda v: v is None or check(v)


def _text(v: object) -> bool:
    return isinstance(v, str) and bool(v)


def _id(v: object) -> bool:
    return isinstance(v, str) and bool(INVOCATION_ID.fullmatch(v))


# THE contract of the two files consumers read: field -> (must be present, validator of a present value). A field a consumer
# reads (journal[...]/.get/.pop/.setdefault, order[...]/.get) is listed here, and a test fails if one is not; absence of an optional
# field keeps the consumer's default (a fresh journal), but a present value that fails its validator is CORRUPT, never normalized.
JOURNAL_FIELDS = {
    "incident": (False, _opt(_dated)), "exhausted": (False, _opt(_obj)), "collected": (False, _opt(_obj)),
    "recovering": (False, _opt(lambda v: _obj(v) and _dated(v.get("incident")))),
    "recoveries": (False, lambda v: isinstance(v, list) and all(_obj(r) and _dated(r.get("incident")) for r in v)),
    "budgets": (False, lambda v: _obj(v) and all(_count(n) for n in v.values())),  # an object of retry counters, each incremented by _spend
    "revision": (False, _count), "settled": (False, _opt(_text)), "unlaunched": (False, lambda v: isinstance(v, bool)),
    "recorded": (False, lambda v: isinstance(v, bool)),
    **{k: (False, _opt(_obj)) for k in ("write_failure", "pending", "refusal", "unresolved", "outage", "observing", "grant", "dispatch",
                                        "record_failure", "envelope", "spawn_refused", "refused")},
}
ORDER_FIELDS = {
    "invocation_id": (True, _id), "topic_id": (True, _text), "kind": (True, _text), "config_bundle_hash": (True, _text),
    "deadline_at": (True, _text), "lease_expires_at": (True, _opt(_text)), "requested_by_invocation_id": (True, _opt(_text)),
    "parent_invocation_id": (False, _opt(_id)), "retry_of": (False, _opt(_text)), "reservation": (False, _opt(_obj)),
    "env": (False, lambda v: _obj(v) and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items())),
    "live": (False, lambda v: isinstance(v, bool)), "plan": (False, _obj),
}


def _fields(doc: object, table: dict) -> bool:
    return isinstance(doc, dict) and all((name in doc if required else True) and (name not in doc or check(doc[name]))
                                         for name, (required, check) in table.items())


def _order_shaped(order: object, name: str) -> bool:
    """A station order: every ORDER_FIELDS entry, naming this directory, and a delegate naming its parent."""
    return (_fields(order, ORDER_FIELDS) and name == "job-" + order["invocation_id"]
            and (order["kind"] != "delegate" or order.get("parent_invocation_id") is not None))


def entries(root: Path) -> list[Entry]:
    """Interpret every entry of the jobs root, once and statelessly (nothing cached or written); every reader of the root uses this.
    VALID: an order whose consumed fields are typed (ORDER_FIELDS) and a journal, if any, likewise (JOURNAL_FIELDS).
    FOREIGN: positively not this station's: an order whose keys are exactly the harness's and no journal. PRE_PREPARE: a directory the
    driver made before its order (nothing but a scratch). Everything else (damaged or non-object JSON, missing or wrong identity, a
    journal beside an unreadable order, an unknown entry) is CORRUPT: ambiguous station state, never absence, never capacity released."""
    found = []
    for path in sorted(Path(root).iterdir()) if Path(root).is_dir() else ():
        job, name = Job(root, path.name), path.name
        if not path.is_dir():
            found.append(Entry(name, CORRUPT, reason="not a job directory"))
            continue
        try:
            files = {n: _present(path / n) for n in ("order.json", "journal.json")}  # (exists, decoded): a JSON null is present, never absence
        except (ValueError, OSError) as failure:
            found.append(Entry(name, CORRUPT, reason=f"unreadable order or journal: {type(failure).__name__}"))
            continue
        (has_order, order), (has_journal, journal) = files["order.json"], files["journal.json"]
        if not has_order and not has_journal:
            kind = PRE_PREPARE if {e.name for e in path.iterdir()} <= {"scratch"} else CORRUPT
            found.append(Entry(name, kind, reason="" if kind == PRE_PREPARE else "files without an order"))
        elif has_journal and not _fields(journal, JOURNAL_FIELDS):
            found.append(Entry(name, CORRUPT, reason="journal is not a station journal"))
        elif not has_journal and isinstance(order, dict) and set(order) == HARNESS_ORDER_KEYS:
            found.append(Entry(name, FOREIGN))
        elif has_order and _order_shaped(order, name):
            found.append(Entry(name, VALID, order, journal))
        else:
            found.append(Entry(name, CORRUPT, reason="order is not a station order for this directory" if has_order else "journal without an order"))
    return found


def orders(root: Path) -> list[dict]:
    """The valid station orders, for the readers that follow orders only (Driver, discovery): the same interpretation, without the rest."""
    return [entry.order for entry in entries(root) if entry.kind == VALID]


def census(root: Path) -> dict:
    """The classified facts of the root, for status: counts of each kind and each corrupt entry with its reason."""
    found = entries(root)
    corrupt = [{"entry": e.name, "reason": e.reason} for e in found if e.kind == CORRUPT]
    return {"valid": sum(e.kind == VALID for e in found), "foreign": sum(e.kind == FOREIGN for e in found),
            "pre_prepare": sum(e.kind == PRE_PREPARE for e in found), "corrupt": corrupt, "blocking": bool(corrupt)}


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

    @contextlib.contextmanager
    def hold(self, deadline: float, poll_s: float):
        """Hold the job's journal lock: an open-file-description write lock on
        journal.lock, so one holder at a time across the processes and the
        threads of this host. It is released when its holder lets go or
        dies (the kernel drops it with the holder's last descriptor), so a
        crashed holder leaves nothing to clean up. Waits, polling every
        poll_s, until `deadline` (time.monotonic()), then raises Taken. A
        thread holding it already holds it again at once, released by its
        outermost hold. One host only: whether another host's lock on a
        shared file system is seen depends on that file system."""
        fd = os.open(self.dir / "journal.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            stat = os.fstat(fd)
            key, held = (stat.st_dev, stat.st_ino), _HELD.__dict__.setdefault("keys", set())
            if key in held:
                yield
                return
            while True:
                try:
                    fcntl.fcntl(fd, fcntl.F_OFD_SETLK, struct.pack(FLOCK, fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0))
                    break
                except OSError as busy:
                    if busy.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                if time.monotonic() >= deadline:
                    raise Taken(self.handle)
                time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))  # the last try at the deadline, not after it
            held.add(key)
            try:
                yield
            finally:
                held.discard(key)
        finally:
            os.close(fd)  # the lock's last descriptor: released

    def _lock_free(self) -> bool:
        """True if no launcher holds the job's lock. The lock is asked about
        (F_OFD_GETLK), never taken: a probe that took it, however briefly,
        would make a launcher locking at that moment believe another launcher
        of this job is alive, and exit without starting (task 1c-repair C2:
        found as an intermittent never-started job under load)."""
        fd = os.open(self.dir / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            answer = fcntl.fcntl(fd, fcntl.F_OFD_GETLK, struct.pack(FLOCK, fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0))
        finally:
            os.close(fd)
        return struct.unpack(FLOCK, answer)[0] == fcntl.F_UNLCK

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
        view = {"identity": identity, "exit": None, "members": []}
        spawn = self.read("spawn.json")
        if identity is None and (spawn is None or spawn["failed"] >= spawn["attempts"]):  # no start tried, or every one refused by the OS
            return {**view, "verdict": "not_started"}
        if identity is None:
            return {**view, "verdict": "unstarted" if self._lock_free() else "starting"}
        stat = proc_stat(identity["pid"]) if identity["boot_id"] in (boot_id(),) else None
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
