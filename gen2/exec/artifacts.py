"""Bind bytes to artifact references: staged claim text, and the retained lineage of a work, read once by the parent (the views).

Trace: 2e2-min design O14.5, O14.10; Astra T11 F3 (source_artifacts are bound to the trusted retained bytes and the real retrieval
and work lineage, before re-access is admitted; the verifier never fabricates a source row, and discovery gets no PRIMARY authority);
Gate S #7 (builders read only the view and the bytes it names, so the lineage is computed here by the parent and carried in the view).
Oracle: the digest recomputed from the bytes. Limits: the stage function is the child's evidence stage; `Exchanges` is the retained-exchange
read the discovery job stages; `source_version` is the response bytes' own digest, so a version names exactly the bytes it was taken from.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from gen2.core import canonical
from gen2.exec.common import Exchanges, Refused

Stage = Callable[[bytes, str], Mapping]


def stage_bytes(stage: Stage, data: bytes, media_type: str) -> dict:
    """Stage `data` and return its artifact_ref, refused unless the ref is the bytes' own."""
    ref = dict(stage(data, media_type))
    if ref.get("content_hash") != canonical.bytes_digest(data) or ref.get("size_bytes") != len(data):
        raise Refused("the spool's reference is not the staged bytes'")
    return ref


def text_ref(stage: Stage, text: str) -> dict:
    """Stage `text` as UTF-8 and return its artifact_ref."""
    return stage_bytes(stage, text.encode("utf-8"), "text/plain")


@dataclass(frozen=True)
class Retained:
    ref: Mapping
    data: bytes
    lane: str
    provider_record_id: str
    event_id: str
    observation_id: str
    gateway_call_ref: str
    captured_at: str
    invocation_id: str   # the invocation that acquired the bytes (the observation's)


def retained(work_id: str, records: Mapping[str, Sequence[Mapping]], exchanges: Exchanges) -> Retained:
    """The earliest retrieval event of this topic for the work whose response is staged. A work the topic never
    retrieved, one with no staged exchange, or bytes that do not hash to their reference, is refused: nothing is
    invented to make support possible."""
    events = {row["event_id"]: row for row in records["retrieval_events"]}
    observations = {row["observation_id"]: row for row in records["search_observations"]}
    linked = sorted((events[link["event_id"]] for link in records["record_work_links"]
                     if link["work_id"] == work_id and link["event_id"] in events),
                    key=lambda event: (event["captured_at"], event["event_id"]))
    if not linked:
        raise Refused(f"{work_id} was not retrieved by this topic")
    for event in linked:
        observation = observations[event["observation_id"]]
        call = observation.get("gateway_call_ref")
        staged = exchanges.response(call) if call else None
        if staged is not None:
            ref, data = staged
            if canonical.bytes_digest(data) != ref["content_hash"]:
                raise Refused(f"{work_id}: the staged response does not hash to its reference")
            return Retained(ref, data, observation["lane"], event["provider_record_id"], event["event_id"], observation["observation_id"], call, event["captured_at"], observation["invocation_id"])
    raise Refused(f"{work_id}: no retained response is staged for it")
