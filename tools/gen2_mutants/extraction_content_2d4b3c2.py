"""Paired extraction ceiling predicates, including the shared SQL 16 rule."""
from dataclasses import replace

from .base import Mutation
from . import content_tiers_2d4b3b as shared

SCOPE = "verification_receipts_extraction_content_tier"
TESTS = tuple("test_store_extraction_content_tiers." + cls + ".test_"
    for cls in ("ExtractionContentDDLTest", "ValidatedContentDDLTest"))
MUTATIONS, CONTROLS = [], {}


def change(name, old, new, killer, control="lower_tier_control", tests=TESTS):
    mid = "2D4B3C2-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3c2", name, tuple(t + killer for t in tests), old=old, new=new, scope=SCOPE))
    CONTROLS[mid] = {"controls": [t + control for t in tests],
        "why": "Separate literal recorded-content controls admit both pending methods at or below the selected record's ceiling; SQL 17 still refuses support authority."}


for method, test in zip(("verifier_extraction", "validated_extraction"), TESTS):
    remaining = "validated_extraction" if method == "verifier_extraction" else "verifier_extraction"
    change(method, "'verifier_extraction', 'validated_extraction'", "'" + remaining + "'", "verdicts", tests=(test,))
change("comparison", ") > coalesce((", ") >= coalesce((", "full_text_control")
change("bibliographic-rank", "WHEN 'bibliographic' THEN 1", "WHEN 'bibliographic' THEN 4", "bibliographic_control", "full_text_control")
for name, rank, killer in (("abstract", 2, "shapes"), ("full_text", 3, "kind"), ("reproduced", 4, "reproduction")):
    change(name + "-rank", f"WHEN '{name}' THEN {rank}", f"WHEN '{name}' THEN 0", killer)
for name, expression in (("work", "a.work_id = NEW.work_id"), ("version", "a.source_version = NEW.source_version"),
        ("verifier", "a.verifier_invocation_id = NEW.verifier_invocation_id"),
        ("call", "a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')"),
        ("time", "a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')"),
        ("route", "'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')")):
    change(name, expression, "1 = 1", "lineage")
change("missing-diagnostic", ")), 4)", ")), 0)", "missing_diagnostic")
change("hash", "a.content_hash = NEW.obtained_content_hash", "1 = 1", "hash_diagnostic")

# Exercise each shared-view predicate through both extraction consumers too.
for mutant in shared.MUTATIONS:
    if mutant.scope is None and mutant.target == "ddl" and not mutant.mid.startswith("2D4B3B-pending-"):
        name = mutant.mid.removeprefix("2D4B3B-")
        killer = mutant.killers[0].rsplit(".test_", 1)[1]
        control = shared.CONTROLS[mutant.mid]["controls"][0].rsplit(".test_", 1)[1]
        mid = "2D4B3C2-shared-" + name
        MUTATIONS.append(replace(mutant, mid=mid, finding="2d-4b3c2", killers=tuple(t + killer for t in TESTS)))
        CONTROLS[mid] = {"controls": [t + control for t in TESTS], "why": "The shared SQL 16 content predicate is consumed by independently accepted receipts of each extraction method."}
