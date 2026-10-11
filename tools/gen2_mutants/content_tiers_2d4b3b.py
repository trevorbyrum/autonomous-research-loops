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
    expression = f"length(trim(json_extract(r.value, '$.{field}'), char(9,10,13,32))) > 0"
    change(field + "-nonblank", expression, "1 = 1", "shapes")
    change(field + "-whitespace", f"trim(json_extract(r.value, '$.{field}'), char(9,10,13,32))",
        f"json_extract(r.value, '$.{field}')", "shapes")
change("full-text-ceiling", "> 0 THEN 3", "> 0 THEN 4", "reproduction")
change("abstract-ceiling", "> 0 THEN 2", "> 0 THEN 3", "verdicts")
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
