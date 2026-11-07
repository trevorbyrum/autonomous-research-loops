"""Verification input: which claims need a verifier, and what the verifier reads (2e2-min T15, O15.2, O15.3).

Trace: flow S4.8-9; INVARIANTS V-3 (re-access reuses retained gateway bytes), V-4, V-8, RG-5; DEBT-051 (the retained exchange is
read through the exchange index, the production capture reader); Astra T11 decision 5. Oracle: the Router's rows, and the same
retained-lineage read the research builder commits source_artifacts from (`artifacts.retained`). Limits: selection is a query, not
a judgment (it never decides a claim is sufficient or settled); the acquisition triple and route are derived from retained rows,
never from the model; a claim with no retained source link is not selected, since there is nothing to check it against; the blank label is the router's own `nonblank`;
exclusion is `support.require_support`'s answer over the topic's rows, wired from gen2/app/support_gate.py.
"""
from __future__ import annotations

from typing import Callable, Mapping, Protocol, Sequence

from gen2.exec import artifacts, views
from gen2.exec.common import Exchanges, Refused, latest_revision

FAMILIES = ("claims", "claim_source_links", "verification_receipts", "source_artifacts", "works", "retrieval_events", "record_work_links",
            "search_observations", "detailed_check_records", "source_acquisitions", "quote_checks")   # the last three are the support predicate's operands
TIERS = ("bibliographic", "abstract", "full_text", "reproduced")
CHECK_KINDS = 4
RECEIPT_CAP = 64 // CHECK_KINDS   # one commit carries at most 64 detailed_check_records (outcome-document.schema.json), four per receipt


class Support(Protocol):
    """The router's own support predicates, wired by the composition root (gen2/app/support_gate.py): exec may not import the router."""
    def qualified(self, records: Mapping[str, Sequence[Mapping]]) -> Callable[[Mapping], bool]:
        """claim row -> True only when `support.require_support` accepts support for it over these rows; absent operands are False."""

    def nonblank(self, text: object) -> bool:
        """The router's own blank rule (`support.nonblank`)."""


def select(records: Mapping[str, Sequence[Mapping]], support: Support) -> list[Mapping]:
    """The latest revision of each provisional load-bearing claim that has a retained source link and that the router's support
    predicate does not already accept. A query, not a judgment: it holds no definition of support of its own."""
    qualified = support.qualified(records)
    latest = latest_revision(records["claims"])
    linked = {(link["claim_id"], link["claim_revision"]) for link in records["claim_source_links"]}
    return [claim for _, claim in sorted(latest.items())
            if claim["load_bearing"] and claim["status"] == "provisional" and (claim["claim_id"], claim["revision"]) in linked and not qualified(claim)]


def verify_view(admission: Mapping, records: Mapping[str, Sequence[Mapping]], support: Support, exchanges: Exchanges, text_of: Callable[[str], str | None],
                as_of: str, truncation: list[dict]) -> dict:
    """The verifier's view: each selected claim, and for each source it rests on the retained text and the acquisition triple."""
    if admission.get("context") != "contract/1":
        raise Refused("a verification view needs a contract/1 admission")
    committed = {(row["work_id"], row["source_version"]) for row in records["source_artifacts"]}
    claims, receipts = [], 0
    chosen = select(records, support)
    for claim in chosen:
        sources, seen = [], set()
        for link in records["claim_source_links"]:
            if (link["claim_id"], link["claim_revision"]) != (claim["claim_id"], claim["revision"]) or (link["work_id"], link["source_version"]) in seen:
                continue
            seen.add((link["work_id"], link["source_version"]))
            if (link["work_id"], link["source_version"]) not in committed:
                continue   # no committed source_artifacts row: there is nothing the router could bind a receipt to
            found = artifacts.retained(link["work_id"], records, exchanges)
            if found.ref["content_hash"] != link["source_version"]:
                raise Refused(f"{link['work_id']}: the retained response is not the version the claim's link names")
            text = views.abstract_of(found)
            usable = text is not None and support.nonblank(text)
            sources.append({"work_id": link["work_id"], "source_version": link["source_version"], "artifact_ref": dict(found.ref), "acquired_by": found.invocation_id, "identity": found.provider_record_id,
                            "content_tier": "abstract" if usable else "bibliographic", "content": text if usable else None,
                            "acquisition": {"gateway_call_ref": found.gateway_call_ref, "retrieved_at": found.captured_at, "route": f"gateway:{found.lane}"}})
        if not sources:
            continue
        if len(sources) > RECEIPT_CAP:
            raise Refused(f"{claim['claim_id']} rests on {len(sources)} retained sources, more than one commit's {RECEIPT_CAP} receipts; it needs a split, not silence")
        if receipts + len(sources) > RECEIPT_CAP:
            truncation.append({"family": "claims", "kept": len(claims), "total": len(chosen)})
            break
        receipts += len(sources)
        claims.append({"claim_ref": claim["claim_id"], "revision": claim["revision"], "tier": claim["required_access_tier"], "producer": claim["producer_invocation_id"],
                       "text": text_of(claim["text_ref"]), "sources": sources})
    return {"as_of": as_of, "claims": claims}
