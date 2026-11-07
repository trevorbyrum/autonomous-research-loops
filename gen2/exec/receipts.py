"""Verify builder: the verification judgment plus retained bytes become receipts, detailed-check records and quote checks.

Trace: 2e2-min design O15.4; flow S4.8-9; INVARIANTS V-3 (canonical retained bytes are reusable), V-4, V-6 (the engine computes the
match: the builder supplies only the quote and its byte span), V-8 (attributed detailed checks), RG-5 (the verifier is its own
invocation, under its own capability); Astra T11 decision 5. Oracle: verification-receipt, detailed-check-record and quote-check
schemas, and the router's own commit (tests/test_exec_receipts_commit.py). Limits:
- A span is a half-open BYTE range into the staged response bytes (a canonical reconstruction of the client's parsed exchange, not
  transport octets), found structurally inside the selected record's `abstract` string (gen2/exec/spans.py). An escape elsewhere in
  the abstract does not matter; a quote that itself contains an escaped character is refused, never approximated.
- The system, not the model, decides a tier shortfall: a claim whose required tier no source's retained text reaches gets a
  `cannot_assess_at_required_tier` receipt over the examined bytes, whatever the judgment said; the router writes the hold.
- `verifier_capability_id` is bearer authority (with the invocation id it can commit as the invocation), so the child never sees
  it: the receipts omit it and the supervisor fills it from the journal grant before it stages and hashes the outcome. No hash
  computed here covers that field (ids are derived from the invocation and index, and evidence hashes cover assessments only).
  The quote normalization version is the composition root's (the router's quote_matching.NORMALIZATION joined with "/").
- One receipt per claim, bound to one source. A judgment that contradicts itself (support with a failed or unperformed check) or
  quotes text that is not in the retained text is refused whole: nothing is repaired.
"""
from __future__ import annotations

from typing import Callable, Mapping

from gen2.core import canonical
from gen2.exec import artifacts
from gen2.exec.spans import locate
from gen2.exec.common import Refused, derived_id, scaffold
from gen2.exec.verify import TIERS

KINDS = ("numeric_units", "denominators", "negation", "qualifications")
PROJECTION = {"succeeded": "checked_ok", "failed": "checked_problem", "not_applicable": "not_applicable", "not_checked": "not_checked", "unavailable": "unavailable"}
PERFORMED = ("succeeded", "failed", "not_applicable")
ALLOWED = {"supports": ("succeeded", "not_applicable"), "partially_supports": PERFORMED}
LEAD = {"numeric_units": "Quantities and unit interpretation", "denominators": "Population or base", "negation": "Polarity and scope", "qualifications": "Limiting context"}
BLANK = "".join(chr(c) for c in (*range(9, 14), 32, 133, 160))


def _span(start: int, end: int, locator: str) -> dict:
    return {"start": start, "end": end, "locator": {"kind": "section", "value": locator[:500] or "abstract"}}


def make_builder(stage: artifacts.Stage, bytes_of: Callable[[str], bytes], *, normalization: str) -> Callable[[Mapping, Mapping], dict]:
    """The job's Builder for verification/verify. Pure: it reads the view and `bytes_of(content_hash)`, the retained response the parent set
    aside in the job's scratch (digest-checked)."""

    def build(work: Mapping, judgment: Mapping) -> dict:
        inv, view = work["invocation_id"], work["view"]
        claims = {c["claim_ref"]: c for c in view["claims"]}
        receipts, checks, quotes, seen = [], [], [], set()
        for n, item in enumerate(judgment["items"]):
            claim = claims.get(item["claim_ref"])
            if claim is None or item["claim_ref"] in seen:
                raise Refused(f"{item['claim_ref']}: not a claim of this view, or judged twice")
            seen.add(item["claim_ref"])
            receipt = _receipt(inv, n, work, claim, item, bytes_of, stage, normalization)
            receipts.append(receipt["doc"])
            checks += receipt["checks"]
            quotes += receipt["quotes"]
        return scaffold(inv, work["topic_id"], verification_receipts=receipts, detailed_check_records=checks, quote_checks=quotes)
    return build


def _receipt(inv, n, work, claim, item, bytes_of, stage, normalization) -> dict:
    required = TIERS.index(claim["tier"])
    ranked = sorted(claim["sources"], key=lambda s: -TIERS.index(s["content_tier"]))
    if not ranked:
        raise Refused(f"{claim['claim_ref']} has no source in the view")
    verdict = item["verdict"]
    reachable = [s for s in ranked if TIERS.index(s["content_tier"]) >= required]
    if not reachable:
        verdict, quotes_in = "cannot_assess_at_required_tier", []   # the system's finding, whatever the judgment said (no silent downgrade)
    else:
        quotes_in = item["cited_spans"] if verdict in ("supports", "partially_supports", "does_not_support") else []
    outcomes = {k: item["checks"][k]["outcome"] for k in KINDS}
    if verdict in ALLOWED and any(o not in ALLOWED[verdict] for o in outcomes.values()):
        raise Refused(f"{claim['claim_ref']}: a {verdict} verdict needs every check in {ALLOWED[verdict]}, not {sorted(set(outcomes.values()))}")
    if verdict in ("supports", "partially_supports") and not quotes_in:
        raise Refused(f"{claim['claim_ref']}: a {verdict} verdict needs a cited quote")
    pool = reachable or ranked
    source = next((s for s in pool if all(q["quote"] in (s["content"] or "") for q in quotes_in)), None)
    if source is None:
        raise Refused(f"{claim['claim_ref']}: no single retained source contains every cited quote")
    ref, data = dict(source["artifact_ref"]), bytes_of(source["artifact_ref"]["content_hash"])
    if canonical.bytes_digest(data) != ref["content_hash"]:
        raise Refused(f"{source['work_id']}: the set-aside response does not hash to the view's reference")
    base = {"claim_id": claim["claim_ref"], "claim_revision": claim["revision"], "work_id": source["work_id"], "source_version": source["source_version"]}
    quote_rows, spans = [], []
    for k, cited in enumerate(quotes_in):
        start, end = locate(data, source["identity"], source["content"], cited["quote"])
        spans.append(_span(start, end, cited["locator"]))
        quote_rows.append({"check_id": derived_id("qck", inv, f"quote{n}", k), **base, "artifact_ref": ref, "quoted_text": cited["quote"], "span_start": start, "span_end": end})
    if not spans:   # nothing quoted: the span names the bytes that were examined
        spans = [_span(0, len(data), "examined retained response")]
    records_out, entries = [], {}
    for kind in KINDS:
        outcome, note = outcomes[kind], item["checks"][kind]["note"]
        if outcome in PERFORMED and not note.strip(BLANK):
            raise Refused(f"{claim['claim_ref']}: the {kind} check is {outcome} with no note")
        entry = {"outcome": outcome}
        if outcome in PERFORMED:
            assessment = {**base, "source_artifact_hash": ref["content_hash"], "examined_artifact_ref": ref, "cited_spans": spans, "context_spans": [],
                          "kind": kind, "outcome": outcome, "method": "attributed-assessment/1", "assessment": note,
                          "context_examined": f"{LEAD[kind]}: {note}", "applicability_reason": note if outcome == "not_applicable" else ""}
            record_id = derived_id("chk", inv, f"check{n}", KINDS.index(kind))
            records_out.append({"check_id": record_id, "assessment": assessment, "evidence_ref": artifacts.stage_bytes(stage, canonical.canonical_bytes(assessment), "application/json")})
            entry["record_id"] = record_id
        entries[kind] = entry
    matched = bool(quote_rows)
    doc = {"receipt_version": "verification-receipt/2", "verification_receipt_id": derived_id("ver", inv, "receipt", n), "topic_id": work["topic_id"],
           "claim": {"claim_id": claim["claim_ref"], "claim_revision": claim["revision"]}, "source": {"work_id": source["work_id"], "source_version": source["source_version"]},
           "cited_spans": spans, "obtained_content_hash": ref["content_hash"], "access_tier": source["content_tier"],
           "requested_for": {"use": "load_bearing", "required_access_tier": claim["tier"]},
           "acquisition": {**source["acquisition"], "cache_reuse": True},
           "extraction": {"method": "canonical_bytes", "extractor": "canonical/1", "produced_by_invocation_id": source["acquired_by"], "validation_ref": None},
           "producer_invocation_id": claim["producer"], "verifier_invocation_id": inv,
           "quote_check_id": quote_rows[0]["check_id"] if matched else None,
           "checks": {"exact_quote": {"status": "matched" if matched else "not_applicable", "normalization_version": normalization if matched else "none/1",
                                      "source_artifact_hash": ref["content_hash"]}, **{k: PROJECTION[o] for k, o in outcomes.items()}},
           "detailed_checks": entries, "adjudication": None, "verdict": verdict, "verified_at": view_time(work)}
    return {"doc": doc, "checks": records_out, "quotes": quote_rows}


def view_time(work: Mapping) -> str:
    return work["view"]["as_of"]
