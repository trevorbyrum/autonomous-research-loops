"""Each extraction admission predicate has a separate accepted raw control."""
from .base import Mutation

SCOPE = "verification_receipts_admitted_extraction"
TEST = "test_store_extraction_acquisitions.ExtractionDDLTest.test_"
MUTATIONS, CONTROLS = [], {}


def change(name, old, new, killer="selectors"):
    mid = "2D4B3C-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3c", name, (TEST + killer,), old=old, new=new, scope=SCOPE))
    CONTROLS[mid] = {"controls": [TEST + "control"],
        "why": "Separate accepted receipts of both extraction methods consume literal admitted work/version/verifier/hash/call/time/route operands; the extractor may differ from the acquirer. Raw SQL proves lineage only."}


change("verifier-method", "'verifier_extraction', 'validated_extraction'", "'validated_extraction'", "missing")
change("validated-method", "'verifier_extraction', 'validated_extraction'", "'verifier_extraction'", "missing")
change("existence", "AND NOT EXISTS (", "AND 0 AND NOT EXISTS (", "missing")
for name, expression in (("work", "a.work_id = NEW.work_id"), ("version", "a.source_version = NEW.source_version"),
        ("verifier", "a.verifier_invocation_id = NEW.verifier_invocation_id"), ("hash", "a.content_hash = NEW.obtained_content_hash"),
        ("call", "a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')"),
        ("time", "a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')"),
        ("route", "'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')")):
    change(name, expression, "1 = 1")
