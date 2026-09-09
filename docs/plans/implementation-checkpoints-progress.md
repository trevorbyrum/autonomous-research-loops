# Checkpoint execution progress

Implemented in `research_loops.checkpoints` against the controller transaction
interface. No deployment, live configuration, service, or model invocation was
performed.

| Requirement / acceptance | Evidence |
|---|---|
| R05, R06; A11–A14, A19 | `accept_research_completion` records accepted ordinary run IDs once, preserves next ordinal, and creates durable handled trigger records. |
| R07; A18 | Deepening entry is recorded per inventory version and coalesces with cadence into one episode. |
| R08; A15–A16 | `start_checkpoint` snapshots either station 1's pair or an explicit pair once per episode. The adapter entry point is separate from ordinary prompts. |
| R09; A20–A25 | Valid complete empty results resume automatically. Structured proposal decisions are idempotent and retain the topic's ordinal and queue-owned position. |
| R13, R14; A26–A27, A33 | Checkpoint accounting is distinct from ordinary completion and contains no saturation/research-method changes. Runner/chassis integration remains pending release of concurrent edits. |
| A36 | The protocol is in the package under `research_loops/checkpoints/prompts/`, and `SubprocessCheckpointAdapter` resolves it from the installed package. Package-data inclusion is pending root packaging integration. |

`tests/test_checkpoint_lifecycle.py` uses a disposable fake transaction store and
fake checkpoint adapter. It covers 24 → 25 → checkpoint → 26, duplicate delivery,
coalesced deepening/cadence triggers, invalid/incomplete results, shared agents, and
idempotent decisions, strict incomplete-result handling, and managed checkpoint
dispatch. Controller-supervised accounting for individual secondary/counter/repair
delegate calls (A17) remains an adapter/controller-client integration task.
