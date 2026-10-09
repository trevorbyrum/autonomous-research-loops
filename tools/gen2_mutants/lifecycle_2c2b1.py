"""2c-2b1 guard removals, each paired with a hand-written accepted control."""
from .base import Mutation

TEST = "test_source_lifecycle.LifecycleTest."
DDL = "test_source_lifecycle.LifecycleDDLTest."
VIEW = "test_source_lifecycle.DatedViewTest."
SCHEMA_TEST = "test_semantic_assessments.LifecycleSchemaTest."
TARGET = "gen2/router/assessments.py"
SCHEMA = "gen2/schema/outcome-document.schema.json"
MUTATIONS = []


def python(name, killer, old, new, target=TARGET):
    MUTATIONS.append(Mutation("2C2B1-" + name, "2c-2b1", name, (killer,), target=target, old=old, new=new))


python("actor", TEST + "test_actor_and_pins", 'raise Refusal("kind_not_permitted", "semantic assessments require contract-admitted primary work")', 'return')
python("pins", TEST + "test_actor_and_pins",
    'if pins != (inv["contract_revision"], contract["framing_version"], contract["document"]["eligibility_protocol"]["protocol_version"]):', 'if False:')
python("subject-topic", TEST + "test_topic_and_evidence", 'if not self._core._work_of_topic(record["work_id"], inv["topic_id"]):', 'if False:')
python("related-topic", TEST + "test_topic_and_evidence",
    'if record["related_work_id"] is not None and not self._core._work_of_topic(record["related_work_id"], inv["topic_id"]):', 'if False:')
python("evidence", TEST + "test_topic_and_evidence", 'bind(ref, f"{record[\'disposition_id\']}: its evidence")', 'pass')
python("predecessor", TEST + "test_predecessor_and_time",
    'raise Refusal("payload_invalid", "lifecycle predecessor must exist for this topic and source version")', 'continue')
python("time", TEST + "test_predecessor_and_time", 'if utc_instant_ns(prior["created_at"]) >= utc_instant_ns(now):', 'if False:')
python("overwrite-is-replay", TEST + "test_overwrite",
    'for record in payload.get("source_lifecycle", []):\n            if record["related_work_id"]',
    'for record in payload.get("source_lifecycle", []):\n            if self._core._one("source_lifecycle", {"disposition_id": record["disposition_id"]}) is not None:\n                continue\n            if record["related_work_id"]')
python("future-changes-past", VIEW + "test_dated_and_explicit_replacement",
    'if utc_instant_ns(r.created_at) <= instant)', 'if True)', "gen2/accounting/__init__.py")
python("implicit-latest-wins", VIEW + "test_dated_and_explicit_replacement",
    'if r.disposition_id not in replaced)', 'if r.disposition_id not in replaced and r is dated[-1])', "gen2/accounting/__init__.py")
python("replacement-ignored", VIEW + "test_dated_and_explicit_replacement",
    'if r.disposition_id not in replaced)', 'if True)', "gen2/accounting/__init__.py")

for trigger, killer in (("source_lifecycle_bound", "test_binding_and_predecessor_guards"),
                       ("source_lifecycle_predecessor", "test_binding_and_predecessor_guards"),
                       ("source_lifecycle_immutable_u", "test_update_and_delete_guards"),
                       ("source_lifecycle_immutable_d", "test_update_and_delete_guards")):
    MUTATIONS.append(Mutation("2C2B1-" + trigger, "2c-2b1", trigger, (DDL + killer,), drop_trigger=trigger))

for name, old, new in (("action", "CHECK (action IN ('add', 'keep', 'supersede', 'coexist', 'quarantine', 'duplicate-report'))", "CHECK (1)"),
                      ("actor", "CHECK (actor_kind = 'primary')", "CHECK (1)"),
                      ("reason", "CHECK (length(reason_code) > 0)", "CHECK (1)"),
                      ("version", "CHECK (length(source_version) > 0)", "CHECK (1)"),
                      ("evidence", "json_array_length(evidence_refs) > 0", "json_array_length(evidence_refs) >= 0"),
                      ("related-pair", "related_work_id IS NOT NULL AND related_source_version IS NOT NULL", "1")):
    MUTATIONS.append(Mutation("2C2B1-ddl-" + name, "2c-2b1", name, (DDL + "test_shape_guards",), old=old, new=new, scope="source_lifecycle"))

required = '"disposition_id", "work_id", "source_version", "contract_revision", "eligibility_protocol_version", "framing_version", "action", "related_work_id", "related_source_version", "supersedes_id", "reason_code", "evidence_refs"'
for field in required.replace('"', '').split(', '):
    fields = required.split(', ')
    fields.remove('"' + field + '"')
    python("missing-" + field, SCHEMA_TEST + "test_required_and_attribution_guards", required, ', '.join(fields), SCHEMA)
python("forged-attribution", SCHEMA_TEST + "test_required_and_attribution_guards",
    '"source_disposition": {\n      "type": "object", "additionalProperties": false,',
    '"source_disposition": {\n      "type": "object", "additionalProperties": true,', SCHEMA)
python("schema-action", SCHEMA_TEST + "test_required_and_attribution_guards",
    '"action": {"enum": ["add", "keep", "supersede", "coexist", "quarantine", "duplicate-report"]}', '"action": {"type": "string"}', SCHEMA)
python("schema-related-pair", SCHEMA_TEST + "test_required_and_attribution_guards",
    '"then": {"properties": {"related_work_id": {"type": "string"}, "related_source_version": {"type": "string"}}}', '"then": {}', SCHEMA)
evidence = '"evidence_refs": {"type": "array", "minItems": 1, "maxItems": 50, "uniqueItems": true, "items": {"$ref": "common.schema.json#/$defs/artifact_ref"}}\n      },\n      "if":'
python("schema-evidence", SCHEMA_TEST + "test_required_and_attribution_guards", evidence, evidence.replace('"minItems": 1', '"minItems": 0'), SCHEMA)

CONTROLS = {m.mid: {"controls": [SCHEMA_TEST + "test_control" if m.target == SCHEMA else DDL + "test_control_insert" if m.target == "ddl"
    else VIEW + "test_control_current" if m.target == "gen2/accounting/__init__.py" else TEST + "test_control_actions_and_disagreement"],
    "why": "Accepted primary record with explicit pins, evidence and all six actions, or a complete schema/DDL record or present-time view; no refused input in the control."} for m in MUTATIONS}
for name in ("predecessor", "time"):
    CONTROLS["2C2B1-" + name] = {"controls": [TEST + "test_control_supersede_then_reversal"],
        "why": "Two valid, strictly dated predecessor links, including a reversal, exercise the accepted chain admission path."}
