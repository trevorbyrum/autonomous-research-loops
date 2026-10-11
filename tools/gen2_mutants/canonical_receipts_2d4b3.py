"""Each consuming predicate has an isolated raw negative and accepted control."""
from .base import Mutation

SCOPE = "verification_receipts_admitted_canonical"
TEST = "test_store_canonical_receipts.CanonicalDDLTest.test_"
MUTATIONS, CONTROLS = [], {}


def change(name, old=None, new=None, killer="predicates", drop_trigger=None):
    mid = "2D4B3-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3", name, (TEST + killer,),
        old=old, new=new, scope=SCOPE if old else None, drop_trigger=drop_trigger))
    CONTROLS[mid] = {"controls": [TEST + "canonical_control"],
        "why": "A separately accepted raw canonical receipt consumes exact recorded source/version/hash/acquirer/verifier/call/time/route operands; no transport authenticity is inferred from raw SQL."}


change("admission", drop_trigger=SCOPE, killer="missing_admission")
change("method", "NEW.extraction_method = 'canonical_bytes'", "0", killer="missing_admission")
change("existence", "AND NOT EXISTS (", "AND 0 AND NOT EXISTS (", killer="missing_admission")
for name, expression in (
        ("work", "a.work_id = NEW.work_id"),
        ("version", "a.source_version = NEW.source_version"),
        ("verifier", "a.verifier_invocation_id = NEW.verifier_invocation_id"),
        ("hash", "a.content_hash = NEW.obtained_content_hash"),
        ("acquirer", "a.acquired_by_invocation_id = NEW.extraction_invocation_id"),
        ("call", "a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')"),
        ("time", "a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')"),
        ("route", "'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')")):
    change(name, expression, "1 = 1")
# These gates preserve SQL 03 diagnostics and its existing independently
# paired mutants; they are not substitute authentication guards.
for name, expression in (
        ("missing-call-diagnostic", "  AND json_extract(NEW.acquisition, '$.gateway_call_ref') IS NOT NULL\n"),
        ("missing-artifact-diagnostic", "  AND EXISTS (SELECT 1 FROM artifacts WHERE content_hash = NEW.obtained_content_hash)\n")):
    change(name, expression, "")
    MUTATIONS[-1] = Mutation(MUTATIONS[-1].mid, "2d-4b3", name,
        ("test_store_ddl_evidence.VerificationTest.test_producer_unvalidated_extraction_rejected",), old=expression, new="", scope=SCOPE)
