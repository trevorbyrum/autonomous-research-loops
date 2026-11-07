"""Proposal intake and the proposal-to-gateway-request builder.

Trace: 2e2-min design O13.1, O13.2; Astra T11 decision 3; RG-4 (a refused list is refused, never truncated into
fewer searches). Oracle: the committed payload's byte digest and the search-proposal schema (injected check);
the gateway's own field table (research_gateway/app.py FIELD_TYPES), restated as FILTERS. Limits: it picks no
lane and no query; the model's proposal does, and the gateway's grant decides what the lane may do.
"""
from __future__ import annotations

from typing import Callable, Mapping, NamedTuple

from gen2.core import canonical
from gen2.core.search_proposals import gateway_request as build_request
from gen2.exec.common import Refused

MAX_PROPOSALS = 32


class Committed(NamedTuple):
    """The proposals of one committed outcome and the invocation that committed them: both from the same bytes."""
    invocation_id: str
    proposals: list


def intake(payload: bytes, receipt: Mapping, topic_id: str, max_bytes: int, validate: Callable[[str, object], None]) -> Committed:
    """The `search_proposals` of a committed outcome payload, and the invocation that committed it, once the bytes are the
    receipt's: their digest is the receipt's, and the document's own invocation and topic are the receipt's and this
    topic's (a payload cannot be replayed under another invocation). The proposer is read from those bytes, never supplied
    beside them (Astra #127 F1). An oversize payload or list, a repeated proposal id, or a proposal the schema refuses is
    refused whole."""
    if canonical.bytes_digest(payload) != receipt["payload_digest"]:
        raise Refused("the payload is not the receipt's")
    if len(payload) > max_bytes:
        raise Refused(f"the payload is {len(payload)} bytes, over the {max_bytes} cap")
    document = canonical.parse_json_strict(payload)
    if (document.get("invocation_id"), document.get("topic_id")) != (receipt["invocation_id"], topic_id):
        raise Refused("the payload names another invocation or topic than its receipt")
    proposals = document.get("search_proposals", [])
    if not isinstance(proposals, list) or len(proposals) > MAX_PROPOSALS:
        raise Refused(f"search_proposals must be a list of at most {MAX_PROPOSALS}")
    for proposal in proposals:
        validate("search-proposal", proposal)
    if len({p["proposal_id"] for p in proposals}) != len(proposals):
        raise Refused("a proposal id is repeated")
    return Committed(receipt["invocation_id"], proposals)


def gateway_request(proposal: Mapping) -> dict:
    """The gateway payload for one proposal: the same proposal always gives the same request (and so the same
    request identity). A filter the request type does not take is refused, not dropped."""
    try:
        return build_request(proposal)
    except ValueError as error:
        raise Refused(str(error)) from None


def pages(proposal: Mapping) -> int:
    """Only a find pages; its page cap is the proposal's."""
    return proposal["page_cap"] if proposal["request_type"] == "find" else 1
