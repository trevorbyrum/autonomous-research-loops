"""The fixture agent for the offline whole-workflow run (2e2-min T18, O18.1): canned judgment writers, one per purpose.

Not collected as tests. `OfflineAgent` is the `agent` step of `gen2.exec.job.run`: it reads the staged `input.json`, picks the
responder for (kind, purpose), writes `out/judgment.json` and returns 0 (the wrapper contract: inputs/prompt.md and
inputs/input.json read, out/judgment.json written). Each responder reads the view it is given and answers from it, so a
changed input changes the answer; none writes an id, hash or pin (C-9). They prove wiring, not research quality.
Limits: the dossier job has no agent step. It is not the T6 HTTP
responder, which scripts the real runner's model dialogue; that one belongs to lane C's real-wrapper run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical

Responder = Callable[[Mapping], dict]
TIERS = ("bibliographic", "abstract", "full_text", "reproduced")
CLEAN = ("searched_ok", "searched_empty")


def proposal(n: int, lane: str, query: str, obligations=(), subject: str | None = None, request_type: str = "find") -> dict:
    return {"proposal_version": "search-proposal/1", "proposal_id": f"p{n}", "proposer": "primary", "lane": lane, "request_type": request_type,
            "query": query, "page_cap": 1, "obligation_ids": list(obligations), "rationale": "offline fixture search",
            **({"subject_ref": {"claim_ref": subject}} if subject else {})}


def scope(work: Mapping) -> dict:
    view = work["view"]
    base = {"judgment_version": "judgment-scope/1", "territory": "adolescent sleep and attention", "traditions": ["developmental psychology", "sleep medicine"],
            "candidate_facets": ["sleep duration", "school start time"], "deliberately_out": ["adult shift work"],
            "gap_skeleton": "Nothing was searched before this pass." if not view["observations"] else "The recorded searches describe the territory."}
    if view["observations"]:
        return {**base, "search_proposals": []}
    return {**base, "search_proposals": [proposal(1, "semanticscholar", "adolescent sleep attention"), proposal(2, "crossref", "adolescent sleep attention")]}


def research(work: Mapping) -> dict:
    view = work["view"]
    cited = [w for w in view["works"] if "abstract" in w][:1]
    obligation = view["obligations"][0]["obligation_id"]
    labels = sorted((view["contract"]["confidence_scheme"] or {}).get("labels", {}))
    criteria = {c["criterion_id"]: "met" for c in view["contract"]["eligibility_protocol"]["criteria"]}
    claims = [{"local_id": "c1", "text": f"The retained abstract of {w['identity']} states: {w['abstract']}", "load_bearing": True, "required_access_tier": "abstract",
               "sources": [{"work_id": w["work_id"], "obligation_id": obligation, "contribution": "answer"}]} for w in cited]
    return {"judgment_version": "judgment-research/1", "claims": claims,
            "screening": [{"work_id": w["work_id"], "stage": "abstract", "decision": "include", "reason_code": None, "criteria": criteria} for w in view["works"]],
            "obligations": [{"obligation_id": obligation, "outcome": "unknown", "confidence": labels[0] if labels else "low", "summary": "One retained abstract; no replication yet."}],
            "triggers": [], "search_proposals": [], "next_queue_state": "resting"}


def plain_quote(content: str, limit: int = 60) -> str:
    """The longest prefix of whole words, up to `limit` characters, that JSON would write unchanged (no quote mark, backslash or control
    character): the quote the retained text can be located by, byte for byte."""
    quote = ""
    for word in content.split():
        candidate = f"{quote} {word}".strip()
        if len(candidate) > limit or json.dumps(candidate)[1:-1] != candidate:
            break
        quote = candidate
    return quote


def verify(work: Mapping) -> dict:
    """One item per claim: supports it with a plain quote from the first source whose retained text reaches the claim's tier, else says the
    tier cannot be assessed (the builder makes that call from the view anyway)."""
    items = []
    for claim in work["view"]["claims"]:
        source = next((s for s in claim["sources"] if s["content"] and TIERS.index(s["content_tier"]) >= TIERS.index(claim["tier"])), None)
        quote = plain_quote(source["content"]) if source else ""
        note = lambda text: {"outcome": "succeeded", "note": text}   # noqa: E731
        applicable = {"outcome": "not_applicable", "note": "Nothing of this kind is stated in the claim."}
        items.append({"claim_ref": claim["claim_ref"], "verdict": "supports" if quote else "cannot_assess_at_required_tier",
                      "cited_spans": [{"quote": quote, "locator": "abstract"}] if quote else [],
                      "checks": {"numeric_units": applicable, "denominators": applicable, "negation": note("The claim and the quote have the same polarity."),
                                 "qualifications": note("The claim keeps the abstract's limits.")} if quote else
                                {k: {"outcome": "not_checked", "note": ""} for k in ("numeric_units", "denominators", "negation", "qualifications")}})
    return {"judgment_version": "judgment-verify/1", "items": items}


def challenge(work: Mapping) -> dict:
    view = work["view"]
    base = {"judgment_version": "judgment-challenge/1", "counterevidence": [], "explanations": [], "adjudications": [], "promotions": [], "search_proposals": []}
    if view["pass"] == 1:
        return {**base, "search_proposals": [proposal(n, "semanticscholar", f"counterevidence to: {c['text'][:60]}", subject=c["claim_ref"])
                                             for n, c in enumerate(view["claims"], 1)]}
    counter, promotions = [], []
    for claim in view["claims"]:
        mine = [s for s in view["searches"] if s["claim_ref"] == claim["claim_ref"]]
        clean = bool(mine) and all(o["coverage_state"] in CLEAN and o["completeness"] == "complete" for s in mine for o in s["observations"]) \
            and all(s["observations"] for s in mine)
        found = any(o["result_count"] for s in mine for o in s["observations"])
        counter.append({"claim_ref": claim["claim_ref"], "outcome": "unresolved" if found else "resolved" if clean else "unknown",
                        "summary": "The proposed searches recorded this.", "searched": [s["proposal_id"] for s in mine]})
        if clean and not found:
            promotions.append(claim["claim_ref"])
    return {**base, "counterevidence": counter, "promotions": promotions}


def review(work: Mapping) -> dict:
    return {"judgment_version": "judgment-review/1", "outcome": "sufficient", "summary": "The dossier answers the contract's one obligation within its stated limits."}


RESPONDERS: dict[tuple[str, str], Responder] = {("research_pass", "scope"): scope, ("research_pass", "research"): research, ("verification", "verify"): verify,
                                                ("checkpoint", "challenge"): challenge, ("checkpoint", "review"): review}


class OfflineAgent:
    """`agent(prompt, raw_input, out_dir) -> exit code`, recording each call."""

    def __init__(self, responders: Mapping[tuple[str, str], Responder] | None = None) -> None:
        self.responders, self.calls = dict(RESPONDERS if responders is None else responders), []

    def __call__(self, prompt: bytes, raw_input: bytes, out_dir: Path) -> int:
        work = canonical.parse_json_strict(raw_input)
        key = (work["kind"], work["purpose"])
        self.calls.append(key)
        if key not in self.responders:
            return 2
        (Path(out_dir) / "judgment.json").write_bytes(canonical.canonical_bytes(self.responders[key](work)))
        return 0
