"""Current-at-admission predicates, each with a separate traced control."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = "test_store_validation_current_registry.DDLCurrentRegistryTest.test_"
ROUTER = "test_validation_current_registry.RouterCurrentRegistryTest.test_"


def change(name, killer, old, new, target="ddl", control="current_control"):
    mid = "2D4B3E2CURRENT-" + name
    tests = RAW if target == "ddl" else ROUTER
    MUTATIONS.append(Mutation(mid, "2d-4b3e2 part 2 slice 2", name, (tests + killer,),
        old=old, new=new, target=target,
        scope="extraction_validations_v2_current_registry" if target == "ddl" else None))
    CONTROLS[mid] = {"controls": [tests + control],
        "why": "Separate admitted /2 validation reaches the current-at-admission predicate; retained history stays pinned."}


change("validator", "unrelated_current_extraction", "y.extraction_id = NEW.validator_extraction_id", "1 = 1")
change("pin", "stale_after_merge", "y.extractor_registry_version = (SELECT max(registry_version) FROM extractor_registry_revisions)", "1 = 1")
change("latest", "stale_after_merge", "max(registry_version)", "min(registry_version)", control="initial_control")
change("router-pin", "stale_router_guard", "if pin != current:", "if False:", "gen2/router/extractions.py")
change("router-validator", "target_current_router_guard", '{"extraction_id": record["validator_extraction_id"]}', '{"extraction_id": record["target_extraction_id"]}', "gen2/router/extractions.py", "initial_control")
change("router-latest", "stale_router_guard", 'current = max(', 'current = min(', "gen2/router/extractions.py", "initial_control")
change("router-dispatch", "stale_router_guard", 'if table == "extraction_validations_v2":', 'if False:', "gen2/router/extractions.py")
