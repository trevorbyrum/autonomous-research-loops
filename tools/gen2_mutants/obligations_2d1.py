"""2d-1: admission and retention guards with explicit accepted controls."""
from .base import Mutation

TEST = "test_obligation_admission.AdmissionTest."
TARGET = "gen2/router/assessments.py"
SCHEMA = "gen2/schema/obligation-assessment.schema.json"
MUTATIONS = []


def python(name, killer, old, new="if False:", target=TARGET):
    MUTATIONS.append(Mutation("2D1-" + name, "2d-1", name, (TEST + killer,), target=target, old=old, new=new))


python("actor", "test_roles_and_attribution", 'raise Refusal("kind_not_permitted", "obligation judgments require contract-admitted primary work")', 'return')
python("pins", "test_scheme_and_pins", 'if pins != (inv["contract_revision"], contract["content_hash"], contract["framing_version"], doc["eligibility_protocol"]["protocol_version"]):')
python("subject", "test_scheme_and_pins", 'if self._core._one("obligations", {"topic_id": inv["topic_id"], "contract_revision": inv["contract_revision"], "obligation_id": record["obligation_id"]}) is None:', 'if False:')
python("scheme", "test_scheme_and_pins", 'if scheme is None or confidence["scheme"] != {"scheme_id": scheme["scheme_id"], "version": scheme["version"]} or confidence["label"] not in scheme["labels"]:')
python("unknown-reason", "test_schema", 'elif not confidence["reason"].strip():', 'elif False:')
python("predecessor", "test_histories_and_conflicts", 'if prior is None or (prior["topic_id"], prior["obligation_id"]) != (inv["topic_id"], record["obligation_id"]):', 'if prior is None:')
python("time", "test_predecessor_time", 'if prior_instant >= utc_instant_ns(now):')
python("write", "test_control", 'self._validate_obligations(payload, inv)  # repeat under the writer fence', 'return {}')
python("evidence", "test_evidence", 'bind(ref, f"{record[\'record_id\']}: its evidence")', 'pass', "gen2/router/assessments.py")

for trigger in ("bound", "scheme", "predecessor", "immutable_u", "immutable_d"):
    name = "obligation_assessments_" + trigger
    MUTATIONS.append(Mutation("2D1-" + name, "2d-1", name, ("test_obligation_admission.DDLTest.test_ddl_guards",), drop_trigger=name))

python("required-reason", "test_schema", '"evidence_refs", "reason", "supersedes_id"', '"evidence_refs", "supersedes_id"', SCHEMA)
python("schema-attribution", "test_schema", '  "type": "object", "additionalProperties": false,\n  "required":', '  "type": "object", "additionalProperties": true,\n  "required":', SCHEMA)
python("schema-evidence", "test_schema", '"minItems": 1, "maxItems": 50', '"minItems": 0, "maxItems": 50', SCHEMA)

CONTROLS = {m.mid: {"controls": ["test_obligation_admission.DDLTest.test_control" if m.target == "ddl" else TEST + ("test_schema_control" if m.target == SCHEMA else "test_noop_control" if m.mid == "2D1-write" else
    "test_histories_and_conflicts" if m.mid in {"2D1-time", "2D1-unknown-reason"} else "test_control")],
    "why": "Literal accepted judgment under the approved scheme; the dated history control admits successors, the no-op control reaches write without records, and the schema control validates the complete proposal."} for m in MUTATIONS}
