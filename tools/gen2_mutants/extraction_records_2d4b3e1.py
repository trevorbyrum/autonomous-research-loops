"""SQL 22 predicate guards paired with accepted independent records."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
DDL = "test_store_extraction_records.DDLTest."
ROUTER = "test_extraction_records.RecordTest."


def change(name, killer, old=None, new="1 = 1", scope=None, target="ddl", control="control", drop_trigger=None):
    mid = "2D4B3E1-" + name
    test = DDL if target == "ddl" else ROUTER
    MUTATIONS.append(Mutation(mid, "2d-4b3e1", name, (test + "test_" + killer,), old=old, new=new,
        scope=scope, target=target, drop_trigger=drop_trigger))
    CONTROLS[mid] = {"controls": [test + "test_" + control],
        "why": "Separate accepted independent records consume admitted input and retained authenticated outputs; no receipt or SQL 17 support authority changes."}


change("acquisition", "acquisition", "FOREIGN KEY (topic_id, work_id, source_version, event_id, verifier_invocation_id)\n    REFERENCES source_acquisitions (topic_id, work_id, source_version, event_id, verifier_invocation_id)", "CHECK (1)", "source_extractions")
change("ceiling", "tier", ") > coalesce((", ") < coalesce((", "source_extractions_tier")
change("commit-attribution", "commit", "o.operation_id = NEW.recorded_by_operation_id", scope="source_extractions_commit")
change("producer", "producer", "v.invocation_id <> s.invocation_id", scope="extraction_validations_binding")
change("extractor", "extractor", "v.invocation_id <> x.extracting_invocation_id", scope="extraction_validations_binding")
change("lineage", "foreign_basis", "y.topic_id = x.topic_id AND y.work_id = x.work_id AND y.source_version = x.source_version\n    AND y.event_id = x.event_id AND y.verifier_invocation_id = x.verifier_invocation_id", scope="extraction_validations_binding")
change("same-identity", "same_identity", "y.extractor_identity = x.extractor_identity", "0 = 1", "extraction_validations_method")
change("integrity-version", "integrity_version", "y.extractor_version <> x.extractor_version", "0 = 1", "extraction_validations_method", control="integrity_control")
change("byte-comparison", "byte_comparison", "json_extract(y.output_ref, '$.content_hash') <> json_extract(x.output_ref, '$.content_hash')", "0 = 1", "extraction_validations_method")
change("outcome", "outcome", "CHECK ((outcome = 'succeeded') = (comparison IN ('byte_equal', 'semantic_agreement')))", "CHECK (1)", "extraction_validations")
change("policy", "policy", "CHECK (policy_version = 1)", "CHECK (1)", "extraction_validations")
change("method", "policy", "CHECK (method IN ('independent_extraction', 'same_extractor_replay'))", "CHECK (1)", "extraction_validations")
change("failed-result", "failed", "policy_version = 1 AND outcome = 'succeeded'", "policy_version = 1 AND 1 = 1")
change("integrity-result", "integrity_control", "method = 'independent_extraction' AND policy_version = 1", "1 = 1 AND policy_version = 1")
for scope, killer, field in (("source_extractions_artifact", "artifact", "output_ref"),
        ("extraction_validations_artifact", "evidence", "comparison_evidence_ref")):
    change(scope + "-topic", killer, "t.topic_id = NEW.topic_id" if field == "output_ref" else "t.topic_id = x.topic_id", scope=scope)
    for member in ("size_bytes", "media_type"):
        change(scope + "-" + member, "metadata" if field == "output_ref" else "evidence_metadata",
            f"a.{member} = json_extract(NEW.{field}, '$.{member}')", scope=scope)
for table in ("source_extractions", "extraction_validations"):
    for suffix in ("u", "d"):
        change(table + "-" + suffix, "immutable", drop_trigger=table + "_immutable_" + suffix)
change("authenticate", "authentication", 'boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"],\n                    topic_id=inv["topic_id"], media_type=ref["media_type"])', "pass", target="gen2/router/extractions.py", control="authentication_control")
change("authenticate-wiring", "authentication", "self._extractions.authenticate(payload, inv, bind)", "pass", target="gen2/router/service.py", control="authentication_control")
change("write-wiring", "control", 'self._extractions.write(payload, inv, env["operation_id"], now)', "{}", target="gen2/router/service.py", control="empty_control")
