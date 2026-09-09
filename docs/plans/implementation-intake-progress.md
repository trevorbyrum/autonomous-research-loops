# Intake interface implementation evidence

Implemented: strict brief/discovery/decision schemas; canonical draft creation;
automatic intake-lane registration; stale contract-hash rejection; request replay
protection; managed CLI/MCP handlers; and recoverable draft promotion.

Checkpoint decisions use the same controller dispatch and a staged contract
publisher. Additions/amendments update the approved contract and semantic
inventory; scope requests fail closed. The returned lock is persisted into the
managed queue item and work inventory with the decision.

Evidence run locally:

```text
.venv/bin/python -m pytest tests/test_intake_boundaries.py -q
5 passed
.venv/bin/python -m pytest tests/test_checkpoint_lifecycle.py -q
9 passed
```

Checkpoint bundles are staged in a disposable copy before any approved contract
file is changed. Successful decision handling removes its publication journal;
replay remains idempotent through the controller decision record.

Open: dedicated injected multi-proposal crash tests remain to be added.
