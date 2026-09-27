# Gen-2 station supervisor (task 1c)

`supervisor.Supervisor` is the one lifecycle implementation for every invocation kind: research pass, discovery, delegate, verification and checkpoint (BOUNDARIES.md *Station supervisor*; INVARIANTS RG-2). Nothing in it branches on the kind except the claim a delegate makes under its parent's capability (L-8) and, for a parent, ending its delegates before its own end. It reaches the router only through the `ControlBackend` protocol (`gen2/core/control.py`), wired by the composition root (`gen2/app/station.py`). It imports neither router nor store (`gen2/boundaries.toml`).

| File | What it is |
|---|---|
| `supervisor.py` | The lifecycle: `prepare`/`submit` an order, `advance` one step, `run` to an end, `recover` after a restart, `incidents` to list what is open. |
| `jobs.py` | A job per invocation under its stable handle `job-<invocation id>`: its directory, the launcher start, lookup by handle, process identity, the execution group and its termination. |
| `jobshim.py` | The launcher: a standard-library script started by path in its own session. It is the job's execution group, and it outlives the supervisor. |
| `spool.py` | The protected spool (C-9): immutable, content-addressed, topic-scoped and size-bounded. It is also the router's `StagedBytes`. |
| `fake_executor.py` | Deterministic, scriptable stand-ins for an agent of any kind: no model, gateway or network. |

## One job, three durable records

A supervisor holds nothing it needs only in memory. Each `advance` rebuilds its view from:
- **The job directory** (`jobs.py` docstring). It holds the order, written before the claim, and what the launcher recorded: `spawn.json` is written before each start, and `identity.json` and `exit.json` are written atomically by the launcher. It also holds the supervisor's `journal.json`: the grant; an end being observed (`observing`) and the end observed and retained (`collected`); the request an end or a reconciliation sends, fixed with its staged record (`pending`); the envelope it sent; its budgets; an outage in progress; and its incidents.
- **The spool.** It holds the result bytes and every execution record (`execution-record/1`, `gen2/schema/execution-record.schema.json`).
- **The router.** It holds the authoritative lifecycle (L-1), read with `invocation_status`.

## The lifecycle

Each `advance` first observes the job **locally**. This needs no router, so admitted work finishes and is retained while the router is away (C-10):
- An exit is collected. The rest of the execution group is ended and confirmed gone (L-7). The output is checked structurally and staged. The execution record is written.
- At its deadline a live group is terminated: a running one, and one whose launcher has vanished while members of its session remain. This does not wait for a router answer (Astra 1c review A9).

What cannot be done twice is kept in the journal before the next step: the descendants handled, the observation with its staged result, a termination as it happened. A write that fails is retried from there; nothing is observed or signalled again for it.

Then it drives the router one step:

| Router state | What the supervisor does |
|---|---|
| `admitted` | Records launch intent before any start (L-2); the router checks launch admission (lease, pause, deadline, cancellation; L-7) as it records it. A paused topic is retried within the launch budget. After that, or on a lapsed lease or deadline, the supervisor cancels the admitted work itself (`requested_by: supervisor`); nothing was spawned. |
| `launching` | Before **every** actual start — the first, a start retried after the OS refused one, a start after a restart — reads the router's current launch-admission check (`launch_admission` in `invocation_status`): recorded launch intent is not renewed authority (A1). A withdrawn authority starts nothing: a pause waits within the launch budget, then (or for a lapsed, released or replaced lease) the work is cancelled. Otherwise it starts the launcher (spawn budget) and records the identity the launcher recorded: job handle, host, container, boot id, and a start fingerprint of pid, start time and session (L-3). A start this process did not see through enters `outcome_unknown` (`spawn_uncertain`). |
| `running` | Delivers the collected end: a structural finding is `failed` with its class and record, and a clean end is `result_ready`. A cancellation request terminates the group, then records `cancelled` once descendants are confirmed. A launcher gone with no exit record enters `outcome_unknown` (`contact_lost`). A group whose termination is unconfirmed enters `outcome_unknown` (`termination_unconfirmed`) and releases no capacity. |
| `result_ready` | `commit_outcome` of the retained result, with its execution record as a result reference. A stale state revision or a paused topic is re-sent within the commit budget. Any other refusal is `failed` (`result_rejected`), and the result stays in the spool, uncommitted. |
| `outcome_unknown` | Reconciles the current episode (L-4) with what the job's handle finds: `found_running` (a live, verified launcher), `found_result` (the collected clean result), `confirmed_failed` (a finding, a launcher gone with nothing left, or a start that never ran), or `terminated_group`. A terminated group ends `failed` with its failure class, or — when cancellation was requested — `cancelled` with none: no failure class is invented for a cancellation (A2). For work that already exited, the cancellation is reconciled by the same idempotent group termination, which on an empty group signals nothing (recorded as `none_found`), and the exit stays as the launcher recorded it. What cannot be established stays unknown under the episode's router hold, which has an owner and a deadline and clears only through the episode's reconciliation (A7). |

**Structural checks decide (L-5, L-9).** The executor's result is one file of its scratch directory, `outcome.json`; the supervisor chose that name. Each of these is a failure with a structural class:
- a non-zero exit (`exit_nonzero`) or a signal (`killed`);
- a missing or empty file (`empty_output`), whatever `status.json` says;
- a symlink, hard link, special file, oversized file, or a file that changed while it was read (`output_refused`; A10);
- a declared digest the bytes do not have (`output_digest_mismatch`).

The agent's self-report is recorded as data and decides nothing. The declared digest is checked data that cannot establish success: one that disagrees with the bytes refuses the output, and one that agrees adds nothing — the supervisor's own hash of the bytes is what is recorded. Empty output is written to the store as the failed transition itself, with its class, its execution record (an artifact) and its audit event, never as a bare return code.

**Capacity (L-7, L-8).** A failure or cancellation releases the lease only when its execution record confirms the descendants were handled; the router refuses the end otherwise. A parent's lease is also its delegates', and a delegate runs in its own session, which the parent's descendant check cannot see: before anything that releases a parent's capacity (a failure, a cancellation, a terminal reconciliation, an unlaunched end, the final commit), the supervisor ends every delegate job it holds for the parent — cancellation requested, group terminated, or an already staged result delivered — and the parent waits until the router confirms each ended. The router refuses the parent's release while a delegate is live (A3).

**Budgets and incidents (L-6, RG-3).** Every retry path draws on a budget in `Policy`, kept in the journal before each attempt, so a restart does not refill it:
- *Router.* An outage is budgeted from its first failed call until a write the router answers; a successful read refunds nothing (A5). It is bounded by attempts (`router_attempts`) and by time (`router_window_s`). Past either, the job stalls with a `router_unreachable` incident.
- *Durable writes.* A write the supervisor cannot make — a record or result over the spool quota, a file-system error from the spool — is an infrastructure failure, never a completion (C-10). It is retried on later advances within `write_attempts`; past that the job stalls with a `durable_write_failed` incident naming its phase and error. When the journal itself cannot be written, the incident cannot be kept either: `advance()` raises `ControlFailure` to its caller, out of band, and `recover()` raises it after trying every job (A4).
- *Recovery.* `recover()` resumes a stalled job, drawing on `recovery_attempts`. It does not refill the budget that ran out: a resumption that fails again stalls again at once.
- *Launch, spawn and commit.* When one of these retry budgets runs out, the job ends as before (cancelled, `spawn_failed`, `result_rejected`) and a `retry_exhausted` incident is recorded beside that end, with the budget, the last refusal and the result it concerns (A11). An ordinary resolved failure, or a refusal that is not retried, raises none.

Every incident has an owner (`supervisor:<station>`) and a deadline (`incident_window_s`), and `Supervisor.incidents()` lists them. The one a stalled job waits on is cleared by `recover()`; a `retry_exhausted` incident is a record for the operator surface, which is 1e's.

**Crash and restart.** The launcher runs in its own session and survives the supervisor. `recover()` advances every job from its handle. A start found after a restart gets `start_grace_s` to show itself. Before a start that left no identity is settled as never started, the supervisor marks the job `abandoned` and then asks whether a launcher holds the job's lock. A lookup only asks (an open-file-description lock query) and never takes the lock, so it cannot make a launcher that is locking at that moment give up (task 1c-repair C2: that race ended jobs as never started under load). A launcher that takes the lock after the mark reads it and starts nothing (`jobshim.py` steps 1–3). So "never started" is final. The request of an end or a reconciliation is fixed with its staged record before it is sent, so a retry after a lost reply sends the identical request and replays.

## What is proven, and where

- `gen2/tests/test_supervisor_lifecycle.py`: the fault set for all five kinds, with real child processes. It covers a clean end; empty output, including a claimed success without output; a wrong declared digest; a symlink or hard-link output; an exit code or signal; a live descendant after exit; timeout; cancellation, and cancellation racing completion in both orders; pause at launch; a retried start admitted again; a stale result after lease loss; replay of a delivered result; router outage and recovery, including a deadline passing during the outage and a launcher that vanished during it; `outcome_unknown` entered and reconciled, both by termination and by lookup; and the launch, spawn and commit budgets with their exhaustion incidents.
- `gen2/tests/test_supervisor_crash.py`: the supervisor killed with `os._exit` at each lifecycle boundary and restarted, for all five kinds. This includes a crash between spawn and identity record, a second crash right after entering `outcome_unknown`, a recovery after launch intent whose authority was withdrawn meanwhile (pause, expired, released or replaced lease, cancellation), and cancellation after an uncertain spawn (live, exited, never started).
- `gen2/tests/test_supervisor_delegates.py`: the four parent kinds ending — completion, failure, cancellation, a vanished launcher's reconciliation, a start that never happened, a supervisor restart — with nothing of the delegate's group alive at any releasing call.
- `gen2/tests/test_supervisor_budgets.py`: durable-write failures (record over quota, ENOSPC, termination and reconciliation records, an unwritable journal) and partial router availability, for all five kinds, each with a recovery control.
- `gen2/tests/test_supervisor_spool.py` and `test_supervisor_jobs.py`: the spool's and the job layer's own guards, including a scratch file changed while it is read and the lock probe.

These are the chosen schedules; they do not establish arbitrary concurrency.

## Structural limits

- Faults are what these processes can do to each other on one host: kills, exits, hangs and lost replies. They do not cover power loss or disk corruption; a kill leaves the page cache.
- Fencing protects commits. It does not undo an orphan's external effects (L-7).
- A descendant that leaves the job's session (`setsid`) is not seen or ended. A pid reused by a new session leader within a job's life would be counted as a member. Members are listed (session, start time, not a zombie) and then signalled by pid: in the interval between listing a pid and signalling it, it can exit and be reused by an unrelated process, which would receive the signal.
- The spool and job directories are protected by being the station's, not by the OS: another process of the same user can write them. Isolation is deployment's and 1e's. A scratch change that leaves a file's size and times as they were (within one timestamp tick of the previous write) is not detected; the job's group is ended before collection, so it needs a process outside the group.
- The spool's aggregate quota is counted per `Spool` instance, from its own writes and its last listing: two instances writing one root can exceed it together. One writer per spool root is a deployment restriction.
- The supervisor trusts its own observations. The router binds the execution record to the invocation, the job and what the record supports, not to whether it is true.
- Linux only (`/proc`, open-file-description locks).
