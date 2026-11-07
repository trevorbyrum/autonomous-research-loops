"""Trusted input assembly: the discovery input's proposals and their proposer come from one receipt-verified committed outcome.

Trace: Astra #127 F1 and #125 F2 (a proposal reference is execution provenance, so it is bound, not supplied); 2e2-min design
O13.1; INVARIANTS C-9, C-12. The assembler (host side, in the station) reads the proposing invocation's committed
`final_outcome` receipt from the Router, reads those exact bytes from the topic spool, and verifies them with
`requests.intake` (digest, then the document's own invocation and topic, then the proposals). The child re-runs the same
intake on the bytes in its digest-pinned input, so a separately supplied proposer or proposal list is refused.
Oracle: the Router's receipt row (operation_id, invocation_id, topic_id, payload_digest, operation_kind). Limits: the Router
read is `topic_records` over `operation_receipts`, which the route's allow-list does not carry yet (gen2/router/accounting.py
TOPIC_FAMILIES, lane A): until it does, the Router refuses that family and this assembler has nothing to read from it. It trusts
the Router's rows and the spool's hash check; it decides nothing about which proposals are worth running.
"""
from __future__ import annotations

from typing import Callable, Mapping, Protocol, Sequence

from gen2.core.control import StagedBytes
from gen2.discovery import requests
from gen2.exec.common import Refused


class Receipts(Protocol):
    def receipt(self, invocation_id: str) -> Mapping:
        """The invocation's one committed final_outcome receipt row, or Refused."""


class RecordsReader(Protocol):
    def topic_records(self, request: Mapping) -> dict:
        """The Router's trusted read: {topic_id, families} -> {status: ok, topic_id, records: {family: [row, ...]}}."""


class TopicReceipts:
    """Receipts from the Router's trusted `topic_records` read (family `operation_receipts`)."""

    def __init__(self, reader: RecordsReader, topic_id: str) -> None:
        self._reader, self._topic = reader, topic_id

    def receipt(self, invocation_id: str) -> Mapping:
        answer = self._reader.topic_records({"topic_id": self._topic, "families": ["operation_receipts"]})
        if answer.get("status") != "ok" or answer.get("topic_id") != self._topic or "operation_receipts" not in answer.get("records", {}):
            raise Refused(f"topic_records gave no operation_receipts: {answer.get('reason', answer.get('status'))}")
        rows = [r for r in answer["records"]["operation_receipts"]
                if r["invocation_id"] == invocation_id and r["operation_kind"] == "final_outcome"]
        if len(rows) != 1:
            raise Refused(f"{invocation_id} has {len(rows)} committed final outcomes, not exactly one")
        return rows[0]


def assemble(receipts: Receipts, spool: StagedBytes, topic_id: str, proposing_invocation_id: str, validate: Callable[[str, object], None],
             max_bytes: int, only: Sequence[str] | None = None) -> dict:
    """The `committed` (and `only`) part of a discovery input's view: the receipt, and the exact committed bytes it names."""
    receipt = receipts.receipt(proposing_invocation_id)
    if (receipt["invocation_id"], receipt["topic_id"]) != (proposing_invocation_id, topic_id):
        raise Refused("the receipt is another invocation's or topic's")
    payload = spool.read(receipt["payload_digest"], topic_id=topic_id)
    if payload is None:
        raise Refused("the committed payload is not staged for this topic")
    committed = requests.intake(payload, receipt, topic_id, max_bytes, validate)
    requests.select(committed, only)   # a name the committed payload lacks is refused before any input exists
    view = {"committed": {"payload": payload.decode("utf-8"), "receipt": {"invocation_id": receipt["invocation_id"], "payload_digest": receipt["payload_digest"]}}}
    return {**view, "only": list(only)} if only is not None else view
