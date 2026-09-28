"""The station supervisor: the one lifecycle implementation for every
invocation kind — research pass, discovery, delegate, verification and
checkpoint (task 1c). Nothing below branches on the kind except the claim
request a delegate makes under its parent (L-8).

Trace: BOUNDARIES.md Station supervisor (owns launch intent before spawn,
process identity, deadlines, cancellation, descendant handling, result
retention and durable delivery; must never trust agent self-reported
completion, let an agent write authoritative state or the spool destination,
or treat outcome_unknown as anything without reconciliation); design review
§5 ("Artifacts and the sole-writer promise", "Router outage", "Crash
fencing"), §6; INVARIANTS L-1..L-9, C-8, C-9, C-10, RG-2, RG-3;
gen2/core/control.py (the only way it reaches the router: it imports neither
router nor store, gen2/boundaries.toml).

One job per invocation, under its stable handle "job-<invocation id>"
(jobs.py). What the supervisor knows lives in three places, each durable:
the job directory (the order, what the launcher recorded, the journal of
what the supervisor observed, retained and sent), the spool (the result and
every execution record, content-addressed), and the router (the
authoritative lifecycle). advance() rebuilds its view from all three every
time, so a supervisor that restarts (recover()) continues each job from its
handle: nothing it needs is only in memory.

Each advance first observes the job locally, needing no router (C-10): an
exit is collected (descendants handled, the output checked structurally and
staged, the execution record written); a job past its deadline has its
execution group terminated. Then it drives the router one step along L-1:
  admitted          launch intent first (the router's final launch-admission
                    check, L-2, L-7); a refusal for a paused topic is retried
                    within the launch budget, then the admitted work is
                    cancelled (supervisor); a lapsed lease or deadline cancels it
  launching         start the launcher (spawn budget); record its identity
                    once it has recorded it (L-3). A start this process did
                    not see through — a crash between spawn and identity —
                    enters outcome_unknown and is reconciled (L-4)
  running           a collected end is delivered: a structural finding is a
                    failure with its class and record (L-5, L-9); a clean end
                    stages result_ready; a cancellation request terminates
                    the group, then records cancelled once descendants are
                    confirmed (L-7); a launcher gone without an exit record
                    is outcome_unknown
  result_ready      commit_outcome with the retained result and its execution
                    record; a stale state revision is re-sent within the
                    commit budget; any other refusal is a failure
                    (result_rejected), the result staying retained (C-10)
  outcome_unknown   look the job up by its handle, or terminate its group,
                    and reconcile the episode with the resolution the record
                    supports; what cannot be established stays unknown under
                    the episode's hold (owner, deadline)
Every retry path draws on a declared budget kept in the journal, so a
restart does not refill it (L-6): an outage (attempts and time, from its first
failed call until a write the router answers — a read refunds nothing), a
failing durable write, a lifecycle write the router refused (an end, a
reconciliation, entering outcome_unknown, a cancellation — until that write
is accepted; a refusal no retry can change, such as a conflict, stops at
once), an outcome_unknown episode that cannot be reconciled yet (attempts,
and time from its first unresolved look, per episode), recover()
resumptions, launch refusals, launcher starts and commit re-sends. Past the
router, write, refusal or unknown budget the job stalls with an owned,
deadlined incident naming the budget and what it last met, which only
recover() — itself budgeted, and refilling nothing — closes. An unresolved
episode keeps its hold, since only its reconciliation clears it (L-4). An
exhausted launch, spawn or commit budget is recorded as an incident beside
the job's end; a journal that cannot be written raises ControlFailure out of
band (RG-3).
Every router call goes through one chokepoint, _call(), which makes none for
a job stalled on an open incident or settled — as that job's own durable
journal says, whoever asks: its own advance, its parent ending it, its
delegate needing its capability, a recover() with no recovery attempt left.
So a stalled job's spent budget stays spent until recover() closes its
incident, and a settled job is never claimed again. An open incident is
write-once: nothing renews its kind, since or deadline (L-6, RG-3; Astra 1c
re-review 2, L-6).
One caller at a time per job (task 1c-repair-4; Astra 1c re-review 3,
BLOCK 1): advance() and each job's step of recover() hold the job's lock
(jobs.Job.hold) from the read of its journal to its last write; a
delegate's advance takes its parent's lock first, as its grant claims the
parent's; a parent ending its delegates takes each one's under its own. One
order for every caller, parent before delegate, so no two wait on each
other. So no caller reads a journal another is changing, nor writes an older
copy over a newer one, and what is said here of budgets and incidents holds
for overlapping callers — threads sharing a supervisor, supervisors sharing
the jobs directory — as for sequential ones. Waiting for a lock spends no
budget and is bounded (Policy.lock_wait_s; then "busy"). A write resting on
an older copy of the journal is refused (StaleJournal, out of band): a
backstop, not a lock. The lock is per job, across the processes and threads
of one host; nothing is claimed across hosts.
Each advance is one step, and run() is bounded by its timeout. A parent
waiting on its delegates retries nothing of its own: each advance reads its
status and advances each delegate, whose own budgets apply, so a stalled
delegate holds its parent at that delegate's incident. Before a parent's
capacity is released its delegate jobs are ended (L-7, L-8).

Structural limits: faults are what these processes can do to each other on
one host (kills, exits, hangs, lost replies), not power loss or disk
corruption; fencing protects commits and does not undo an orphan's external
effects (L-7); a descendant that leaves the job's session is not seen, and a
listed pid can be reused before it is signalled (jobs.py); supervisors on
different hosts sharing a jobs directory are not known to be excluded by the
job's lock (it may not be seen there; then only the StaleJournal backstop
stands between them, and it does not stop a call). The supervisor trusts its own observations: the router binds
the execution record to what it supports, not to whether it is true. The
README states what is proven.
"""
from __future__ import annotations

import contextlib
import hashlib
import re
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical, instants
from gen2.core.control import ControlUnavailable
from gen2.supervisor import jobs
from gen2.supervisor.spool import Spool, SpoolFull, read_scratch

OUTPUT = "outcome.json"          # the executor's one result file; its name is the supervisor's (C-9)
SELF_REPORT = "status.json"      # an agent's own claim about itself: recorded, never used (L-5)
DECLARED_DIGEST = "declared-digest"
LAUNCHER = (sys.executable, str(Path(__file__).with_name("jobshim.py")))
TERMINAL = ("committed", "failed", "cancelled")
# Refusals of a lifecycle write that no retry can change: another fact is already recorded under the write-once key,
# or the router does not know this capability for this invocation. They stop at once rather than spend the budget.
FINAL_REFUSALS = frozenset({"transition_conflict", "reconciliation_conflict", "cancel_conflict",
                            "unknown_invocation", "capability_invalid", "capability_invocation_mismatch"})
DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Policy:
    """Execution policy (G-10): the shipped defaults, which a config bundle's
    supervisor section overrides value by value (supervisor_policy). Every
    retry path draws on one of these (L-6)."""
    router_attempts: int = 5       # sends while the router is unreachable, per outage (until a write it answers)
    router_window_s: float = 600.0 # how long an outage may last before the job stalls, whatever attempts remain
    recovery_attempts: int = 3     # recover() resumptions of a job stalled on an incident
    write_attempts: int = 3        # advances a failing durable write (a record, a result, the spool) is retried on
    incident_window_s: float = 3600.0  # an incident's deadline: how long its owner has to act on it
    launch_attempts: int = 3       # launch-admission refusals (a paused topic) before the admitted work is cancelled
    spawn_attempts: int = 2        # launcher starts that fail before the job fails as spawn_failed
    commit_attempts: int = 3       # sends of a result whose expected state revision went stale
    refusal_attempts: int = 3      # sends of a lifecycle write the router refused (an end, a reconciliation, entering outcome_unknown, a cancellation)
    unknown_attempts: int = 5      # looks at an outcome_unknown episode that cannot be reconciled yet
    unknown_window_s: float = 600.0  # how long such an episode may stay unresolved, from its first unresolved look
    lock_wait_s: float = 30.0      # how long an advance waits for another caller holding its job's lock before answering "busy"
    identity_grace_s: float = 5.0  # how long a launcher this process started may take to record its identity
    start_grace_s: float = 5.0     # how long a start found after a restart may take to show itself before it is abandoned
    term_grace_s: float = 2.0      # SIGTERM -> SIGKILL
    kill_grace_s: float = 2.0      # SIGKILL -> the group confirmed empty, or not
    poll_s: float = 0.02


def supervisor_policy(bundle: Mapping) -> Policy:
    """A config-bundle/1 document's supervisor policy: the values it names over
    the shipped defaults (G-10). The router validated the bundle when it was
    activated (gen2/schema/config-bundle.schema.json)."""
    return replace(Policy(), **bundle["policy"].get("supervisor", {}))


@dataclass(frozen=True)
class WorkOrder:
    """One invocation for this supervisor to run. The invocation id is the
    stable job identity: the claim, every lifecycle fact and every reconnect
    use it (L-8)."""
    invocation_id: str
    kind: str
    topic_id: str
    config_bundle_hash: str
    deadline_at: str
    command: tuple[str, ...]
    lease_expires_at: str | None = None
    parent_invocation_id: str | None = None      # a delegate: its parent, another job of this supervisor
    requested_by_invocation_id: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)


class Waiting(Exception):
    """This advance cannot proceed now; the job keeps everything it holds."""


class Busy(Waiting):
    """The job's lock, or its parent's (taken first), stayed another's for the
    whole wait (lock_wait_s): nothing read, sent or written, no budget spent.
    (A delegate's lock inside its parent's step is held by no one else then:
    every holder takes the parent's first.) The next advance tries again."""

    def __init__(self, handle: str) -> None:
        super().__init__("busy")
        self.handle = handle


class Held(Waiting):
    """The chokepoint made no router call (Supervisor._call): the job the
    request is for is stalled on an open incident ("stalled"), or settled
    (`settled`: its end). Nothing was written."""

    def __init__(self, handle: str, settled: str | None) -> None:
        super().__init__("stalled" if settled is None else settled)
        self.handle, self.settled = handle, settled


class ControlFailure(Exception):
    """Out of band (RG-3: failed incident persistence is a control failure):
    a durable write failed and the job's own record of it — its journal,
    where its incident lives — could not be written either. Raised to the
    caller of advance()/recover(); nothing changed beyond what was already
    durable. `outcomes`: recover()'s outcome for every job it tried."""

    def __init__(self, message: str, outcomes: dict | None = None) -> None:
        super().__init__(message)
        self.outcomes = outcomes or {}


class StaleJournal(ControlFailure):
    """A journal write rested on a copy older than the durable journal: some
    writer changed it after that copy was read. Refused, nothing written
    (the backstop behind the job's lock, Supervisor._save)."""


class Supervisor:
    def __init__(self, control, spool: Spool, jobs_root: str | Path, *, station_id: str, host_id: str, container_id: str | None = None,
                 policy: Policy = Policy(), policies: Callable[[str], Policy] | None = None, clock: Callable[[], str],
                 launcher: tuple[str, ...] = LAUNCHER, fault: Callable[[str], None] | None = None) -> None:
        self.control = control
        self.spool = spool
        self.jobs_root = Path(jobs_root)
        self.jobs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.station_id, self.host_id, self.container_id = station_id, host_id, container_id
        self.policy = policy  # the station's own (lock wait, polling), and every job's without `policies`
        self._policies = policies  # a config bundle's hash -> its Policy (the composition root's); None: every job has `policy`
        self._pinned: dict[str, Policy] = {}
        self._clock = clock
        self.launcher = tuple(launcher)
        self._fault = fault or (lambda point: None)
        self._children: dict[str, object] = {}  # launchers this process started: reaped here, and trusted to be this session's own start

    # -- public ----------------------------------------------------------------
    def job(self, invocation_id: str) -> jobs.Job:
        return jobs.Job(self.jobs_root, "job-" + invocation_id)

    def prepare(self, order: WorkOrder) -> None:
        """Make the order durable under its job handle (the claim is sent from
        the stored order, so a restart re-sends the same claim, L-8). An order
        pins a recorded config bundle: one the resolver does not know raises
        before anything is written."""
        if self._policies is not None:
            self._policies(order.config_bundle_hash)
        self.job(order.invocation_id).prepare({**asdict(order), "command": list(order.command), "env": dict(order.env)})

    def submit(self, order: WorkOrder) -> str:
        self.prepare(order)
        return self.advance(order.invocation_id)

    def recover(self) -> dict[str, str]:
        """After a restart, or once the router is back: every job this
        supervisor holds, advanced from what its handle finds. A job stalled
        on an incident resumes here, drawing on its recovery budget: that
        closes its incident, the only way its calls pass the chokepoint again
        (_call). The budget that ran out stays spent (an outage or a failing
        write is exhausted until that operation makes progress), so a
        resumption that fails again stalls again at once (L-6; Astra 1c
        review A5). With no recovery attempt left the incident stays open as
        raised, and the job's calls stay refused. Each job's resumption and
        its advance are one hold of its lock (_exclusive): a job whose lock
        another caller keeps past the wait is reported busy, its recovery
        budget untouched. A job whose journal cannot be written is reported
        as control_failure, and once every job was tried ControlFailure is
        raised naming them."""
        outcomes, failures = {}, []
        for path in sorted(self.jobs_root.iterdir()):
            order = jobs.Job(self.jobs_root, path.name).read("order.json")
            if order is None:
                continue
            job = self.job(order["invocation_id"])
            try:
                with self._exclusive(order):
                    journal = self._journal(job)  # read under the lock, as advance() reads it
                    if journal.get("incident") and not journal.get("settled") and self._spend(job, journal, "recovery"):
                        journal["incident"] = None
                        self._save(job, journal)
                    outcomes[order["invocation_id"]] = self.advance(order["invocation_id"])
            except Busy as busy:
                outcomes[order["invocation_id"]] = str(busy)
            except (ControlFailure, OSError) as failure:
                outcomes[order["invocation_id"]] = "control_failure"
                failures.append(f"{job.handle}: {failure}")
        if failures:
            raise ControlFailure("; ".join(failures), outcomes)
        return outcomes

    def incidents(self) -> list[dict]:
        """Every open control incident of this supervisor's jobs (RG-3:
        visible, owned, deadlined): the one a stalled job waits on
        (blocking), and each exhausted retry budget (kept beside the job's
        end, which it does not block). Read from the journals; changes
        nothing."""
        found = []
        for path in sorted(self.jobs_root.iterdir()):
            job = jobs.Job(self.jobs_root, path.name)
            order, journal = job.read("order.json"), job.read("journal.json") or {}
            for key in ("incident", "exhausted"):
                if order is not None and journal.get(key):
                    found.append({"invocation_id": order["invocation_id"], "blocking": key == "incident", **journal[key]})
        return found

    def run(self, invocation_id: str, *, timeout_s: float = 60.0, until: tuple[str, ...] = TERMINAL + ("not_admitted",)) -> str:
        """Advance until an outcome in `until`, or `timeout_s` of wall time."""
        deadline = time.monotonic() + timeout_s
        while True:
            outcome = self.advance(invocation_id)
            if outcome in until or time.monotonic() >= deadline:
                return outcome
            time.sleep(self.policy.poll_s)

    def advance(self, invocation_id: str) -> str:
        """One step of the job, holding its lock — a delegate's parent's
        first (_exclusive) — from the read of its journal to its last write,
        so no other caller reads that journal meanwhile or writes over it:
        another thread, or another supervisor sharing the jobs directory on
        this host (L-6, RG-3; Astra 1c re-review 3, BLOCK 1). Waiting for the
        lock spends nothing and is bounded (Busy: "busy")."""
        job = self.job(invocation_id)
        order = job.read("order.json")
        if order is None:
            raise KeyError(f"no job for {invocation_id}")
        try:
            with self._exclusive(order):
                journal = self._journal(job)  # read under the lock: every write of this advance rests on it (_save)
                return self._advance(job, order, journal)
        except Busy as busy:
            return str(busy)

    def _advance(self, job: jobs.Job, order: dict, journal: dict) -> str:
        if journal.get("settled"):
            return journal["settled"]
        try:
            self._observe(job, order, journal)  # local: a stalled job's deadline is still enforced (C-10)
            return self._drive(job, order, journal)  # a stalled job's first router call is refused at the chokepoint: "stalled"
        except Waiting as waiting:
            return str(waiting)
        except (SpoolFull, OSError) as failure:  # a durable write failed: an infrastructure failure, never a completion (C-10)
            return self._write_failed(job, failure)

    # -- the job's lock -------------------------------------------------------
    def _lineage(self, order: dict) -> list[jobs.Job]:
        """The job and its ancestors, root first: a delegate's parent, then
        the delegate (L-8 allows no deeper chain; one would be followed)."""
        lineage, seen, parent = [self.job(order["invocation_id"])], {order["invocation_id"]}, order.get("parent_invocation_id")
        while parent is not None and parent not in seen:
            ancestor = self.job(parent)
            ancestor_order = ancestor.read("order.json")
            if ancestor_order is None:
                break
            lineage.insert(0, ancestor)
            seen.add(parent)
            parent = ancestor_order.get("parent_invocation_id")
        return lineage

    @contextlib.contextmanager
    def _exclusive(self, order: dict):
        """Hold the lock of every job whose journal a step of this one may
        read and write (jobs.Job.hold): its parent's — a delegate's grant
        claims its parent's — then its own. A parent ending its delegates
        acts on their journals holding its own lock first. So every caller
        takes them in one order, parent before delegate, and no two wait on
        each other. One deadline (Policy.lock_wait_s) bounds the whole wait:
        past it, Busy: no journal read or written, no budget spent. A
        caller that holds one already (a parent advancing its delegate)
        holds it again at once. Per job, across the processes and threads of
        one host; nothing is claimed across hosts (jobs.py)."""
        deadline = time.monotonic() + self.policy.lock_wait_s
        with contextlib.ExitStack() as held:
            for job in self._lineage(order):
                try:
                    held.enter_context(job.hold(deadline, self.policy.poll_s))
                except jobs.Taken:
                    raise Busy(job.handle) from None
                except OSError as failure:
                    raise ControlFailure(f"{job.handle}: its lock cannot be taken ({type(failure).__name__}: {failure})") from failure
            yield

    # -- journal and budgets ---------------------------------------------------
    def _policy(self, job: jobs.Job) -> Policy:
        """The job's policy: that of the config bundle its order is pinned to,
        the one it was admitted under, whatever bundle is active now — resolved
        once, and again the same way after a restart (G-10, RG-9)."""
        if self._policies is None:
            return self.policy
        if job.handle not in self._pinned:
            self._pinned[job.handle] = self._policies(job.read("order.json")["config_bundle_hash"])
        return self._pinned[job.handle]

    def _journal(self, job: jobs.Job) -> dict:
        journal = job.read("journal.json") or {}
        journal.setdefault("budgets", {})
        return journal

    def _save(self, job: jobs.Job, journal: dict) -> None:
        """Write the job's journal one revision on from the copy it rests on.
        Under the job's lock that copy is the durable journal; a copy that is
        not — read before another writer changed it — is refused
        (StaleJournal) and nothing is written, so no write puts older state
        over newer. The check and the write are two steps: a backstop behind
        the lock, not a lock."""
        revision, durable = journal.get("revision", 0), (job.read("journal.json") or {}).get("revision", 0)
        if durable != revision:
            raise StaleJournal(f"{job.handle}: this write rests on journal revision {revision}; the journal is at {durable}")
        job.write("journal.json", {**journal, "revision": revision + 1})
        journal["revision"] = revision + 1

    def _spend(self, job: jobs.Job, journal: dict, path: str) -> bool:
        """Draw one attempt from this job's budget for `path`; False once it is
        spent. Recorded before the attempt, so a crash does not refund it."""
        used = journal["budgets"].get(path, 0)
        if used >= getattr(self._policy(job), f"{path}_attempts"):
            return False
        journal["budgets"][path] = used + 1
        self._save(job, journal)
        return True

    def _settle(self, job: jobs.Job, journal: dict, state: str) -> str:
        journal["settled"] = state
        self._save(job, journal)
        return state

    def _incident(self, job: jobs.Job, journal: dict, kind: str, key: str = "incident", **facts) -> None:
        """An owned, deadlined control incident (RG-3), kept in the job's
        journal: "incident" is the one a stalled job waits on until recover();
        "exhausted" records a retry budget that ran out, beside the job's end.
        Write-once while open: one already raised in the job's durable journal
        — whatever copy the caller holds — is kept as it was, kind, since and
        deadline included, and nothing is written; only recover() closes an
        incident (L-6, RG-3; Astra 1c re-review 2, L-6)."""
        raised = (job.read("journal.json") or {}).get(key)
        if raised:
            journal[key] = raised
            return
        journal[key] = {"kind": kind, "since": self._now(), "owner": f"supervisor:{self.station_id}",
                        "deadline_at": self._after(self._policy(job).incident_window_s), **facts}
        self._save(job, journal)

    def _exhausted(self, job: jobs.Job, journal: dict, budget: str, last_refusal: dict | None, result_ref: dict | None) -> None:
        """A retry budget ran out (RG-3; Astra 1c review A11): which budget,
        the last refusal and the result it concerns, owned and deadlined —
        recorded before the job's end, once (the first stays: _incident)."""
        self._incident(job, journal, "retry_exhausted", key="exhausted", budget=budget, last_refusal=last_refusal, result_ref=result_ref)

    def _write_failed(self, job: jobs.Job, failure: Exception) -> str:
        """A durable write failed — the spool full or refusing, a file-system
        error. What was durable before it stands (an observation kept in the
        journal is never made again), and the write is retried on later
        advances within the write budget; exhausted, the job stalls with an
        owned, deadlined incident until recover() (C-10, RG-3; Astra 1c
        review A4) — or, stalled on another incident already (a record of a
        termination made while the router was away, say), keeps that one as
        raised and waits with it (_observe). When the journal itself cannot
        be written the incident cannot be kept either: ControlFailure, out of
        band."""
        error = f"{type(failure).__name__}: {failure}"[:500]
        try:
            journal = self._journal(job)  # what is durable: the failed operation's unsaved changes are dropped
            if self._spend(job, journal, "write"):
                journal["write_failure"] = {"at": self._now(), "error": error}
                self._save(job, journal)
                return "write_failed"
            self._incident(job, journal, "durable_write_failed", phase="delivery" if journal.get("collected") or journal.get("pending") else "collection",
                           error=error)
            return "stalled"
        except OSError as unwritable:
            raise ControlFailure(f"{job.handle}: a durable write failed ({error}) and its incident cannot be written "
                                 f"({type(unwritable).__name__}: {unwritable})") from failure

    @staticmethod
    def _wrote(journal: dict) -> None:
        """The failing write made progress: its budget is spent no longer (saved by the caller)."""
        journal["budgets"].pop("write", None)
        journal.pop("write_failure", None)

    def _refused(self, job: jobs.Job, journal: dict, write: str, response: dict):
        """The router answered a lifecycle write — an end, a reconciliation,
        entering outcome_unknown, a cancellation — with a refusal. It is
        decided and sent afresh on a later advance within the refusal budget,
        which only that write's acceptance refunds; a refusal no retry can
        change (FINAL_REFUSALS) stops at once. Past either, the job stalls
        with an owned, deadlined incident naming the budget, the write and the
        last refusal, which only recover() resumes, refilling nothing (L-6,
        RG-3)."""
        refusal = {"reason": response.get("reason"), "detail": response.get("detail")}
        final = refusal["reason"] in FINAL_REFUSALS
        journal["refusal"] = {"write": write, **refusal}
        if final or not self._spend(job, journal, "refusal"):
            self._incident(job, journal, "lifecycle_write_refused", budget="refusal", write=write, last_refusal=refusal, final=final)
            raise Waiting("stalled")
        raise Waiting(f"{write}_refused:{refusal['reason']}")

    def _accepted(self, job: jobs.Job, journal: dict, write: str) -> None:
        """The router accepted a lifecycle write: if it is the one last
        refused, the refusal budget it spent is spent no longer."""
        if (journal.get("refusal") or {}).get("write") == write:
            del journal["refusal"]
            journal["budgets"].pop("refusal", None)
            self._save(job, journal)

    def _unresolved(self, job: jobs.Job, journal: dict, status: dict, finding: str):
        """The current outcome_unknown episode cannot be reconciled yet: it is
        looked at again on a later advance within the unknown budget —
        attempts, and time from its first unresolved look — kept per episode.
        Past either, the job stalls with an owned, deadlined incident naming
        the episode and what was last found, which only recover() resumes,
        refilling nothing; nothing is reconciled, so the episode's hold stays
        with the router (L-4, L-6, RG-3)."""
        episode = status["unknown_episode"]
        tried = journal.get("unresolved")
        if tried is None or tried["episode"] != episode:
            tried = journal["unresolved"] = {"episode": episode, "since": self._now()}
            journal["budgets"].pop("unknown", None)
            self._save(job, journal)
        tried["finding"] = finding
        if not self._spend(job, journal, "unknown") or self._past(self._after(self._policy(job).unknown_window_s, tried["since"])):
            self._incident(job, journal, "outcome_unknown_unresolved", budget="unknown", unknown_episode=episode,
                           unresolved_since=tried["since"], last_finding=finding)
            raise Waiting("stalled")
        raise Waiting("unknown_unresolved")

    READS = frozenset({"invocation_status"})

    def _call(self, job: jobs.Job, journal: dict, method: str, request: dict) -> dict:
        """One router call: the chokepoint every control call goes through.
        None is made for a job stalled on an open incident, or settled — the
        job the request is for, as its own durable journal says, whatever
        job or journal copy the caller holds — whoever calls: its advance,
        its parent ending it, its delegate needing its capability, recover()
        with no recovery attempt left. Held is raised and nothing is written:
        the incident stays as raised, its budget spent, until recover() closes
        it; a settled job is never sent anything again (L-6, RG-3; Astra 1c
        re-review 2, L-6).
        Unreachable: the same request is sent again on a later advance. An
        outage is budgeted from its first failed call until a write the
        router answers — a successful read refunds nothing (Astra 1c review
        A5) — by attempts and by time; past either, the job stalls with an
        owned, deadlined incident until recover(), which does not refill it
        (C-10, L-6)."""
        owner = self.job(request["invocation_id"])
        held = owner.read("journal.json") or {}
        if held.get("incident") or held.get("settled"):
            raise Held(owner.handle, held.get("settled"))
        try:
            response = getattr(self.control, method)(request)
        except ControlUnavailable:
            outage = journal.setdefault("outage", {"since": self._now()})
            if not self._spend(job, journal, "router") or self._past(self._after(self._policy(job).router_window_s, outage["since"])):
                self._incident(job, journal, "router_unreachable", method=method, outage_since=outage["since"])
                raise Waiting("stalled") from None
            raise Waiting("router_unavailable") from None
        if method not in self.READS and (journal["budgets"].get("router") or journal.get("outage")):  # the router answered a write: progress
            journal["budgets"]["router"] = 0
            journal.pop("outage", None)
            self._save(job, journal)
        return response

    # -- time ------------------------------------------------------------------
    def _now(self) -> str:
        return self._clock()

    def _past(self, instant: str) -> bool:
        return instants.utc_instant_ns(self._now()) >= instants.utc_instant_ns(instant)

    def _after(self, seconds: float, start: str | None = None) -> str:
        ns = instants.utc_instant_ns(start or self._now()) + int(seconds * 10**9)
        return datetime.fromtimestamp(ns // 10**9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{ns % 10**9 // 1000:06d}Z"

    def _reap(self) -> None:
        for popen in list(self._children.values()):  # a copy: another thread's advance of another job may start one meanwhile
            popen.poll()

    # -- local observation (needs no router) -----------------------------------
    def _observe(self, job: jobs.Job, order: dict, journal: dict) -> None:
        if journal.get("collected"):
            return
        # a write whose budget ran out while the job is stalled (on it, or on another incident): recover() retries it, nothing else does
        stalled_on_a_write = bool(journal.get("incident")) and journal["budgets"].get("write", 0) >= self._policy(job).write_attempts
        if "observation" in journal.get("observing", {}):  # an end already observed, its record not yet staged: never observed again
            return None if stalled_on_a_write else self._retain(job, order, journal)
        if stalled_on_a_write and journal.get("observing"):
            return  # the collection that failed to write waits for recover()
        self._reap()
        view = job.lookup()
        if view["verdict"] == "exited":
            self._collect(job, order, journal, view)
        elif self._past(order["deadline_at"]) and (view["verdict"] == "running" or (view["verdict"] == "vanished" and view["members"])):
            # the deadline is local (C-10): a live group is ended at it whether or not its launcher survives, and whatever the
            # router's state or reachability; the end is retained and reconciled once the router answers (Astra 1c review A9)
            self._terminate(job, order, journal, view, "timeout")

    def _process(self, identity: dict | None) -> dict | None:
        if identity is None:
            return None
        return {"host_id": self.host_id, "container_id": self.container_id, "boot_id": identity["boot_id"], "start_fingerprint": jobs.fingerprint(identity)}

    @staticmethod
    def _agent_text(job: jobs.Job, name: str) -> str | None:
        """A small file the agent may have written, read as data (bounded, no
        symlink, never staged): recorded, never trusted (L-5)."""
        found = read_scratch(job.scratch, name, 4096)
        return found["data"][:500].decode("utf-8", "replace").strip() or None if found["status"] == "present" else None

    def _descendants(self, job: jobs.Job, identity: dict) -> tuple[dict, dict | None]:
        """After the primary ended: wait for the launcher to leave (it has
        recorded the exit), then end whatever else is left of the group and
        confirm it gone (L-7). The launcher is not counted as a descendant."""
        deadline = time.monotonic() + self._policy(job).kill_grace_s
        while identity["pid"] in jobs.members(identity) and time.monotonic() < deadline:
            self._reap()
            time.sleep(0.005)
        left = [pid for pid in jobs.members(identity) if pid != identity["pid"]]
        if not left and identity["pid"] not in jobs.members(identity):
            return {"handling": "none_found", "count": 0}, None
        ended = job.terminate(identity, term_grace=self._policy(job).term_grace_s, kill_grace=self._policy(job).kill_grace_s, reap=self._reap)
        if not left and ended["confirmed"]:  # only a lingering launcher was ended: no descendant
            return {"handling": "none_found", "count": 0}, None
        return self._handled({**ended, "found": len(left)}), {"reason": "descendants_after_exit"}

    @staticmethod
    def _handled(ended: dict) -> dict:
        """The descendants field of an execution record, from a termination."""
        if not ended["confirmed"]:
            return {"handling": "unconfirmed", "count": ended["found"]}
        return {"handling": "terminated", "count": ended["found"]} if ended["found"] else {"handling": "none_found", "count": 0}

    def _collect(self, job: jobs.Job, order: dict, journal: dict, view: dict) -> None:
        """The structural checks: the exit, what is on disk, and the rest of the
        group. The agent's self-report is data; its declared digest is checked
        data that cannot establish success — one the bytes do not have refuses
        the output, one they have adds nothing (L-5).
        What cannot be done twice is kept in the journal before the next step
        — the descendants handled, then the observation with its staged
        result — so a durable write that fails is retried without observing
        again (C-10; Astra 1c review A4)."""
        seen = journal.get("observing") or {}
        if "descendants" not in seen:
            descendants, termination = self._descendants(job, view["identity"])
            seen = journal["observing"] = {"descendants": descendants, "termination": termination}
            self._save(job, journal)
        exit_record, findings = view["exit"], []
        if exit_record["signal"] is not None:
            findings.append("killed")
        elif exit_record["code"] != 0:
            findings.append("exit_nonzero")
        found = self.spool.collect(order["topic_id"], job.scratch, OUTPUT, "application/json")  # a full spool fails the write (advance): the output stays in scratch
        declared = self._agent_text(job, DECLARED_DIGEST)
        output = {"status": found["status"], "content_hash": None, "size_bytes": None,
                  "declared_digest": declared if declared and DIGEST.match(declared) else None, "detail": found["detail"]}
        result = None
        if found["status"] in ("absent", "empty"):
            findings.append("empty_output")
        elif found["status"] == "refused":
            findings.append("output_refused")
        elif declared is not None and declared != found["ref"]["content_hash"]:
            output.update(status="digest_mismatch", detail=f"the executor declared {declared[:80]}; the bytes hash to {found['ref']['content_hash']}")
            findings.append("output_digest_mismatch")
        else:
            output.update(content_hash=found["ref"]["content_hash"], size_bytes=found["ref"]["size_bytes"])
            result = found["ref"] if not findings else None
        observation = {"process": self._process(view["identity"]), "exit": exit_record, "termination": seen["termination"], "descendants": seen["descendants"],
                       "output": output, "self_report": self._agent_text(job, SELF_REPORT), "findings": findings}
        journal["observing"] = {**seen, "observation": observation, "result": result, "method": "exit_observed"}
        self._save(job, journal)
        self._retain(job, order, journal)

    def _terminate(self, job: jobs.Job, order: dict, journal: dict, view: dict, reason: str) -> None:
        """End the execution group (timeout or cancellation) and record it;
        the termination is kept before its record is staged (A4)."""
        ended = job.terminate(view["identity"], term_grace=self._policy(job).term_grace_s, kill_grace=self._policy(job).kill_grace_s, reap=self._reap)
        observation = {"process": self._process(view["identity"]), "exit": job.read("exit.json"), "termination": {"reason": reason},
                       "descendants": self._handled(ended),
                       "output": {"status": "not_collected", "content_hash": None, "size_bytes": None, "declared_digest": None, "detail": None},
                       "self_report": None, "findings": ["timeout"] if reason == "timeout" else []}
        journal["observing"] = {"observation": observation, "result": None, "method": "execution_group_termination", "terminated": reason}
        self._save(job, journal)
        self._retain(job, order, journal)

    def _retain(self, job: jobs.Job, order: dict, journal: dict) -> None:
        """Stage the kept observation's execution record, then keep the end as
        collected: retained until it is delivered (C-10)."""
        seen = journal["observing"]
        record = self._record(order, seen["method"], seen["observation"])
        journal["collected"] = {"observation": seen["observation"], "result": seen["result"], "record": record,
                                **({"terminated": seen["terminated"]} if seen.get("terminated") else {})}
        del journal["observing"]
        self._wrote(journal)
        self._save(job, journal)
        self._fault("terminated" if seen.get("terminated") else "collected")

    def _record(self, order: dict, method: str, observation: dict) -> dict:
        """Stage an execution record (execution-record/1) for this job."""
        doc = {"record_version": "execution-record/1", "invocation_id": order["invocation_id"], "topic_id": order["topic_id"],
               "job_handle": "job-" + order["invocation_id"], "method": method, "observed_at": self._now(), **observation}
        return self.spool.stage(order["topic_id"], canonical.canonical_bytes(doc), "application/json")

    # -- driving the router ------------------------------------------------------
    def _grant(self, job: jobs.Job, order: dict, journal: dict) -> dict:
        if journal.get("grant"):
            return journal["grant"]
        request = {"invocation_id": order["invocation_id"], "kind": order["kind"], "topic_id": order["topic_id"],
                   "config_bundle_hash": order["config_bundle_hash"], "deadline_at": order["deadline_at"]}
        if order["kind"] == "delegate":
            parent = self.job(order["parent_invocation_id"])
            try:  # the parent's grant: kept, or its claim — which its own chokepoint refuses while it is stalled or settled
                request["parent_capability_id"] = self._grant(parent, parent.read("order.json"), self._journal(parent))["capability_id"]
            except Held as held:
                if held.settled is None:  # stalled: it waits for recover(), and the delegate sends nothing meanwhile
                    raise Waiting("parent_stalled") from None
                journal["refused"] = {"reason": "parent_not_admitted",
                                      "detail": f"its parent {order['parent_invocation_id']} ended {held.settled} without a capability"}
                self._settle(job, journal, "not_admitted")
                raise Waiting("not_admitted") from None
        else:
            request.update(station_id=self.station_id, lease_expires_at=order["lease_expires_at"] or order["deadline_at"])
        if order["requested_by_invocation_id"]:
            request["requested_by_invocation_id"] = order["requested_by_invocation_id"]
        grant = self._call(job, journal, "claim", request)
        self._fault("claimed")
        if grant["status"] not in ("granted", "replayed"):
            journal["refused"] = {"reason": grant.get("reason"), "detail": grant.get("detail")}
            self._settle(job, journal, "not_admitted")
            raise Waiting("not_admitted")
        journal["grant"] = grant
        self._save(job, journal)
        return grant

    def _status(self, job: jobs.Job, journal: dict, grant: dict) -> dict:
        return self._call(job, journal, "invocation_status", {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"]})

    def _transition(self, job: jobs.Job, journal: dict, grant: dict, to_state: str, **facts) -> dict:
        return self._call(job, journal, "record_transition", {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                                              "to_state": to_state, **facts})

    def _drive(self, job: jobs.Job, order: dict, journal: dict) -> str:
        grant = self._grant(job, order, journal)
        status = self._status(job, journal, grant)
        state = status["state"]
        if state in TERMINAL:
            return self._settle(job, journal, state)
        step = {"admitted": self._admitted, "launching": self._launching, "running": self._running,
                "result_ready": self._result_ready, "outcome_unknown": self._unknown}[state]
        return step(job, order, journal, grant, status)

    def _settle_delegates(self, order: dict) -> None:
        """A parent's lease is its delegates' too (L-8), and a delegate runs in
        its own supervisor-owned session, which the parent's descendant check
        cannot see. So before anything that releases a parent's capacity (a
        failure, a cancellation, a terminal reconciliation, the final commit)
        every delegate job of it held here is ended — its cancellation
        requested, its group terminated, or its already staged result
        delivered — and the router confirms it ended (L-7; Astra 1c review A3).
        Until then the parent waits; the router refuses the release anyway.
        A delegate stalled on an incident passes the same chokepoint as its
        own advance (_call): its parent makes none of its control calls, so
        its exhausted budget stays spent and its incident (and deadline) stays
        as raised, until recover() resumes it; it is still advanced, so its
        deadline is still observed locally (L-6, C-10; Astra 1c re-review
        A5-R)."""
        if order["kind"] == "delegate":
            return
        pending = []
        for path in sorted(self.jobs_root.iterdir()):
            delegate = jobs.Job(self.jobs_root, path.name)
            dorder = delegate.read("order.json")
            if dorder is None or dorder.get("parent_invocation_id") != order["invocation_id"]:
                continue
            with self._exclusive(dorder):  # its journal, under its own lock: this parent's is held already (parent before delegate)
                djournal = self._journal(delegate)
                if djournal.get("settled"):
                    continue
                try:  # its capability: the grant kept, or replayed (a claim lost in a crash), or a fresh claim, cancelled below at once
                    grant = self._grant(delegate, dorder, djournal)
                    status = self._status(delegate, djournal, grant)
                    if status["state"] not in (*TERMINAL, "result_ready") and status["cancel_requested"] is None:
                        response = self._call(delegate, djournal, "request_cancel", {"invocation_id": grant["invocation_id"], "requested_by": "supervisor",
                                                                                     "reason": f"its parent {order['invocation_id']} has ended",
                                                                                     "capability_id": grant["capability_id"]})
                        if response["status"] not in ("cancelled", "recorded", "replayed"):
                            self._refused(delegate, djournal, "cancel", response)
                        self._accepted(delegate, djournal, "cancel")
                except Waiting:  # a stalled delegate's calls are refused at the chokepoint (Held): nothing is sent
                    pass
                if self.advance(dorder["invocation_id"]) not in (*TERMINAL, "not_admitted"):
                    pending.append(dorder["invocation_id"])
        if pending:
            raise Waiting("delegates_pending")

    def _cancel_self(self, job: jobs.Job, journal: dict, grant: dict, reason: str) -> str:
        """Admitted work this supervisor may not launch is cancelled, by the
        supervisor, under its capability (nothing was spawned, L-2)."""
        response = self._call(job, journal, "request_cancel", {"invocation_id": grant["invocation_id"], "requested_by": "supervisor",
                                                                "reason": reason[:500], "capability_id": grant["capability_id"]})
        if response["status"] not in ("cancelled", "recorded", "replayed"):
            self._refused(job, journal, "cancel", response)
        self._accepted(job, journal, "cancel")
        return self._drive(job, job.read("order.json"), journal)

    def _refused_launch(self, job, journal, grant, reason: str) -> str:
        """The launch-admission check refused: a paused topic is waited for
        within the launch budget, then (or for a lapsed lease) the work is
        cancelled by the supervisor — nothing was started (L-2, L-7)."""
        if reason == "topic_paused":
            if self._spend(job, journal, "launch"):
                raise Waiting("waiting_launch")
            self._exhausted(job, journal, "launch", {"reason": reason}, None)
        return self._cancel_self(job, journal, grant, f"launch refused: {reason}")

    def _admitted(self, job, order, journal, grant, status) -> str:
        response = self._transition(job, journal, grant, "launching", job_handle=job.handle)
        if response["status"] == "refused":
            return self._refused_launch(job, journal, grant, response["reason"])
        self._fault("launch_recorded")
        return self._launching(job, order, journal, grant, self._status(job, journal, grant))

    def _launching(self, job, order, journal, grant, status) -> str:
        view = job.lookup()
        if view["verdict"] == "not_started":  # launch intent is recorded and no start has happened: start it now
            refused = status["launch_admission"]  # the router's current launch-admission check, read before every actual start (L-7)
            if status["cancel_requested"] or self._past(order["deadline_at"]) or (refused and refused["reason"] == "deadline_passed"):
                return self._end_unlaunched(job, order, journal, grant, status)
            if refused is not None:  # recorded launch intent is not renewed authority: a recovery or a retried start is checked again
                return self._refused_launch(job, journal, grant, refused["reason"])
            if not self._spend(job, journal, "spawn"):
                self._exhausted(job, journal, "spawn", journal.get("spawn_refused"), None)
                return self._end(job, order, journal, grant, "failed", self._unrun("spawn_failed", "the launcher could not be started within the spawn budget"),
                                 "job_handle_lookup")
            try:
                self._children[job.handle] = job.spawn(list(self.launcher), before_start=lambda: self._fault("spawning"))
            except OSError as refused:  # the start is recorded as refused (spawn.json): the next advance tries again, on budget
                journal["spawn_refused"] = {"reason": "spawn_refused", "detail": f"{type(refused).__name__}: {refused}"[:500]}
                self._save(job, journal)
                raise Waiting("launching") from None
            self._fault("spawned")
            view = self._await_identity(job, self._policy(job).identity_grace_s)
        if view["identity"] is not None and job.handle in self._children:  # this process started it and saw its identity
            response = self._transition(job, journal, grant, "running", **{k: v for k, v in self._process(view["identity"]).items()})
            if response["status"] in ("recorded", "replayed"):
                self._fault("running_recorded")
                return "running"
        # a start this process did not see through (a crash between spawn and identity record, or a launcher that
        # never recorded one): the outcome is unknown until the job is looked up or its group terminated (L-3, L-4)
        return self._enter_unknown(job, order, journal, grant, status, "spawn_uncertain")

    def _await_identity(self, job: jobs.Job, grace: float) -> dict:
        """Wait, within `grace`, for a launcher to record its identity. Before
        it takes the lock a launcher looks unstarted, so that is final only
        for a launcher this process started and has seen end; a start found
        after a restart is given the grace (jobs.Job.lookup)."""
        deadline = time.monotonic() + grace
        child = self._children.get(job.handle)
        while True:
            self._reap()
            view = job.lookup()
            ended = view["verdict"] == "unstarted" and child is not None and child.returncode is not None
            if view["verdict"] not in ("starting", "unstarted") or ended or time.monotonic() >= deadline:
                return view
            time.sleep(0.005)

    @staticmethod
    def _unrun(finding: str | None, detail: str) -> dict:
        return {"process": None, "exit": None, "termination": None, "descendants": {"handling": "none_found", "count": 0},
                "output": {"status": "not_collected", "content_hash": None, "size_bytes": None, "declared_digest": None, "detail": detail},
                "self_report": None, "findings": [finding] if finding else []}

    def _end_unlaunched(self, job, order, journal, grant, status) -> str:
        """Launch intent recorded, nothing ever started: cancelled if that was
        asked for, otherwise the deadline passed first."""
        if status["cancel_requested"]:
            return self._end(job, order, journal, grant, "cancelled", self._unrun(None, "cancelled before the launcher started"), "job_handle_lookup")
        return self._end(job, order, journal, grant, "failed", self._unrun("never_started", "the deadline passed before the launcher started"), "job_handle_lookup")

    def _pending(self, job: jobs.Job, order: dict, journal: dict, purpose: str, **facts) -> dict:
        """The request an end or a reconciliation sends, fixed once: its facts
        and observation are kept in the journal before its execution record is
        staged, and the staged record with them, so a retry — after a failed
        write or a lost reply — sends the identical request (a changed one
        would be a conflict, not a replay: C-5, L-4; Astra 1c review A4)."""
        pending = journal.get("pending")
        if pending is None or pending["purpose"] != purpose:
            pending = journal["pending"] = {"purpose": purpose, "record": None, **facts}
            self._save(job, journal)
        if pending["record"] is None:
            pending["record"] = self._record(order, pending["method"], pending["observation"])
            self._wrote(journal)
            self._save(job, journal)
        return pending

    def _sent(self, job: jobs.Job, journal: dict, response: dict, write: str) -> None:
        """The pending request answered: kept no longer. A refusal lets the
        next attempt decide afresh, within the refusal budget (_refused)."""
        journal.pop("pending", None)
        self._save(job, journal)
        if response["status"] not in ("recorded", "replayed"):
            self._refused(job, journal, write, response)
        self._accepted(job, journal, write)

    def _end(self, job, order, journal, grant, to_state: str, observation: dict, method: str) -> str:
        self._settle_delegates(order)
        pending = self._pending(job, order, journal, f"end:{to_state}", method=method, observation=observation)
        facts = {"end_evidence_ref": pending["record"]["content_hash"]}
        if to_state == "failed":
            facts["failure_class"] = pending["observation"]["findings"][0]
        self._sent(job, journal, self._transition(job, journal, grant, to_state, **facts), "end")
        return self._settle(job, journal, to_state)

    def _running(self, job, order, journal, grant, status) -> str:
        collected = journal.get("collected")
        if collected is None:
            view = job.lookup()
            if status["cancel_requested"] and view["verdict"] in ("running", "vanished"):
                self._terminate(job, order, journal, view, "cancellation")
                return self._running(job, order, journal, grant, status)
            if view["verdict"] == "vanished":
                return self._enter_unknown(job, order, journal, grant, status, "contact_lost")
            return "running"
        observation = collected["observation"]
        if observation["descendants"]["handling"] == "unconfirmed":  # capacity is not released on an unconfirmed group (L-7)
            return self._enter_unknown(job, order, journal, grant, status, "termination_unconfirmed")
        facts = {"end_evidence_ref": collected["record"]["content_hash"]}
        if status["cancel_requested"] or observation["findings"]:
            self._settle_delegates(order)
        if status["cancel_requested"]:
            response = self._transition(job, journal, grant, "cancelled", **facts)
        elif observation["findings"]:
            response = self._transition(job, journal, grant, "failed", failure_class=observation["findings"][0], **facts)
        else:
            response = self._transition(job, journal, grant, "result_ready", result_payload_digest=collected["result"]["content_hash"])
            if response["status"] in ("recorded", "replayed"):
                self._accepted(job, journal, "result_ready")
                self._fault("result_ready_recorded")
                return self._result_ready(job, order, journal, grant, self._status(job, journal, grant))
            if response.get("reason") == "cancel_requested":  # the cancellation won the race: the result stays retained (C-10)
                return self._drive(job, order, journal)
            self._refused(job, journal, "result_ready", response)
        if response["status"] not in ("recorded", "replayed"):
            self._refused(job, journal, "end", response)
        self._accepted(job, journal, "end")
        return self._settle(job, journal, response["state"])

    def _result_ready(self, job, order, journal, grant, status) -> str:
        collected = journal["collected"]
        envelope = journal.get("envelope")
        if envelope is None:
            envelope = self._envelope(order, grant, collected, status["state_revision"])
            journal["envelope"] = envelope
            self._save(job, journal)
        self._settle_delegates(order)
        response = self._call(job, journal, "commit_outcome", envelope)
        self._fault("commit_replied")
        if response["status"] in ("committed", "replayed"):
            return self._settle(job, journal, "committed")
        if response["reason"] in ("state_revision_stale", "topic_paused"):
            if self._spend(job, journal, "commit"):
                if response["current_state_revision"] is not None:
                    journal["envelope"] = self._envelope(order, grant, collected, response["current_state_revision"])
                    self._save(job, journal)
                raise Waiting("result_ready")
            self._exhausted(job, journal, "commit", {"reason": response["reason"], "detail": response.get("detail")}, collected["result"])
        observation = {**collected["observation"], "findings": ["result_rejected"]}  # the result stays in the spool, uncommitted (C-10)
        return self._end(job, order, journal, grant, "failed", observation, "exit_observed")

    def _envelope(self, order: dict, grant: dict, collected: dict, state_revision: int) -> dict:
        result, record = collected["result"], collected["record"]
        return {"envelope_version": "commit-outcome/1", "operation_id": "op_f" + hashlib.sha256(order["invocation_id"].encode()).hexdigest()[:40],
                "operation_kind": "final_outcome", "invocation_id": grant["invocation_id"], "capability_id": grant["capability_id"],
                "topic_id": grant["topic_id"], "admission": grant["admission"], "config_bundle_hash": grant["config_bundle_hash"],
                "lease": {"lease_id": grant["lease"]["lease_id"], "generation": grant["lease"]["generation"]}, "expected_state_revision": state_revision,
                "payload_digest": result["content_hash"], "payload_size_bytes": result["size_bytes"], "result_refs": [record], "submitted_at": self._now()}

    # -- outcome_unknown -----------------------------------------------------------
    def _enter_unknown(self, job, order, journal, grant, status, cause: str) -> str:
        response = self._transition(job, journal, grant, "outcome_unknown", unknown_episode=status["unknown_episode"] + 1, unknown_cause=cause)
        if response["status"] not in ("recorded", "replayed"):
            self._refused(job, journal, "unknown", response)
        self._accepted(job, journal, "unknown")
        self._fault("unknown_recorded")
        return self._unknown(job, order, journal, grant, self._status(job, journal, grant))

    def _unknown(self, job, order, journal, grant, status) -> str:
        """Reconcile the current episode from what the job's handle finds (and
        what this supervisor already collected from it); what cannot be
        established stays unknown under the episode's hold (L-4)."""
        cancel = status["cancel_requested"] is not None
        view = job.lookup()
        if view["verdict"] == "exited" and not journal.get("collected"):
            self._collect(job, order, journal, view)
        collected = journal.get("collected")
        if collected is not None:
            observation = collected["observation"]
            if observation["descendants"]["handling"] == "unconfirmed":
                self._unresolved(job, journal, status, "the collected end's descendants are not confirmed ended")
            if cancel and observation["termination"] is None:
                # a cancellation of work that already ended: the owned group is confirmed empty by the same idempotent
                # operation that ends a live one — an empty group is signalled nothing (descendants none_found) — and the
                # observed exit is kept as it was: nothing says the cancellation caused it (Q5 ruling; Astra 1c review A2)
                ended = job.terminate(view["identity"], term_grace=self._policy(job).term_grace_s, kill_grace=self._policy(job).kill_grace_s, reap=self._reap)
                if not ended["confirmed"]:
                    self._unresolved(job, journal, status, "the group of work that already exited is not confirmed empty")
                observation = {**observation, "termination": {"reason": "cancellation"}, "descendants": self._handled(ended)}
            if cancel or collected.get("terminated"):  # the group was ended by the supervisor: its end is a cancellation if one was asked for
                return self._reconcile(job, order, journal, grant, status, "terminated_group", "execution_group_termination", observation)
            if observation["findings"]:
                return self._reconcile(job, order, journal, grant, status, "confirmed_failed", "job_handle_lookup", observation)
            return self._reconcile(job, order, journal, grant, status, "found_result", "job_handle_lookup", observation, digest=collected["result"]["content_hash"])
        if view["verdict"] in ("starting", "unstarted"):
            view = self._await_identity(job, self._policy(job).start_grace_s)
        if view["verdict"] in ("not_started", "unstarted"):
            if view["verdict"] == "unstarted" and not job.abandon():  # a launcher got the lock first: its identity is next
                self._unresolved(job, journal, status, "a launcher took the lock before the start could be abandoned")
            if cancel:  # the group is confirmed empty: no launcher ever ran, and the abandoned mark keeps a late one from starting
                return self._reconcile(job, order, journal, grant, status, "terminated_group", "execution_group_termination",
                                       {**self._unrun(None, "cancelled; the launcher never started and the job is abandoned: nothing was signalled"),
                                        "termination": {"reason": "cancellation"}})
            return self._reconcile(job, order, journal, grant, status, "confirmed_failed", "job_handle_lookup", self._unrun("never_started", "the launcher never started"))
        if view["verdict"] in ("starting", "exited"):  # still no identity after the grace; or an exit a moment ago (collected on the next advance)
            self._unresolved(job, journal, status, f"the launcher is {view['verdict']} after the start grace")
        if view["verdict"] == "running" and not cancel and not self._past(order["deadline_at"]):
            observation = {**self._unrun(None, "running"), "process": self._process(view["identity"])}
            return self._reconcile(job, order, journal, grant, status, "found_running", "job_handle_lookup", observation, identity=observation["process"])
        if view["verdict"] == "vanished" and not view["members"] and not cancel:  # the launcher is gone, and nothing of its group is left
            observation = {**self._unrun("no_exit_record", "the launcher is gone without an exit record"), "process": self._process(view["identity"])}
            return self._reconcile(job, order, journal, grant, status, "confirmed_failed", "job_handle_lookup", observation)
        # running under cancellation or past its deadline, or vanished leaving members: end the group, then reconcile by termination
        reason = "cancellation" if cancel else ("timeout" if self._past(order["deadline_at"]) else "reconciliation")
        ended = job.terminate(view["identity"], term_grace=self._policy(job).term_grace_s, kill_grace=self._policy(job).kill_grace_s, reap=self._reap)
        if not ended["confirmed"]:
            self._unresolved(job, journal, status, f"the group's termination ({reason}) is not confirmed")
        observation = {**self._unrun({"cancellation": None, "timeout": "timeout"}.get(reason, "no_exit_record"), None),
                       "process": self._process(view["identity"]), "exit": job.read("exit.json"), "termination": {"reason": reason},
                       "descendants": self._handled(ended)}
        return self._reconcile(job, order, journal, grant, status, "terminated_group", "execution_group_termination", observation)

    def _reconcile(self, job, order, journal, grant, status, resolution: str, method: str, observation: dict, *, identity: dict | None = None,
                   digest: str | None = None) -> str:
        purpose = f"reconcile:{status['unknown_episode']}"
        kept = journal.get("pending") if (journal.get("pending") or {}).get("purpose") == purpose else None  # a request already fixed is sent as it was
        if (kept or {"resolution": resolution})["resolution"] in ("confirmed_failed", "terminated_group"):
            self._settle_delegates(order)
        pending = self._pending(job, order, journal, purpose, resolution=resolution, method=method, observation=observation, identity=identity, digest=digest)
        request = {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "unknown_episode": status["unknown_episode"],
                   "resolution": pending["resolution"], "method": pending["method"], "evidence_ref": pending["record"]["content_hash"]}
        if pending["identity"] is not None:
            request.update(pending["identity"])
        if pending["digest"] is not None:
            request["result_payload_digest"] = pending["digest"]
        if pending["resolution"] in ("confirmed_failed", "terminated_group") and not (pending["resolution"] == "terminated_group" and status["cancel_requested"]):
            request["failure_class"] = pending["observation"]["findings"][0]
        self._sent(job, journal, self._call(job, journal, "reconcile", request), "reconcile")
        if journal.pop("unresolved", None) is not None:  # the episode is reconciled: its unknown budget is spent no longer
            journal["budgets"].pop("unknown", None)
            self._save(job, journal)
        return self._drive(job, order, journal)
