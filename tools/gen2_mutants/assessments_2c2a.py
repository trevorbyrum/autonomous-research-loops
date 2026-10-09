"""2c-2a admission and durable record guards, with explicit accepted controls."""
from .base import Mutation

TEST = "test_semantic_assessments.SemanticTest."
CONTROL = TEST + "test_control_records_labels_and_shared_origin"
TARGET = "gen2/router/assessments.py"
DDL = "test_semantic_assessments.SemanticDDLTest."
MUTATIONS = []


def python(name, killer, old, new, target=TARGET):
    MUTATIONS.append(Mutation("2C2A-" + name, "2c-2a", name, (TEST + killer,), target=target, old=old, new=new))


python("actor", "test_unauthorized_actor",
       'raise Refusal("kind_not_permitted", "semantic assessments require contract-admitted primary work")', 'return')
python("precontract", "test_precontract_actor",
       'raise Refusal("kind_not_permitted", "semantic assessments require contract-admitted primary work")', 'return')
python("pins", "test_wrong_pins",
       'if pins != (inv["contract_revision"], contract["framing_version"], contract["document"]["eligibility_protocol"]["protocol_version"]):', 'if False:')
python("subject-topic", "test_subject_and_related_topic",
       'if not self._core._work_of_topic(record["work_id"], inv["topic_id"]):', 'if False:')
python("related-topic", "test_subject_and_related_topic",
       'if not self._core._work_of_topic(lineage["related_work_id"], inv["topic_id"]):', 'if False:')
python("evidence", "test_evidence_binding", 'bind(ref, f"{record[\'assessment_id\']}: its evidence")', 'pass')
python("overwrite-is-replay", "test_overwrite",
       'for record in payload.get("semantic_assessments", []):\n            row =',
       'for record in payload.get("semantic_assessments", []):\n            if self._core._one("semantic_assessments", {"assessment_id": record["assessment_id"]}) is not None:\n                continue\n            row =')
python("unknown-label", "test_unknown_missing_and_duplicate_labels", '"unknown": None}', '"unknown": False}', "gen2/accounting/__init__.py")

for trigger, killer in (("semantic_assessments_bound", "test_binding_guard"),
                        ("semantic_assessments_immutable_u", "test_update_guard"), ("semantic_assessments_immutable_d", "test_delete_guard"),
                        ("source_lineage_immutable_u", "test_update_guard"), ("source_lineage_immutable_d", "test_delete_guard")):
    MUTATIONS.append(Mutation("2C2A-" + trigger, "2c-2a", trigger, (DDL + killer,), drop_trigger=trigger))

for field in ("actor_kind", "novelty", "independence", "applicability", "contribution"):
    old = "CHECK (actor_kind = 'primary')" if field == "actor_kind" else {
        "novelty": "CHECK (novelty IN ('novel', 'not_novel', 'unknown'))",
        "independence": "CHECK (independence IN ('independent', 'shared_origin', 'unknown'))",
        "applicability": "CHECK (applicability IN ('applicable', 'not_applicable', 'unknown'))",
        "contribution": "CHECK (contribution IN ('answer', 'confidence', 'applicability', 'options', 'question_formulation', 'boundary_condition', 'contradiction', 'unknown'))"}[field]
    MUTATIONS.append(Mutation("2C2A-ddl-" + field, "2c-2a", field, (DDL + "test_actor_and_label_guards",),
                             old=old, new="CHECK (1)", scope="semantic_assessments"))
MUTATIONS.append(Mutation("2C2A-lineage-shape", "2c-2a", "shared origin requires an origin id", (DDL + "test_lineage_shape_guard",),
    old="relation = 'shared_study_origin' AND study_origin_id IS NOT NULL", new="relation = 'shared_study_origin'", scope="source_lineage"))

SCHEMA = "gen2/schema/outcome-document.schema.json"
for field in ("source_version", "contract_revision", "eligibility_protocol_version", "framing_version", "novelty"):
    required = '"assessment_id", "work_id", "source_version", "contract_revision", "eligibility_protocol_version", "framing_version", "novelty", "independence", "applicability", "contribution", "evidence_refs", "lineage"'
    python("missing-" + field, "test_schema_guards", required, required.replace('"' + field + '", ', ''), SCHEMA)

CONTROLS = {m.mid: {"controls": [TEST + "test_schema_control" if m.target == SCHEMA else DDL + "test_control_insert" if m.target == "ddl" else CONTROL],
    "why": "Hand-written accepted record with all pins, authorized primary, retained evidence, explicit labels and shared-origin lineage; the schema control validates the complete record against the mutated required list."} for m in MUTATIONS}
