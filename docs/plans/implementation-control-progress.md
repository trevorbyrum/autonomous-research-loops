# Control vertical progress

Scope: controller-owned storage, station configuration, assignment scheduler and
worker boundary only. Ordinary research prompts and methods are untouched.

| Requirement / acceptance | Evidence | Status |
| --- | --- | --- |
| R05, R15, R16; A38 | `research_loops/control_store.py`: explicit opt-in SQLite store, profile registry/resolution, one atomic logical transaction across configuration/queue/work; dry-run or explicit baseline migration only | implemented, unit tests passing |
| R01, R02, R03, R04; A01-A06, A40 | `ControlScheduler`, managed `QueueStore`/`StationsStore` adapters, `workers.start` active-prefix guard | implemented with disposable tests |
| R04, R10; A07-A10, A19, A21-A25 | Desired/current leases, review holds, queue revision reorder, runner-facing `QueueStore.finalize_run` adapter | implemented with disposable tests |
| R01-R05, R10-R11, R16; A37-A40 | `docs/managed-stations.md`, `control-migrate` dry-run/apply CLI, controller station status projection | implemented and CLI tested |

No production state, service, configuration, or model invocation has been changed.
