"""The dossier job: a code-only checkpoint invocation whose recorder asks the router to record the dossier.

Trace: 2e2-min design O16.5; Astra T11 F2 (bounded, replayable recording; stable effect identity) and decision 6;
INVARIANTS C-10 (replay by invocation returns the original revision and hash, never a recompute), G-8, D3 (a gate with
missing records reads unknown, never satisfied). Oracle: the router's own answer; a replay must equal the first answer.
Limits: it decides nothing about sufficiency. The dossier row needs a live admitted invocation, and the later review must
come from a different one, which is why this is a job of its own. The recorder is installed under `checkpoint/dossier`
(supervisor.RECORDED makes the station refuse the purpose without it); the bundle's executors entry and the no-op agent
step that runs `build_dossier` through job.run belong to the composition root (T17).
"""
from __future__ import annotations

from typing import Mapping

from gen2.exec.common import Refused, scaffold

KEY = "checkpoint/dossier"


def record(control, order: Mapping, grant: Mapping, scratch: object) -> None:
    """The supervisor's recorder: idempotent, because the router replays by invocation id. A refusal raises, so the
    supervisor spends a write attempt and, once they are gone, holds the job; the result never commits unrecorded."""
    answer = control.record_dossier({"capability_id": grant["capability_id"], "invocation_id": order["invocation_id"], "topic_id": order["topic_id"]})
    if answer.get("status") not in ("recorded", "replayed"):
        raise Refused(f"record_dossier refused: {answer.get('reason')}: {answer.get('detail')}")


def build_dossier(work: Mapping, judgment: Mapping) -> dict:
    """The job's outcome: an empty outcome/1. Its evidence is the dossier row the recorder wrote."""
    return scaffold(work["invocation_id"], work["topic_id"])
