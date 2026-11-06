"""Order and input assembly for one supervised executor invocation.

Trace: 2e2-min design O14.1, O14.2; DEPLOYMENT-CONTRACT §2 (prompts are mounted files, hash-pinned by the
active bundle's policy.executors); Astra T11 decision 4 (pinned mounted prompts), F3. Oracle: the bundle's
pin, recomputed here from the mounted bytes. Limits: it returns an OrderSpec with a WorkOrder's fields; the
composition root (T17) builds the WorkOrder, so this module imports only core. It selects no scientific
work: which purpose runs next, and its ordinal, are the driver's.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from gen2.core import canonical
from gen2.exec.common import Refused

INPUT, PROMPT = "input.json", "prompt.md"
INPUT_DIR = "inputs"
ENTRY_KEYS = ("deadline_s", "lease_s", "max_input_bytes", "max_output_bytes")


@dataclass(frozen=True)
class OrderSpec:
    invocation_id: str
    kind: str
    topic_id: str
    config_bundle_hash: str
    deadline_at: str
    lease_expires_at: str
    command: tuple[str, ...]
    env: Mapping[str, str]


def executor_entry(bundle: Mapping, kind: str, purpose: str) -> Mapping:
    """The bundle's policy.executors entry for (kind, purpose); absent is refused, never defaulted (G-10)."""
    for entry in bundle.get("policy", {}).get("executors", []):
        if (entry.get("kind"), entry.get("purpose")) == (kind, purpose):
            if any(not isinstance(entry.get(key), int) or entry[key] < 1 for key in ENTRY_KEYS):
                raise Refused(f"executor {kind}/{purpose}: {ENTRY_KEYS} must be positive integers")
            return entry
    raise Refused(f"no executors entry for {kind}/{purpose}")


def mounted_prompt(prompt_dir: Path, entry: Mapping) -> bytes:
    """The mounted `<kind>.<purpose>.md` bytes, refused unless they hash to the entry's pin."""
    path = Path(prompt_dir) / f"{entry['kind']}.{entry['purpose']}.md"
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Refused(f"prompt {path.name} unreadable: {error.strerror}") from None
    if canonical.bytes_digest(data) != entry["prompt"]["content_hash"]:
        raise Refused(f"prompt {path.name} does not match the bundle pin")
    return data


def work_input(*, kind: str, purpose: str, invocation_id: str, topic_id: str, admission: Mapping, entry: Mapping,
               view: Mapping, truncation: list[dict]) -> dict:
    """The work-input/1 document; the model reads it and cannot write it."""
    return {"input_version": "work-input/1", "kind": kind, "purpose": purpose, "invocation_id": invocation_id,
            "topic_id": topic_id, "admission": dict(admission),
            "limits": {"max_input_bytes": entry["max_input_bytes"], "max_output_bytes": entry["max_output_bytes"]},
            "view": dict(view), "truncation": truncation}


def write_inputs(directory: Path, *, entry: Mapping, prompt: bytes, document: Mapping) -> str:
    """Write inputs/prompt.md and inputs/input.json under `directory`; returns input.json's byte digest.
    An input over the entry's cap is refused, never truncated (truncation is the view's recorded act)."""
    data = canonical.canonical_bytes(document)
    if len(data) > entry["max_input_bytes"]:
        raise Refused(f"input is {len(data)} bytes, over the {entry['max_input_bytes']} cap")
    target = Path(directory) / INPUT_DIR
    target.mkdir(parents=True, exist_ok=True)
    (target / PROMPT).write_bytes(prompt)
    (target / INPUT).write_bytes(data)
    return canonical.bytes_digest(data)


def build_order(*, bundle: Mapping, bundle_hash: str, kind: str, purpose: str, topic_id: str, ordinal: int,
                now: datetime, directory: str, input_digest: str, python: str = "python3") -> OrderSpec:
    """The order for the `ordinal`-th invocation of (topic, kind, purpose). The id derives from those three,
    so a driver that crashes and rebuilds the order names the same job (L-8)."""
    entry = executor_entry(bundle, kind, purpose)
    name = hashlib.sha256(f"{topic_id}\0{kind}\0{purpose}\0{ordinal}".encode()).hexdigest()[:32]
    start = now.astimezone(timezone.utc)
    stamp = lambda seconds: (start + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return OrderSpec(invocation_id=f"inv_{name}", kind=kind, topic_id=topic_id, config_bundle_hash=bundle_hash,
                     deadline_at=stamp(entry["deadline_s"]), lease_expires_at=stamp(entry["lease_s"]),
                     command=(python, "-m", "gen2.exec.job", purpose, directory),
                     env={"GEN2_PURPOSE": f"{kind}/{purpose}", "GEN2_INPUT_DIGEST": input_digest})
