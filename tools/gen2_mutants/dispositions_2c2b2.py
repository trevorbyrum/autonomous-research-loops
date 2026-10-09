"""2b2a guard removals with explicit accepted controls; accrual is 2b2b."""
from .base import Mutation

TEST = "test_registry_dispositions.RegistryTest."
DDL = "test_registry_dispositions.RegistryDDLTest."
SHAPE = "test_semantic_assessments.RegistrySchemaTest."
TARGET = "gen2/router/assessments.py"
SCHEMA = "gen2/schema/outcome-document.schema.json"
MUTATIONS = []


def python(name, killer, old, new, target=TARGET):
    MUTATIONS.append(Mutation("2C2B2-" + name, "2c-2b2a", name, (killer,), target=target, old=old, new=new))


python("actor", TEST + "test_actor_and_pins", 'raise Refusal("kind_not_permitted", "semantic assessments require contract-admitted primary work")', 'return')
python("pins", TEST + "test_actor_and_pins",
    'if pins != (inv["contract_revision"], contract["framing_version"], contract["document"]["eligibility_protocol"]["protocol_version"]):', 'if False:')
python("evidence", TEST + "test_evidence", 'bind(ref, f"registry {record[\'disposition_id\']}: its evidence")', 'pass')
python("predecessor", TEST + "test_predecessor",
    'raise Refusal("payload_invalid", "registry predecessor must exist for this topic, kind and identity")', 'continue')
python("time", TEST + "test_time", 'if utc_instant_ns(now) <= utc_instant_ns(prior["created_at"]):', 'if False:')
python("overwrite-is-replay", TEST + "test_overwrite",
    'for record in payload.get("registry_dispositions", []):\n            if record["supersedes_id"]',
    'for record in payload.get("registry_dispositions", []):\n            if self._core._one("registry_dispositions", {"disposition_id": record["disposition_id"]}) is not None:\n                continue\n            if record["supersedes_id"]')

for trigger, killer in (("registry_dispositions_bound", "test_binding_and_predecessor"),
                       ("registry_dispositions_predecessor", "test_binding_and_predecessor"),
                       ("registry_dispositions_immutable_u", "test_immutable"), ("registry_dispositions_immutable_d", "test_immutable")):
    MUTATIONS.append(Mutation("2C2B2-" + trigger, "2c-2b2a", trigger, (DDL + killer,), drop_trigger=trigger))
for name, old, new in (("actor", "CHECK (actor_kind = 'primary')", "CHECK (1)"),
                      ("identity", "CHECK (length(registry_id) > 0)", "CHECK (1)"),
                      ("subject", "CHECK (length(subject) > 0)", "CHECK (1)"),
                      ("reason", "CHECK (length(reason_code) > 0)", "CHECK (1)"),
                      ("evidence", "json_array_length(evidence_refs) > 0", "json_array_length(evidence_refs) >= 0"),
                      ("labels", "CHECK ((registry_kind = 'contradiction' AND disposition IN ('unresolved', 'resolved', 'contested'))\n      OR (registry_kind = 'branch' AND disposition IN ('promote', 'park', 'drop')))", "CHECK (1)")):
    MUTATIONS.append(Mutation("2C2B2-ddl-" + name, "2c-2b2a", name, (DDL + "test_shape",), old=old, new=new, scope="registry_dispositions"))
MUTATIONS.append(Mutation("2C2B2-ddl-kind", "2c-2b2a", "kind admission at both DDL guards", (DDL + "test_shape",),
    old="CHECK (registry_kind IN ('contradiction', 'branch'))", new="CHECK (1)", scope="registry_dispositions",
    also=(("registry_kind = 'contradiction'", "registry_kind != 'branch'"),)))
required = '"disposition_id", "registry_kind", "registry_id", "subject", "disposition", "contract_revision", "eligibility_protocol_version", "framing_version", "supersedes_id", "reason_code", "evidence_refs"'
for field in required.replace('"', '').split(', '):
    fields = required.split(', ')
    fields.remove('"' + field + '"')
    python("missing-" + field, SHAPE + "test_guards", required, ', '.join(fields), SCHEMA)
python("forged-attribution", SHAPE + "test_guards", '"registry_disposition": {\n      "type": "object", "additionalProperties": false,',
    '"registry_disposition": {\n      "type": "object", "additionalProperties": true,', SCHEMA)
python("schema-kind", SHAPE + "test_guards", '"registry_kind": {"enum": ["contradiction", "branch"]}', '"registry_kind": {"type": "string"}', SCHEMA)
for name, old in (("contradiction", '"then": {"properties": {"disposition": {"enum": ["unresolved", "resolved", "contested"]}}}'),
                  ("branch", '"else": {"properties": {"disposition": {"enum": ["promote", "park", "drop"]}}}')):
    python("schema-" + name, SHAPE + "test_guards", old, '"then": {}' if name == "contradiction" else '"else": {}', SCHEMA)
evidence = '"evidence_refs": {"type": "array", "minItems": 1, "maxItems": 50, "uniqueItems": true, "items": {"$ref": "common.schema.json#/$defs/artifact_ref"}}\n      },\n      "if": {"properties": {"registry_kind"'
python("schema-evidence", SHAPE + "test_guards", evidence, evidence.replace('"minItems": 1', '"minItems": 0'), SCHEMA)

CONTROLS = {m.mid: {"controls": [SHAPE + "test_control" if m.target == SCHEMA else DDL + "test_control_insert" if m.target == "ddl" else TEST + "test_control_histories"],
    "why": "Complete primary-attributed record with pins and retained evidence; all six admitted dispositions stay visible, including competing contradiction judgments."} for m in MUTATIONS}
for name in ("predecessor", "time"):
    CONTROLS["2C2B2-" + name] = {"controls": [TEST + "test_control_reversal"],
        "why": "A strictly later same-topic/kind/identity successor appends a resolution and preserves the original unresolved record."}
