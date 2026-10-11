"""2d-3b2 source identity guards and accepted controls; no matching authority."""
from .base import Mutation

TEST = "test_source_artifacts.AdmissionTest."
TARGET = "gen2/router/evidence_writer.py"
SCHEMA = "gen2/schema/source-artifact.schema.json"
MUTATIONS = []


def guard(name, killer, old, new="if False:", target=TARGET, control="test_control"):
    mid = "2D3B2-" + name
    MUTATIONS.append(Mutation(mid, "2d-3b2", name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "A separate accepted source association (or a complete schema/no-record outcome) crosses the edited boundary and retains literal byte identity and actual capture attribution."}


CONTROLS = {}
guard("primary", "test_primary_authority", 'if records and (inv["kind"] not in ("research_pass", "checkpoint") or inv["admission_context"] != "contract/1"):',
      'if records and inv["admission_context"] != "contract/1":')
guard("contract", "test_precontract_authority", 'if records and (inv["kind"] not in ("research_pass", "checkpoint") or inv["admission_context"] != "contract/1"):',
      'if records and inv["kind"] not in ("research_pass", "checkpoint"):')
guard("retrieved-work", "test_unretrieved_work", 'if not self._core._work_of_topic(record["work_id"], inv["topic_id"]):')
guard("artifact-binding", "test_artifact_binding", 'bind(record["artifact_ref"], "source artifact")', 'pass')
guard("version-conflict", "test_version_conflict_and_equal_reference", 'if prior["content_hash"] != content_hash:')
guard("write", "test_control", 'sources = self._write_source_artifacts(payload, inv, op_id, now)', 'sources = {}', control="test_noop_control")
guard("wiring", "test_primary_authority", 'self._evidence_writer.bind_source_artifacts(payload, inv, bind)', 'pass', "gen2/router/service.py")
guard("attribution-schema", "test_schema_attribution", '"additionalProperties": false', '"additionalProperties": true', SCHEMA, "test_schema_control")
for name in ("work_id", "source_version", "artifact_ref"):
    required = '"work_id", "source_version", "artifact_ref"'
    replacement = ", ".join('"' + field + '"' for field in ("work_id", "source_version", "artifact_ref") if field != name)
    guard("required-" + name, "test_schema_required_identity", required, replacement, SCHEMA, "test_schema_control")

DDL = "test_store_source_artifacts.DDLTest."
for suffix, killer in (("commit", "test_commit"), ("topic", "test_topic"),
                       ("immutable_u", "test_update"), ("immutable_d", "test_delete")):
    mid = "2D3B2-ddl-" + suffix
    MUTATIONS.append(Mutation(mid, "2d-3b2", suffix, (DDL + killer,), drop_trigger="source_artifacts_" + suffix))
    CONTROLS[mid] = {"controls": [DDL + "test_control"], "why": "An authenticated, topic-retrieved source artifact inserts under the same DDL trigger with immutable capture provenance."}
