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

from gen2.core import canonical, instants

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
CONTAINED = "contained.json"  # a job whose step failed on its own saved state (Supervisor._contain): {reason, step}, both from the fixed sets below
CONTAINED_REASONS = ("consumed_type", "consumed_key", "consumed_index", "consumed_value", "canonical")  # the class of the failure, never its text
CONTAINED_STEPS = ("recover", "settle")
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


def _any(v: object) -> bool:
    return True


def _opt(check):
    return lambda v: v is None or check(v)


def _list(check):
    return lambda v: isinstance(v, list) and all(check(x) for x in v)


def _text(v: object) -> bool:
    return isinstance(v, str) and bool(v)


def _canonical(v: object) -> bool:
    try:
        canonical.canonical_bytes(v)
    except canonical.CanonicalizationError:
        return False
    return True


def _clean(v: object) -> bool:
    """A text that also serializes canonically (a lone surrogate does not): the method and topic go into the execution record."""
    return _text(v) and _canonical(v)


_instant = instants.is_utc_instant


def _id(v: object) -> bool:
    return isinstance(v, str) and bool(INVOCATION_ID.fullmatch(v))


def _fields(doc: object, table: dict) -> bool:
    """A mapping whose every table entry (required?, validator) holds: required fields present, a present value valid (null included)."""
    return isinstance(doc, dict) and all((name in doc if required else True) and (name not in doc or check(doc[name]))
                                         for name, (required, check) in table.items())


def _of(table: dict):
    return lambda v: _fields(v, table)


# THE contract of the two files consumers read: field -> (must be present, validator of a present value). Absence of an optional
# field keeps the consumer's default (a fresh journal); a present value that fails its validator, null included, is CORRUPT, never
# normalized. A validator guarantees the OPERATION a consumer performs on the value (supervisor.py, driver.py, compose.py, authority.py,
# operator/status.py), reached through aliases and copies too (`_retain` copies observing into collected), GIVEN the journal's own
# values alone: what only external state decides (the router's cancellation, the clock, the configured windows, an unavailable store) is
# not checked here, and a step that still fails on a persisted value is contained per job (Supervisor._contain), never trusted to pass:
#   subscript ["k"]  the mapping carries k, of the type the next operation needs: incident.since, recovering.{incident,requested_by},
#                    observation.{descendants.handling,findings,output}, result.{content_hash,size_bytes}, record/evidence[].content_hash,
#                    grant.{...,lease.{lease_id,generation}}, pending.{purpose,record,method,observation,resolution,identity,digest}
#   [0]              observation.findings[0] is sent as the failure_class of a failed end and of a confirmed_failed/terminated_group
#                    reconcile: a failed end and confirmed_failed carry a finding (a cancellation's observation legitimately carries none)
#   update/** spread incident, exhausted, last_refusal, recoveries[], observing, observation, output, pending.identity are mappings
#                    (identity: exactly the process identity `_process` writes, so it cannot overwrite a request key)
#   iteration        recoveries, findings, evidence are lists of the element shape read
#   instant parsing  unresolved.since, outage.since and the order's deadline_at go through core.instants (`_instant`)
#   arithmetic       budgets values and revision are counts; the dispatch/recorded/unlaunched flags are booleans
#   serialization    an execution record is staged canonically from the order's topic, the method and the observation (`_clean`, `_observation`)
#   result None      a kept or collected end may lack a result only where findings or a cancellation termination explain it (what _terminate
#                    writes: a timeout carries its finding), since the consumers index result.content_hash otherwise (`_explained`);
#                    _collect's partial observing (descendants, termination) is separate
PROCESS_KEYS = frozenset({"host_id", "container_id", "boot_id", "start_fingerprint"})  # what Supervisor._process writes
INCIDENT = {"since": (True, _text), "last_refusal": (False, _opt(_of({"reason": (True, _any)})))}
HANDLING = _of({"handling": (True, _text)})
REF = {"content_hash": (True, _text)}
OBSERVATION = {"descendants": (True, HANDLING), "termination": (True, _opt(_obj)), "findings": (True, _list(_text)), "output": (True, _obj)}
OBSERVING_PARTIAL = {"descendants": (True, HANDLING), "termination": (True, _opt(_obj))}
RECONCILE = {"resolution": (True, _text), "identity": (True, _opt(lambda v: _obj(v) and v.keys() == PROCESS_KEYS)), "digest": (True, _opt(_text))}


def _cancelled(observation: dict) -> bool:
    return (observation["termination"] or {}).get("reason") == "cancellation"


def _observation(v: object) -> bool:
    return _fields(v, OBSERVATION) and _canonical(v)


def _explained(table: dict):
    """A kept or collected end: a result may be absent only where findings or a cancellation explain it (consumers index result otherwise)."""
    return lambda v: _fields(v, table) and (v["result"] is not None or bool(v["observation"]["findings"])
                                            or (v.get("terminated") == "cancellation" and _cancelled(v["observation"])))


OBSERVING_KEPT = {"observation": (True, _observation), "method": (True, _clean), "result": (True, _opt(_of({**REF, "size_bytes": (True, _count)}))),
                  "evidence": (False, _list(_of(REF))), "terminated": (False, _text)}
COLLECTED = {**{k: v for k, v in OBSERVING_KEPT.items() if k != "method"}, "record": (True, _of(REF)), "rehandled": (False, _of({"descendants": (True, HANDLING)}))}
PENDING = {"purpose": (True, _text), "record": (True, _opt(_of(REF))), "method": (True, _clean), "observation": (True, _observation)}


def _pending(v: object) -> bool:
    """A failed end and a confirmed_failed reconcile send observation.findings[0]; a reconcile also carries its resolution, identity, digest."""
    if not _fields(v, PENDING) or (v["purpose"].startswith("reconcile:") and not _fields(v, RECONCILE)):
        return False
    resolution, observation = v.get("resolution"), v["observation"]
    if resolution == "terminated_group":  # without a finding only a cancellation (which _reconcile sends without one if the router agrees)
        return bool(observation["findings"]) or _cancelled(observation)
    return bool(observation["findings"]) or not (v["purpose"] == "end:failed" or resolution == "confirmed_failed")


JOURNAL_FIELDS = {
    "incident": (False, _opt(_of(INCIDENT))), "exhausted": (False, _of(INCIDENT)),
    "collected": (False, _explained(COLLECTED)), "pending": (False, _pending),
    "observing": (False, lambda v: _explained(OBSERVING_KEPT)(v) if _obj(v) and "observation" in v else _fields(v, OBSERVING_PARTIAL)),
    "recovering": (False, _of({"incident": (True, _of(INCIDENT)), "requested_by": (True, _any)})),
    "recoveries": (False, _list(_of({"incident": (True, _of(INCIDENT)), "outcome": (True, _any)}))),
    "grant": (False, _of({k: (True, _any) for k in ("capability_id", "invocation_id", "topic_id", "admission", "config_bundle_hash")}
                          | {"lease": (True, _of({"lease_id": (True, _any), "generation": (True, _any)}))})),
    "dispatch": (False, _of({"admission_ref": (True, _any), "run_id": (True, _any), "attempt": (True, _any), "recorded": (False, lambda v: isinstance(v, bool))})),
    "unresolved": (False, _of({"episode": (True, _any), "since": (True, _instant)})), "outage": (False, _of({"since": (True, _instant)})),
    "budgets": (False, lambda v: _obj(v) and all(_count(n) for n in v.values())),  # an object of retry counters, each incremented by _spend
    "revision": (False, _count), "settled": (False, _opt(_text)), "unlaunched": (False, lambda v: isinstance(v, bool)),
    "recorded": (False, lambda v: isinstance(v, bool)),
    **{k: (False, _obj) for k in ("write_failure", "refusal", "record_failure", "envelope", "spawn_refused", "refused")},
}
ORDER_FIELDS = {
    "invocation_id": (True, _id), "topic_id": (True, _clean), "kind": (True, _text), "config_bundle_hash": (True, _text),
    "deadline_at": (True, _instant), "lease_expires_at": (True, _opt(_text)), "requested_by_invocation_id": (True, _opt(_text)),
    "parent_invocation_id": (False, _opt(_id)), "retry_of": (False, _opt(_text)), "reservation": (False, _opt(_obj)),
    "env": (False, lambda v: _obj(v) and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items())),
    "live": (False, lambda v: isinstance(v, bool)), "plan": (False, _obj),
}


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
        name = path.name
        if not path.is_dir():
            found.append(Entry(name, CORRUPT, reason="not a job directory"))
            continue
        if (path / CONTAINED).exists():  # a contained failure stays blocking across restarts; the operator clears it (delete the file), never a step
            found.append(Entry(name, CORRUPT, reason=_contained_reason(path / CONTAINED)))
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


def _contained_reason(path: Path) -> str:
    """The marker's fixed reason class and step; anything else it holds (or an unreadable marker) reads as 'unreadable', never echoed."""
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        if marker["reason"] in CONTAINED_REASONS and marker["step"] in CONTAINED_STEPS:
            return f"contained: {marker['reason']} in {marker['step']}"
    except (ValueError, OSError, KeyError, TypeError):
        pass
    return "contained: unreadable marker"


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

    def contain(self, failure: Exception, step: str) -> str:
        """Save that `step` failed on this job's state, as the failure's fixed class (never its text); the class is returned."""
        reason = ("canonical" if isinstance(failure, canonical.CanonicalizationError) else
                  {TypeError: "consumed_type", KeyError: "consumed_key", IndexError: "consumed_index"}.get(type(failure), "consumed_value"))
        self.write(CONTAINED, {"reason": reason, "step": step})
        return reason

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
