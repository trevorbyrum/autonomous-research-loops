"""The host-side executor job: read inputs, run the agent step, read its judgment, build the outcome.

Trace: 2e2-min design §1.2; ticket plan wrapper contract (/inputs/prompt.md, /inputs/input.json read-only,
/out/judgment.json written, exit 0 = ran, outcome.json in scratch for the supervisor's _collect). Oracle: the
env digest of input.json, and the injected schema check of the judgment. Limits: the agent step, the schema
validator and the purpose builders are injected, because this module may import only core; the composition
root (T17) wires the real ones. A refusal leaves no outcome.json, so the supervisor sees a failed run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical
from gen2.exec import orders
from gen2.exec.common import Refused, outcome_bytes

OUT_DIR, JUDGMENT, OUTCOME = "out", "judgment.json", "outcome.json"
Agent = Callable[[bytes, bytes, Path], int]            # (prompt, input, out_dir) -> exit code
Builder = Callable[[Mapping, Mapping], Mapping]        # (work-input/1, judgment) -> outcome/1


def run(purpose: str, directory: Path, *, input_digest: str, agent: Agent, builder: Builder,
        validate: Callable[[str, object], None]) -> Path:
    """Run one purpose in `directory`; returns the written outcome.json path."""
    root = Path(directory)
    try:
        prompt = (root / orders.INPUT_DIR / orders.PROMPT).read_bytes()
        raw_input = (root / orders.INPUT_DIR / orders.INPUT).read_bytes()
    except OSError as error:
        raise Refused(f"inputs unreadable: {error.strerror}") from None
    if canonical.bytes_digest(raw_input) != input_digest:
        raise Refused("input.json does not match the order's digest")
    work = canonical.parse_json_strict(raw_input)
    if work["purpose"] != purpose:
        raise Refused("input.json is for another purpose")
    out = root / OUT_DIR
    out.mkdir(exist_ok=True)
    (out / JUDGMENT).unlink(missing_ok=True)   # a judgment left by an earlier run is never read as this run's
    code = agent(prompt, raw_input, out)
    if code != 0:
        raise Refused(f"agent step exited {code}")
    try:
        raw = (out / JUDGMENT).read_bytes()
    except OSError:
        raise Refused("agent step wrote no judgment.json") from None
    if len(raw) > work["limits"]["max_output_bytes"]:
        raise Refused("judgment.json is over the output cap")
    try:
        judgment = canonical.parse_json_strict(raw)
    except ValueError as error:
        raise Refused(f"judgment.json is not strict JSON: {error}") from None
    validate(purpose, judgment)
    path = root / OUTCOME
    path.write_bytes(outcome_bytes(builder(work, judgment)))
    return path
