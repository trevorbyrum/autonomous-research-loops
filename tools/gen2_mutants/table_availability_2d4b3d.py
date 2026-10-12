"""Paired mutations of every table admission predicate, across all methods."""
from .base import Mutation

SCOPE = "verification_receipts_table_availability"
TESTS = tuple("test_store_table_availability." + cls + ".test_" for cls in
    ("TableDDLTest", "ExtractionTableDDLTest", "ValidatedTableDDLTest"))
MUTATIONS, CONTROLS = [], {}


def change(name, old, new, killer, control="lower_table_control", tests=TESTS):
    mid = "2D4B3D-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3d", name, tuple(t + killer for t in tests), old=old, new=new, scope=SCOPE))
    CONTROLS[mid] = {"controls": [t + control for t in tests],
        "why": "Separate literal table/full-text or non-table/lower-tier receipts remain admitted; extraction declarations retain SQL 17's authority fence."}


change("truthful", "NEW.verdict <> 'cannot_assess_at_required_tier'", "1 = 1", "cannot_assess")
change("bibliographic", "'bibliographic', 'abstract'", "'abstract'", "insufficient")
change("abstract", "'bibliographic', 'abstract'", "'bibliographic'", "insufficient")
change("tier-diagnostic", "NEW.access_tier IN ('bibliographic', 'abstract')", "1 = 1", "tier_diagnostic", tests=TESTS[1:])
change("table", "AND EXISTS (", "AND 0 AND EXISTS (", "insufficient")
change("kind", "= 'table'", "= 'page'", "insufficient")
change("all-spans", "WHERE json_extract(s.value", "WHERE s.key = 0 AND json_extract(s.value", "mixed")
change("threshold", ") < 3", ") < 2", "insufficient")
change("comparison", ") < 3", ") <= 3", "lower_table_control", "non_table_control")
change("missing", ")), 3)", ")), 0)", "diagnostics", tests=TESTS[1:])
change("method", "NEW.extraction_method <> 'canonical_bytes'", "1 = 1", "lineage", tests=TESTS[:1])
change("independent-extractor", "NEW.extraction_method <> 'canonical_bytes'", "0", "insufficient", tests=TESTS[1:])
for name, expression in (("work", "a.work_id = NEW.work_id"), ("version", "a.source_version = NEW.source_version"),
        ("verifier", "a.verifier_invocation_id = NEW.verifier_invocation_id"),
        ("call", "a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')"),
        ("time", "a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')"),
        ("route", "'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')")):
    change(name, expression, "1 = 1", "lineage")
change("acquirer", "a.acquired_by_invocation_id = NEW.extraction_invocation_id", "1 = 1", "lineage", tests=TESTS[:1])
change("hash", "a.content_hash = NEW.obtained_content_hash", "1 = 1", "diagnostics", tests=TESTS[1:])
