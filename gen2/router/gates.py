"""The three completion gates and the production profile evaluator (flow S7; G-3, G-4).

Pure functions over detached capture operands, plus the glue that selects the
completing profile and reads the sentinel bytes. A gate consumes recorded
judgments (completion records); it makes none, and never reads holds (D3).
"""
from gen2 import accounting as a
from gen2.accounting import stopping
from gen2.router import boundary, support
from gen2.router.accounting import records
from gen2.router.boundary import Refusal
from gen2.router.verification import ADVERSE

USABLE = ("current", "compatible")
COMPLETES = "completed_with_qualified_conclusions"


class CaptureRows:
    """Select-only rows over a detached capture, for support.require_support."""

    def __init__(self, raw) -> None:
        self._raw = raw

    def select(self, table: str, where: dict | None = None) -> list[dict]:
        return [r for r in records(self._raw, table) if all(r[k] == v for k, v in (where or {}).items())]


def _counts(record: dict, standing) -> bool:
    """Performed work whose contract standing is still usable."""
    return record["assessment"]["outcome"] != "incomplete" and standing(record["contract_revision"]) in USABLE


def verification_state(required, receipts, adjudications, supported):
    """D3 first: an adverse receipt without a counting adjudication makes the whole gate unknown."""
    keys = {(c["claim_id"], c["revision"]) for c in required}
    adverse = [r for r in receipts if (r["claim_id"], r["claim_revision"]) in keys and r["verdict"] in ADVERSE]
    named = {(r["subject_ref"], r["subject_revision"]): r for r in adjudications}
    relied = [named[k] for k in ((r["verification_receipt_id"], r["claim_revision"]) for r in adverse) if k in named]
    if any((r["verification_receipt_id"], r["claim_revision"]) not in named for r in adverse):
        return "unknown", relied
    return stopping.combine("all", tuple("satisfied" if c["status"] in ("accepted_support",) and supported(c) else "not_satisfied" for c in required)), relied


def challenge_state(required, contradictions, completions, standing):
    latest = {(r["kind"], r["subject_ref"], r["subject_revision"]): r for r in completions}  # capture order: newest wins
    subjects = [(("counterevidence_search", c["claim_id"], c["revision"]), True) for c in required]
    for d in contradictions:
        usable = standing(d.contract_revision) in USABLE
        if not usable or d.disposition != "resolved":
            subjects.append((("competing_explanation", d.disposition_id, None), usable))
    states, relied = [], []
    for key, usable in subjects:
        current = latest.get(key)
        if not usable or (current is not None and not _counts(current, standing)):
            states.append("unknown")
        elif current is None:
            states.append("not_satisfied")
        else:
            states.append("satisfied")
            relied.append(current)
    return stopping.combine("all", tuple(states)), relied


def coverage_state(inventory):
    uncertain = (a.candidate_units(inventory).retrieved_records.unknown_reason is not None
                 or any(w.state in ("indeterminate",) for w in a.window_standings(inventory)))
    return "unknown" if uncertain else "satisfied"


def _refs(relied) -> tuple[a.EvidenceReference, ...]:
    return tuple(sorted({a.EvidenceReference(**ref) for r in relied for ref in r["evidence_refs"]}, key=lambda ref: ref.content_hash))


def _sentinels(binding, spool, topic_id: str) -> stopping.KnownItems | None:
    if binding.evaluator not in ("known_item",):
        return None
    ref = binding.params["sentinel_set"]
    ids = boundary.normalize(boundary.staged(spool, ref["content_hash"], ref["size_bytes"], topic_id=topic_id, media_type="application/json"), "payload_invalid")
    if not isinstance(ids, list):
        raise Refusal("payload_invalid", "sentinel set is not an array")
    if not all(isinstance(i, str) and i for i in ids):
        raise Refusal("payload_invalid", "sentinel set holds a non-string or empty work id")
    seen = set()
    for work_id in ids:
        if work_id in seen:
            raise Refusal("payload_invalid", "sentinel set holds duplicate work ids")
        seen.add(work_id)
    return stopping.KnownItems(a.EvidenceReference(**ref), frozenset(ids))


def evaluate(inputs, spool, as_of: str) -> stopping.ProfileResult:
    """The production evaluator: every rule with an automatic binding, the three gates, the completing profile."""
    raw, inventory = inputs.raw, inputs.coverage.inventory
    contract = next(r for r in records(raw, "contract_revisions") if r["revision"] == inventory.current_contract_revision)
    context = stopping.Context(raw.topic_id, contract["revision"], contract["protocol_revision"])
    profiles = [p for p in contract["document"]["stopping_profiles"] if COMPLETES in p["permitted_outcomes"]]
    if len(profiles) != 1:
        raise Refusal("payload_invalid", f"{len(profiles)} stopping profiles permit completion ({', '.join(p['profile_id'] for p in profiles)}); exactly one is supported")
    profile, = profiles
    try:
        binding = stopping.bind_profile(profile)
    except ValueError as exc:
        raise Refusal("payload_invalid", str(exc)) from None
    rules = tuple(stopping.evaluate_binding(b, context, inventory, _sentinels(b, spool, raw.topic_id), pins=inputs.coverage.window_pins, as_of=as_of)
                  for b in binding.rules if b.evaluator)
    rows, standing = CaptureRows(raw), lambda revision: a.label_standing(inventory, revision)
    latest = {}
    for c in rows.select("claims"):
        latest[c["claim_id"]] = max(latest.get(c["claim_id"], c), c, key=lambda x: x["revision"])
    required = [c for c in latest.values() if c["load_bearing"] and c["status"] not in ("rejected", "superseded")]
    completions = rows.select("completion_records")
    adjudications = [r for r in completions if r["kind"] in ("verification_adjudication",) and _counts(r, standing)]
    contradictions = a.active_records(tuple(d for d in inventory.registry_dispositions if d.registry_kind in ("contradiction",)))

    def supported(claim: dict) -> bool:
        try:
            support.require_support(rows, claim, lambda doc: support.quote_support_valid(rows, doc))
        except Refusal:
            return False
        return True

    verification, verified = verification_state(required, rows.select("verification_receipts"), adjudications, supported)
    challenge, challenged = challenge_state(required, contradictions, completions, standing)
    gates = (stopping.GateResult(context, "load_bearing_verification_tiers", verification, _refs(verified)),
             stopping.GateResult(context, "challenge_pass_completed", challenge, _refs(challenged)),
             stopping.GateResult(context, "coverage_integrity", coverage_state(inventory), ()))
    return stopping.evaluate_profile(context, binding.profile, rules, gates, inventory=inventory)
