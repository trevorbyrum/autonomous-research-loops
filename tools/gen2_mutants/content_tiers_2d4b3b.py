"""Canonical content predicates, each paired with a separately accepted receipt."""
from .base import Mutation

SCOPE = "verification_receipts_canonical_content_tier"
TEST = "test_store_content_tiers.ContentDDLTest.test_"
MUTATIONS, CONTROLS = [], {}


def change(name, old, new, killer, control="lower_tier_control", scope=SCOPE):
    mid = "2D4B3B-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3b", name, (TEST + killer,), old=old, new=new, scope=scope))
    CONTROLS[mid] = {"controls": [TEST + control],
        "why": "A separate raw canonical receipt is accepted at a literal recorded ceiling or below it; raw SQL proves relationships/content shape, not byte authentication."}


change("method", "NEW.extraction_method = 'canonical_bytes'", "0", "verdicts")
change("comparison", ") > coalesce((", ") >= coalesce((", "full_text_control")
change("record", "= a.provider_record_id", "IS NOT NULL", "record_identity")
change("observation", "USING (observation_id)", "ON 1 = 1", "availability")
change("availability", "o.coverage_state = 'searched_ok'", "1 = 1", "availability")
change("kind", "json_extract(r.value, '$.kind') = 'full_text'", "1 = 1", "kind")
for field in ("text", "abstract"):
    change(field + "-type", f"json_type(r.value, '$.{field}') = 'text'", "1 = 1", "shapes")
    expression = f"json_extract(r.value, '$.{field}') GLOB (SELECT pattern FROM recorded_nonblank_v1)"
    change(field + "-nonblank", expression, "1 = 1", "shapes")
    change(field + "-whitespace", expression, f"length(json_extract(r.value, '$.{field}')) > 0", "shapes")
change("full-text-ceiling", "recorded_nonblank_v1) THEN 3", "recorded_nonblank_v1) THEN 4", "reproduction")
change("abstract-ceiling", "recorded_nonblank_v1) THEN 2", "recorded_nonblank_v1) THEN 3", "verdicts")
change("bibliographic-ceiling", "ELSE 1 END)", "ELSE 3 END)", "kind")
change("bibliographic-rank", "WHEN 'bibliographic' THEN 1", "WHEN 'bibliographic' THEN 4", "bibliographic_control", "full_text_control")
for name, old, new, killer in (("abstract", "2", "0", "shapes"),
        ("full_text", "3", "0", "kind"), ("reproduced", "4", "0", "reproduction")):
    change(name + "-rank", f"WHEN '{name}' THEN {old}", f"WHEN '{name}' THEN {new}", killer)
for name, expression in (("json", "json_valid(CAST(a.response_bytes AS TEXT))"),
        ("array", "json_type(CAST(a.response_bytes AS TEXT), '$.records') = 'array'"), ("object", "r.type = 'object'")):
    change(name, expression, "0", "full_text_control", "bibliographic_control")
for name, expression in (("work", "a.work_id = NEW.work_id"), ("version", "a.source_version = NEW.source_version"),
        ("verifier", "a.verifier_invocation_id = NEW.verifier_invocation_id"),
        ("acquirer", "a.acquired_by_invocation_id = NEW.extraction_invocation_id"),
        ("call", "a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')"),
        ("time", "a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')"),
        ("route", "'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')")):
    change(name, expression, "1 = 1", "lineage")
# Missing acquisitions must still be diagnosed by SQL 15, in either trigger order.
mid = "2D4B3B-missing-admission-diagnostic"
MUTATIONS.append(Mutation(mid, "2d-4b3b", "preserve SQL 15 refusal", ("test_store_canonical_receipts.CanonicalDDLTest.test_missing_admission",),
    old=")), 4)", new=")), 0)", scope=SCOPE))
CONTROLS[mid] = CONTROLS["2D4B3B-method"]

# Counterfactual property sets, not just the originally reproduced characters.
change("unicode-space-set", "char(9) || '-' || char(13) || char(32,133,160,5760)\n  || char(8192) || '-' || char(8202) || char(8232,8233,8239,8287,12288)",
    "char(9,10,13,32)", "shapes", scope=None)
change("unicode-ignorable-set", "char(173,847,1564)", "char(65)", "shapes", scope=None)

PENDING = "test_pending_extraction_support."
FENCE = "claims_accepted_support_pending_extraction"


def pending(name, old, new, killer="PendingDDLTest.test_pending_methods", target="ddl", scope=FENCE):
    mid = "2D4B3B-pending-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3b-repair-1", name, (PENDING + killer,), old=old, new=new, target=target, scope=scope))
    CONTROLS[mid] = {"controls": [PENDING + ("PendingRouterTest.test_canonical_support_control" if target != "ddl" else "PendingDDLTest.test_canonical_support_control")],
        "why": "An independently recorded canonical full-text receipt qualifies support; pending extraction declarations remain retained and do not clear attention."}


pending("activation", "NEW.status = 'accepted_support'", "0")
pending("method-verifier", "'verifier_extraction', 'validated_extraction'", "'validated_extraction'")
pending("method-validated", "'verifier_extraction', 'validated_extraction'", "'verifier_extraction'")
pending("existence", "AND NOT EXISTS (", "AND 0 AND NOT EXISTS (")
pending("authority", "c.extraction_method = 'canonical_bytes'", "1 = 1")
for name, old in (("claim", "c.claim_id = NEW.claim_id"), ("revision", "c.claim_revision = NEW.revision"), ("use", "c.use = 'load_bearing'"), ("verdict", "c.verdict = 'supports'")):
    pending(name, old, "1 = 1", "PendingDDLTest.test_canonical_distractors")
# The hold routing predicate appears in _needs_hold and pending classification;
# distinguish their exact expressions so each counterfactual removes one guard.
pending("hold", 'return doc["verdict"] != "supports" or doc["extraction"]["method"] != "canonical_bytes"',
    'return doc["verdict"] != "supports"', "PendingRouterTest.test_pending_methods", target="gen2/router/verification.py", scope=None)
pending("classification", 'pending = doc["verdict"] == "supports" and doc["extraction"]["method"] != "canonical_bytes"',
    "pending = False", "PendingRouterTest.test_pending_methods", target="gen2/router/verification.py", scope=None)

mid = "2D4B3B-pending-capture"
MUTATIONS.append(Mutation(mid, "2d-4b3b-repair-1", "pending receipt cannot preserve governed accepted support",
    ("test_store_capture_support.CaptureDDLTest.test_late_pending_cannot_preserve_support",),
    old="      AND v.extraction_method = 'canonical_bytes'\n", new=""))
CONTROLS[mid] = {"controls": ["test_store_capture_support.CaptureDDLTest.test_capture_control"],
    "why": "A separate canonical receipt binds the current governed capture and qualifies support."}

mid = "2D4B3B-pending-python-capture"
MUTATIONS.append(Mutation(mid, "2d-4b3b-repair-1", "Router capture support consumes an authoritative method",
    ("test_capture_support.RouterGuardTest.test_pending_cannot_borrow_historical_canonical",),
    old='and v["extraction_method"] == "canonical_bytes"', new='', target="gen2/router/evidence_writer.py"))
CONTROLS[mid] = {"controls": ["test_capture_support.RouterGuardTest.test_control"],
    "why": "The matching canonical receipt qualifies Router support with the independent SQL capture consumers removed."}
