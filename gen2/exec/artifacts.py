"""Bind bytes to artifact references: staged claim text, and the source_artifacts of selected retained sources.

Trace: 2e2-min design O14.5, O14.10; Astra T11 F3 (the research builder commits source_artifacts bound to the
trusted retained bytes and the real retrieval and work lineage, before re-access is admitted; the verifier never
fabricates a source row, and discovery gets no PRIMARY authority). Oracle: the digest recomputed from the bytes.
Limits: the stage function is the topic spool's `stage`; `Exchanges` is the retained-exchange read T13 stages and
T15's capture reader consumes, coded here against its ticket-plan shape; `source_version` is the response
bytes' own digest, so a version names exactly the bytes it was taken from.
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping, Protocol, Sequence

from gen2.core import canonical
from gen2.exec.common import Refused

Stage = Callable[[bytes, str], Mapping]


class Exchanges(Protocol):
    def response(self, gateway_call_ref: str) -> tuple[Mapping, bytes] | None:
        """(artifact_ref, bytes) staged for this topic's retained gateway response, or None."""


def text_ref(stage: Stage, text: str) -> dict:
    """Stage `text` as UTF-8 and return its artifact_ref, refused unless the ref is the bytes' own."""
    data = text.encode("utf-8")
    ref = dict(stage(data, "text/plain"))
    if ref.get("content_hash") != canonical.bytes_digest(data) or ref.get("size_bytes") != len(data):
        raise Refused("the spool's reference is not the staged text's")
    return ref


def source_artifacts(work_ids: Iterable[str], records: Mapping[str, Sequence[Mapping]], exchanges: Exchanges) -> list[dict]:
    """One record per selected work, from the earliest retrieval event of this topic whose response is staged.
    A work the topic never retrieved, or one with no staged exchange, or bytes that do not hash to their
    reference, is refused: nothing is invented to make support possible."""
    events = {row["event_id"]: row for row in records["retrieval_events"]}
    observations = {row["observation_id"]: row for row in records["search_observations"]}
    out = []
    for work_id in sorted(set(work_ids)):
        linked = sorted((events[link["event_id"]] for link in records["record_work_links"]
                         if link["work_id"] == work_id and link["event_id"] in events),
                        key=lambda event: (event["captured_at"], event["event_id"]))
        if not linked:
            raise Refused(f"{work_id} was not retrieved by this topic")
        for event in linked:
            call = observations[event["observation_id"]].get("gateway_call_ref")
            staged = exchanges.response(call) if call else None
            if staged is not None:
                ref, data = staged
                if canonical.bytes_digest(data) != ref["content_hash"]:
                    raise Refused(f"{work_id}: the staged response does not hash to its reference")
                out.append({"work_id": work_id, "source_version": ref["content_hash"], "artifact_ref": dict(ref)})
                break
        else:
            raise Refused(f"{work_id}: no retained response is staged for it")
    return out
