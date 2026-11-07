"""Challenge view and builder: a search round, then counterevidence/explanation/adjudication records and promotions.

Trace: 2e2-min design O16.1, O16.2; Astra T11 F4 (a counterevidence label is not the required search: pass 1 proposes
the searches, the existing discovery job runs them, pass 2 records only what the retained observations support);
INVARIANTS E-6, RG-4 (coverage is read from recorded observations, never the model's word), C-9 (the model authors no
id, hash or pin), V-4 (promotions are proposals; the store gate decides). Oracle: outcome-document and
completion-record schemas, and the router's own checks (producer != challenger, load-bearing subject, evidence refs).
Limits: `none_found` is written only when the claim has searches, the model cites only those searches, and each is a
clean, complete observation with a staged response; otherwise the record is `incomplete`, or absent when no response is
staged at all (a record needs one artifact, and none is invented). A search belongs to a proposal when lane and query
equal the proposal's: T13 must keep that identity stable. The judgment's outcome words are mapped, not interpreted:
resolved/unresolved/unknown become none_found/counterevidence_found/incomplete, explanation_rejected/stands/incomplete,
verdict_upheld/verdict_overturned/(no record). Only a provisional claim is promoted (the store gate refuses a repeat). Open review episodes are given by the caller (status carries them).
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping, Protocol, Sequence

from gen2.core import canonical
from gen2.exec.common import Refused, derived_id, scaffold

PROPOSER = "checkpoint.challenge"
FAMILIES = ("claims", "verification_receipts", "registry_dispositions", "search_observations")
ADVERSE = ("partially_supports", "does_not_support")
CLEAN = ("searched_ok", "searched_empty")
ROW_CAP = 200
OBSERVATION_KEYS = ("observation_id", "coverage_state", "completeness", "result_count", "error_class")
COUNTER = {"resolved": "none_found", "unresolved": "counterevidence_found", "unknown": "incomplete"}
EXPLANATION = {"resolved": "explanation_rejected", "unresolved": "explanation_stands", "unknown": "incomplete"}
ADJUDICATION = {"resolved": "verdict_upheld", "unresolved": "verdict_overturned"}   # unknown: no record, the gate stays open
Stage = Callable[[bytes, str], Mapping]


class Exchanges(Protocol):
    def response(self, gateway_call_ref: str) -> tuple[Mapping, bytes] | None:
        """(artifact_ref, bytes) staged for this topic's retained gateway response, or None."""


def _latest_claims(rows: Iterable[Mapping], invocation_id: str) -> list[Mapping]:
    latest: dict[str, Mapping] = {}
    for row in rows:
        if row["claim_id"] not in latest or row["revision"] > latest[row["claim_id"]]["revision"]:
            latest[row["claim_id"]] = row
    return [c for _, c in sorted(latest.items())
            if c["load_bearing"] and c["status"] not in ("rejected", "superseded") and c["producer_invocation_id"] != invocation_id]


def _matches(proposal: Mapping, row: Mapping) -> bool:
    return row["lane"] == proposal["lane"] and row["request"]["request"].get("query") == proposal["query"]


def challenge_view(admission: Mapping, records: Mapping[str, Sequence[Mapping]], text_of: Callable[[str], str], *, invocation_id: str,
                   review_episodes: Sequence[str], proposals: Sequence[Mapping], as_of: str, truncation: list[dict]) -> dict:
    """Pass 1 (no `proposals`): the claims to challenge. Pass 2: the same, plus what each proposed search recorded."""
    if admission.get("context") != "contract/1":
        raise Refused("a challenge view needs a contract/1 admission")
    claims = _latest_claims(records["claims"], invocation_id)
    if len(claims) > ROW_CAP:
        truncation.append({"family": "claims", "kept": ROW_CAP, "total": len(claims)})
    claims = claims[:ROW_CAP]
    keys = {(c["claim_id"], c["revision"]) for c in claims}
    superseded = {r["supersedes_id"] for r in records["registry_dispositions"]}
    searches = []
    for proposal in proposals:
        ref = proposal.get("subject_ref")
        if ref is None or not any(c["claim_id"] == ref["claim_ref"] for c in claims):
            raise Refused(f"proposal {proposal.get('proposal_id')} tests no claim of this view")
        searches.append({"proposal_id": proposal["proposal_id"], "claim_ref": ref["claim_ref"], "lane": proposal["lane"],
                         "query": proposal["query"],
                         "observations": [{**{k: row.get(k) for k in OBSERVATION_KEYS}, "gateway_call_ref": row.get("gateway_call_ref")}
                                          for row in records["search_observations"] if _matches(proposal, row)]})
    return {"as_of": as_of, "pass": 2 if proposals else 1, "review_episodes": sorted(review_episodes),
            "claims": [{"claim_ref": c["claim_id"], "revision": c["revision"], "tier": c["required_access_tier"], "status": c["status"], "text": text_of(c["text_ref"])}
                       for c in claims],
            "adverse_receipts": [{"receipt_id": r["verification_receipt_id"], "claim_ref": r["claim_id"], "claim_revision": r["claim_revision"],
                                  "verdict": r["verdict"]}
                                 for r in records["verification_receipts"] if (r["claim_id"], r["claim_revision"]) in keys and r["verdict"] in ADVERSE],
            "contradictions": [{"disposition_id": r["disposition_id"], "subject": r["subject"]}
                               for r in records["registry_dispositions"] if r["registry_kind"] == "contradiction"
                               and r["disposition"] != "resolved" and r["disposition_id"] not in superseded],
            "searches": searches}


def _proposals(work: Mapping, judgment: Mapping) -> list[dict]:
    claims = {c["claim_ref"] for c in work["view"]["claims"]}
    out = []
    for proposal in judgment["search_proposals"]:
        ref = proposal.get("subject_ref")
        if ref is None or ref["claim_ref"] not in claims:
            raise Refused(f"search proposal {proposal.get('proposal_id')} must name a claim of the view")
        out.append({**proposal, "proposer": PROPOSER})   # the model keeps its content and loses its attribution (C-9)
    return out


def _by_ref(items: Sequence[Mapping], key: str, wanted: str, what: str) -> Mapping:
    for item in items:
        if item[key] == wanted:
            return item
    raise Refused(f"{what} {wanted} is not in the view")


def make_builder(exchanges: Exchanges, stage: Stage) -> Callable[[Mapping, Mapping], dict]:
    """work-input/1 + judgment-challenge/1 -> outcome/1. `exchanges` and `stage` are the topic spool's."""

    def evidence(call_refs: Iterable[str]) -> list[Mapping]:
        refs = {}
        for call in call_refs:
            staged = exchanges.response(call) if call else None
            if staged is not None:
                ref, data = staged
                if canonical.bytes_digest(data) != ref["content_hash"]:
                    raise Refused("a staged response does not hash to its reference")
                refs[ref["content_hash"]] = dict(ref)
        return [refs[h] for h in sorted(refs)]

    def counterevidence(item: Mapping, view: Mapping, claim: Mapping) -> tuple[str, list[Mapping]] | None:
        mine = {s["proposal_id"]: s["observations"] for s in view["searches"] if s["claim_ref"] == claim["claim_ref"]}
        cited = set(item["searched"])
        if cited - set(mine):
            raise Refused(f"{claim['claim_ref']}: the judgment cites a search that is not one of this claim's")
        outcome = COUNTER[item["outcome"]]
        used = [o for name in (sorted(cited) or sorted(mine)) for o in mine[name]]
        refs = evidence(o["gateway_call_ref"] for o in used)
        clean = bool(cited) and bool(used) and all(mine[name] for name in cited) and all(
            o["coverage_state"] in CLEAN and o["completeness"] == "complete" and o["error_class"] is None for o in used)
        if outcome == "none_found" and not (clean and len(refs) == len({o["gateway_call_ref"] for o in used})):
            outcome = "incomplete"
        return (outcome, refs) if refs else None

    def build(work: Mapping, judgment: Mapping) -> dict:
        view, invocation, topic = work["view"], work["invocation_id"], work["topic_id"]
        if view["pass"] == 2 and judgment["search_proposals"]:
            raise Refused("pass 2 proposes no further searches")
        if judgment["search_proposals"]:
            return scaffold(invocation, topic, search_proposals=_proposals(work, judgment))
        pin = work["admission"]["contract"]["revision"]
        judged = canonical.canonical_bytes(judgment)
        own = [dict(stage(judged, "application/json"))]
        records = []

        def add(kind: str, subject: str, revision: int | None, outcome: str, summary: str, refs: list[Mapping]) -> None:
            records.append({"record_id": derived_id("cpl", invocation, kind, len(records)), "kind": kind, "contract_revision": pin,
                            "subject_ref": subject, "subject_revision": revision, "subject_hash": None,
                            "assessment": {"outcome": outcome, "summary": summary}, "evidence_refs": refs})
        for item in judgment["counterevidence"]:
            claim = _by_ref(view["claims"], "claim_ref", item["claim_ref"], "claim")
            result = counterevidence(item, view, claim)
            if result is not None:
                add("counterevidence_search", claim["claim_ref"], claim["revision"], result[0], item["summary"], result[1])
        for item in judgment["explanations"]:
            _by_ref(view["contradictions"], "disposition_id", item["disposition_id"], "contradiction")
            add("competing_explanation", item["disposition_id"], None, EXPLANATION[item["outcome"]], item["summary"], own)
        for item in judgment["adjudications"]:
            receipt = _by_ref(view["adverse_receipts"], "receipt_id", item["receipt_id"], "adverse receipt")
            if item["outcome"] in ADJUDICATION:
                add("verification_adjudication", receipt["receipt_id"], receipt["claim_revision"], ADJUDICATION[item["outcome"]], item["summary"], own)
        promoted = [_by_ref(view["claims"], "claim_ref", ref, "claim") for ref in judgment["promotions"]]
        if any(c["status"] != "provisional" for c in promoted):
            raise Refused("only a provisional claim is promoted")
        promotions = [{"claim_id": c["claim_ref"], "revision": c["revision"]} for c in promoted]
        return scaffold(invocation, topic, completion_records=records, claim_promotions=promotions,
                        review_closures=[{"episode_id": e} for e in view["review_episodes"]])
    return build
