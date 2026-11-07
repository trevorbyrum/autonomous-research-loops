"""Retained exchanges of the discovery job: build, stage, index and read them.

Trace: 2e2-min design O13.5; Astra T11 decision 3 (trusted retained exchanges); DEBT-051 (the consumers are T15's capture
reader and the research builder's source_artifacts); DEBT-003 (the audit evidence requirement, owned by 2e2).

WHAT IS RETAINED, STATED PLAINLY. The response document is a canonical reconstruction of the client's parsed exchange
(capture echo, each lane's coverage, completeness and retrieved identities, the records), not the raw transport octets:
GatewayClient parses the body and keeps no octets. It satisfies router.reaccess.check_reaccess; it does not let an auditor
re-derive what the gateway literally sent. Retaining the octets is DEBT-003's. The request document is the canonical
attempted lane/page/request the observation holds.

The spool is addressed by content hash, so nothing there is keyed by call. The job's retained scratch therefore holds
`exchanges.json`: {gateway_call_ref, request ref, response ref} per captured call, and `ExchangeIndex` reads it back.
Oracle: byte digests recomputed on read. Limits: a call the gateway did not capture durably has no call ref and no entry;
the index lives as long as the job's scratch is retained.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, Mapping

from gen2.core import canonical
from gen2.core.control import StagedBytes
from gen2.core.gateway_capture import RetainedExchange
from gen2.exec.common import Refused

INDEX, MEDIA = "exchanges.json", "application/json"
FORM = "canonical reconstruction of the client's parsed exchange; not the raw transport octets"
Stage = Callable[[str, bytes, str], Mapping]


def build(result: Mapping) -> dict[str, tuple[bytes, bytes]]:
    """{gateway_call_ref: (request bytes, response bytes)} for every captured call of a discovery result."""
    inv, attempt, built = result["invocation_id"], result["attempt"], {}
    for search in result["searches"]:
        out = search["out"]
        for page in out["pages"]:
            if page["call_ref"] is None:
                continue
            ref = f"gw-call:{page['call_ref']}"
            observed = [o for o in out["observations"] if o["observation"]["gateway_call_ref"] == ref and isinstance(o["observation"]["request"], dict)]
            if not observed:
                continue
            lane = (page["sent"].get("lanes") or [None])[0]
            asked = next((o for o in observed if o["observation"]["lane"] == lane), observed[0])
            records, seen = [], set()
            for o in observed:
                for record in o["records"]:
                    if record.get("identity") not in seen:
                        seen.add(record.get("identity"))
                        records.append(record)
            response = {"retained_form": FORM, "request_type": page["sent"]["request_type"],
                        "observation": {"captured": True, "call_ref": page["call_ref"], "invocation_id": inv, "attempt": attempt},
                        "effective_request": page["effective_request"],
                        "lanes": [{"source": o["observation"]["lane"], "coverage": o["observation"]["coverage_state"],
                                   "completeness": o["observation"]["completeness"], "retrieved": [e["provider_record_id"] for e in o["retrieval_events"]]}
                                  for o in observed],
                        "records": records}
            pair = (canonical.canonical_bytes(asked["observation"]["request"]), canonical.canonical_bytes(response))
            if built.setdefault(ref, pair) != pair:
                raise Refused(f"{ref} was answered two different ways in one result")
    return built


def stage_all(stage: Stage, topic_id: str, built: Mapping[str, tuple[bytes, bytes]]) -> list[dict]:
    """Stage every exchange in the topic's spool; the index entries (call ref, request ref, response ref), in call order."""
    entries = []
    for ref, (request, response) in sorted(built.items()):
        refs = [dict(stage(topic_id, data, MEDIA)) for data in (request, response)]
        for data, staged in zip((request, response), refs):
            if staged.get("content_hash") != canonical.bytes_digest(data) or staged.get("size_bytes") != len(data):
                raise Refused(f"{ref}: the spool's reference is not the staged bytes'")
        entries.append({"gateway_call_ref": ref, "request": refs[0], "response": refs[1]})
    return entries


def write_index(scratch: Path | str, invocation_id: str, attempt: int, entries: list[dict]) -> None:
    """exchanges.json in the job's scratch; identical content on every replay, replaced whole (never half-written)."""
    data = canonical.canonical_bytes({"index_version": "exchanges/1", "invocation_id": invocation_id, "attempt": attempt, "exchanges": entries})
    target = Path(scratch) / INDEX
    temp = target.with_name(INDEX + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, target)


class ExchangeIndex:
    """Reads staged exchanges back by call ref from the retained scratch indexes of this topic's discovery jobs."""

    def __init__(self, spool: StagedBytes, topic_id: str, scratches: Callable[[], Iterable[Path | str]]) -> None:
        self._spool, self._topic, self._scratches = spool, topic_id, scratches

    def _entries(self) -> Iterable[tuple[Mapping, Mapping]]:
        for scratch in self._scratches():
            path = Path(scratch) / INDEX
            if path.is_symlink() or not path.is_file():
                continue
            try:
                document = canonical.parse_json_strict(path.read_bytes())
            except (OSError, ValueError):
                continue
            for entry in document.get("exchanges", []):
                yield document, entry

    def _bytes(self, ref: Mapping) -> bytes | None:
        data = self._spool.read(ref["content_hash"], topic_id=self._topic)
        return data if data is not None and canonical.bytes_digest(data) == ref["content_hash"] and len(data) == ref["size_bytes"] else None

    def response(self, gateway_call_ref: str) -> tuple[Mapping, bytes] | None:
        """artifacts.Exchanges: (the response's artifact reference, its bytes), or None when nothing verified is staged."""
        for _, entry in self._entries():
            if entry["gateway_call_ref"] == gateway_call_ref and (data := self._bytes(entry["response"])) is not None:
                return entry["response"], data
        return None

    def read(self, *, topic_id: str, invocation_id: str, attempt: int, gateway_call_ref: str) -> RetainedExchange | None:
        """core.gateway_capture.CaptureReader: both documents of one captured call, verified, or None."""
        if topic_id != self._topic:
            return None
        for document, entry in self._entries():
            if (document["invocation_id"], document["attempt"], entry["gateway_call_ref"]) == (invocation_id, attempt, gateway_call_ref):
                request, response = self._bytes(entry["request"]), self._bytes(entry["response"])
                if request is not None and response is not None:
                    return RetainedExchange(topic_id, invocation_id, attempt, gateway_call_ref, request, response)
        return None
