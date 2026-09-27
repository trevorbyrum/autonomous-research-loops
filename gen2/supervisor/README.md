# Gen-2 station supervisor (task 1c)

`supervisor.Supervisor` is the one lifecycle implementation for every invocation kind: research pass, discovery, delegate, verification and checkpoint (BOUNDARIES.md *Station supervisor*; INVARIANTS RG-2). Nothing in it branches on the kind except the claim a delegate makes under its parent's capability (L-8). It reaches the router only through the `ControlBackend` protocol (`gen2/core/control.py`), wired by the composition root (`gen2/app/station.py`). It imports neither router nor store (`gen2/boundaries.toml`).

| File | What it is |
|---|---|
| `supervisor.py` | The lifecycle: `prepare`/`submit` an order, `advance` one step, `run` to an end, `recover` after a restart. |
| `jobs.py` | A job per invocation under its stable handle `job-<invocation id>`: its directory, the launcher start, lookup by handle, process identity, the execution group and its termination. |
| `jobshim.py` | The launcher: a standard-library script started by path in its own session. It is the job's execution group, and it outlives the supervisor. |
| `spool.py` | The protected spool (C-9): immutable, content-addressed, topic-scoped and size-bounded. It is also the router's `StagedBytes`. |
| `fake_executor.py` | Deterministic, scriptable stand-ins for an agent of any kind: no model, gateway or network. |

## One job, three durable records

A supervisor holds nothing it needs only in memory. Each `advance` rebuilds its view from:
- **The job directory** (`jobs.py` docstring). It holds the order, written before the claim, and what the launcher recorded: `spawn.json` is written before each start, and `identity.json` and `exit.json` are written atomically by the launcher. It also holds the supervisor's `journal.json`: the grant, the end it observed and retained, the envelope it sent, its budgets and any local incident.
- **The spool.** It holds the result bytes and every execution record (`execution-record/1`, `gen2/schema/execution-record.schema.json`).
- **The router.** It holds the authoritative lifecycle (L-1), read with `invocation_status`.

## The lifecycle

Each `advance` first observes the job **locally**. This needs no router, so admitted work finishes and is retained while the router is away (C-10):
- An exit is collected. The rest of the execution group is ended and confirmed gone (L-7). The output is checked structurally and staged. The execution record is written.
- A job past its deadline has its whole group terminated.

Then it drives the router one step:

| Router state | What the supervisor does |
|---|---|
| `admitted` | Records launch intent before any start (L-2). This is the router's final launch-admission check (lease, pause, deadline, cancellation; L-7). A paused topic is retried within the launch budget. After that, or on a lapsed lease or deadline, the supervisor cancels the admitted work itself (`requested_by: supervisor`); nothing was spawned. |
| `launching` | Starts the launcher (spawn budget) and records the identity the launcher recorded: job handle, host, container, boot id, and a start fingerprint of pid, start time and session (L-3). A start this process did not see through enters `outcome_unknown` (`spawn_uncertain`). |
| `running` | Delivers the collected end: a structural finding is `failed` with its class and record, and a clean end is `result_ready`. A cancellation request terminates the group, then records `cancelled` once descendants are confirmed. A launcher gone with no exit record enters `outcome_unknown` (`contact_lost`). A group whose termination is unconfirmed enters `outcome_unknown` (`termination_unconfirmed`) and releases no capacity. |
| `result_ready` | `commit_outcome` of the retained result, with its execution record as a result reference. A stale state revision or a paused topic is re-sent within the commit budget. Any other refusal is `failed` (`result_rejected`), and the result stays in the spool, uncommitted. |
| `outcome_unknown` | Reconciles the current episode (L-4) with what the job's handle finds: `found_running` (a live, verified launcher), `found_result` (the collected clean result), `confirmed_failed` (a finding, a launcher gone with nothing left, or a start that never ran), or `terminated_group` (ends as `cancelled` if cancellation was requested, else `failed`). What cannot be established stays unknown under the episode's router hold, which has an owner and a deadline. |

**Structural checks decide (L-5, L-9).** The executor's result is one file of its scratch directory, `outcome.json`; the supervisor chose that name. Each of these is a failure with a structural class:
- a non-zero exit (`exit_nonzero`) or a signal (`killed`);
- a missing or empty file (`empty_output`), whatever `status.json` says;
- a symlink, hard link, special file or oversized file (`output_refused`);
- a declared digest the bytes do not have (`output_digest_mismatch`).

The agent's self-report and declared digest are recorded in the execution record as data and never decide anything. Empty output is written to the store as the failed transition itself, with its class, its execution record (an artifact) and its audit event, never as a bare return code. See *Open questions* in the task report on reading "observation stream".

**Capacity (L-7).** A failure or cancellation releases the lease only when its execution record confirms the descendants were handled. The router refuses the end otherwise.

**Retry budgets (L-6).** Every retry path draws on a budget in `Policy`: router sends per outage, `recover()` resumptions, launch refusals, launcher starts and commit re-sends. The budget is kept in the journal before each attempt, so a restart does not refill it. A router unreachable past its budget stalls the job with a local incident until `recover()` (itself budgeted). A success ends an outage: the router count restarts at the next one.

**Crash and restart.** The launcher runs in its own session and survives the supervisor. `recover()` advances every job from its handle. A start found after a restart gets `start_grace_s` to show itself. Before a start that left no identity is settled as never started, the supervisor marks the job `abandoned` and then checks the launcher's lock. A launcher that takes the lock after that reads the mark and starts nothing (`jobshim.py` steps 1–3). So "never started" is final.

## What is proven, and where

- `gen2/tests/test_supervisor_lifecycle.py`: the fault set for all five kinds, with real child processes. It covers a clean end; empty output, including a claimed success without output; a wrong declared digest; a symlink or hard-link output; an exit code or signal; a live descendant after exit; timeout; cancellation, and cancellation racing completion in both orders; pause at launch; a stale result after lease loss; replay of a delivered result; router outage and recovery, including a deadline passing during the outage; `outcome_unknown` entered and reconciled, both by termination and by lookup; and the spawn budget.
- `gen2/tests/test_supervisor_crash.py`: the supervisor killed with `os._exit` at each lifecycle boundary and restarted, for all five kinds. This includes a crash between spawn and identity record, and a second crash right after entering `outcome_unknown`.
- `gen2/tests/test_supervisor_spool.py` and `test_supervisor_jobs.py`: the spool's and the job layer's own guards.

## Structural limits

- Faults are what these processes can do to each other on one host: kills, exits, hangs and lost replies. They do not cover power loss or disk corruption; a kill leaves the page cache.
- Fencing protects commits. It does not undo an orphan's external effects (L-7).
- A descendant that leaves the job's session (`setsid`) is not seen or ended. A pid reused by a new session leader within a job's life would be counted as a member.
- The spool and job directories are protected by being the station's, not by the OS: another process of the same user can write them. Isolation is deployment's and 1e's.
- The supervisor trusts its own observations. The router binds the execution record to the invocation, the job and what the record supports, not to whether it is true.
- Linux only (`/proc`).
