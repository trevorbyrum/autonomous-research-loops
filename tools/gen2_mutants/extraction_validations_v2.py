"""Each successor predicate has a separate accepted, traced record control."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = "test_store_extraction_validations_v2.DDLV2Test.test_"
ROUTER = "test_extraction_validations_v2.RouterV2Test.test_"


def change(name, killer, old=None, new="1 = 1", scope=None, control="control", target="ddl", drop_trigger=None):
    mid = "2D4B3E2V2-" + name
    test = RAW if target == "ddl" else ROUTER
    MUTATIONS.append(Mutation(mid, "2d-4b3e2 continuation part 2", name, (test + killer,),
        old=old, new=new, scope=scope, target=target, drop_trigger=drop_trigger))
    CONTROLS[mid] = {"controls": [test + control],
        "why": ("Separate accepted successor record compares both tools under the validator extraction's pinned registry; SQL 17 remains fenced."
            if name.startswith("comparison-") else "Separate accepted successor record reaches the changed predicate; independence uses pinned families and SQL 17 remains fenced.")}


for name, predicate in (
        ("topic", "y.topic_id = x.topic_id"), ("work", "y.work_id = x.work_id"),
        ("version", "y.source_version = x.source_version"), ("event", "y.event_id = x.event_id"),
        ("lineage", "y.verifier_invocation_id = x.verifier_invocation_id"),
        ("comparison-author", "y.extracting_invocation_id = v.invocation_id"),
        ("target-verifier", "x.verifier_invocation_id = v.invocation_id"),
        ("extractor", "v.invocation_id <> x.extracting_invocation_id"), ("producer", "v.invocation_id <> s.invocation_id"),
        ("validator-topic", "v.topic_id = x.topic_id"), ("validator-kind", "v.kind = 'verification'"),
        ("admission", "v.admission_context = 'contract/1'"), ("parent", "v.parent_invocation_id IS NULL"),
        ("commit-author", "o.invocation_id = v.invocation_id"), ("commit-topic", "o.topic_id = x.topic_id"),
        ("commit-contract", "o.contract_revision = v.contract_revision")):
    change(name, "bindings", predicate, scope="extraction_validations_v2_binding")
for side in ("x", "y"):
    change(side + "-pin", "historical_pin" if side == "x" else "registered_validator_pin",
        f"t{side}.registry_version = {side}.extractor_registry_version", scope="extraction_validations_v2_registered")
for name, predicate in (
        ("validator", "y.extraction_id = NEW.validator_extraction_id"),
        ("revision", "tc.registry_version = y.extractor_registry_version"),
        ("identity", "tc.extractor_identity = x.extractor_identity"),
        ("target", "x.extraction_id = NEW.target_extraction_id")):
    change("comparison-" + name, "comparison_target_absent", predicate,
        scope="extraction_validations_v2_comparison_registry", control="cross_revision_control")
for side in ("x", "y"):
    change("comparison-" + side + "-own-pin", "two_identities_renamed",
        f"t{side}.registry_version = y.extractor_registry_version", f"t{side}.registry_version = x.extractor_registry_version",
        "extraction_validations_v2_method", control="cross_revision_control")
    change("comparison-" + side + "-identity", "cross_revision_control",
        f"t{side}.extractor_identity = {side}.extractor_identity",
        f"t{side}.extractor_identity = {'y' if side == 'x' else 'x'}.extractor_identity",
        "extraction_validations_v2_method", control="renamed_integrity_control")
change("independent-family", "same_family", "ty.family = tx.family", "0 = 1", "extraction_validations_v2_method")
change("replay-family", "method", "ty.family <> tx.family", "0 = 1", "extraction_validations_v2_method", control="integrity_control")
change("byte-comparison", "byte_comparison", "json_extract(y.output_ref, '$.content_hash') <> json_extract(x.output_ref, '$.content_hash')", "0 = 1", "extraction_validations_v2_method")
for name, predicate in (
        ("policy", "CHECK (policy_version = 2)"), ("method", "CHECK (method IN ('independent_extraction', 'same_family_replay'))"),
        ("outcome-domain", "CHECK (outcome IN ('succeeded', 'failed'))"),
        ("comparison-domain", "CHECK (comparison IN ('byte_equal', 'semantic_agreement', 'disagreement'))"),
        ("outcome-binding", "CHECK ((outcome = 'succeeded') = (comparison IN ('byte_equal', 'semantic_agreement')))")):
    change(name, "method", predicate, "CHECK (1)", "extraction_validations_v2")
change("replay-semantic", "replay_semantic", "CHECK (method <> 'same_family_replay' OR comparison <> 'semantic_agreement')", "CHECK (1)", "extraction_validations_v2", control="integrity_control")
for member, predicate, killer in (
        ("topic", "t.topic_id = x.topic_id", "evidence"),
        ("hash", "a.content_hash = json_extract(NEW.comparison_evidence_ref, '$.content_hash')", "evidence_hash"),
        ("size", "a.size_bytes = json_extract(NEW.comparison_evidence_ref, '$.size_bytes')", "evidence_metadata"),
        ("media", "a.media_type = json_extract(NEW.comparison_evidence_ref, '$.media_type')", "evidence_metadata")):
    change("evidence-" + member, killer, predicate, scope="extraction_validations_v2_artifact")
for suffix in ("u", "d"):
    change("immutable-" + suffix, "immutable", drop_trigger="extraction_validations_v2_immutable_" + suffix)
change("failed-result", "failed_control", "policy_version = 2 AND outcome = 'succeeded'", "policy_version = 2 AND 1 = 1")
change("integrity-result", "integrity_control", "method = 'independent_extraction' AND policy_version = 2", "1 = 1 AND policy_version = 2")
change("authenticate", "authentication", ' + payload.get("extraction_validations_v2", [])', "", target="gen2/router/extractions.py", control="authentication_control")
change("write", "control", ',\n                ("extraction_validations_v2", "validation_id", "validator_invocation_id")', "", target="gen2/router/extractions.py", control="legacy_control")
for event in ("i", "u"):
    test = "test_store_extraction_validations_v2.V2DomainTest.test_"
    for predicate, old in (("duplicate", "HAVING count(*) > 1"), ("nul", "instr(CAST(key AS BLOB), x'00') > 0")):
        mid = f"2D4B3E2V2-domain-{event}-{predicate}"
        MUTATIONS.append(Mutation(mid, "2d-4b3e2 continuation part 2", predicate, (test + predicate + "_" + event,),
            old=old, new="HAVING count(*) < 0" if predicate == "duplicate" else "0 > 0", scope="member_domain_extraction_validations_v2_comparison_evidence_ref_" + event))
        CONTROLS[mid] = {"controls": [test + "control_" + event], "why": "Separate successful domain event with Store.select readback; only UPDATE immutability is removed."}
