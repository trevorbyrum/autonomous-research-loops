"""2d-3b3 computation, provenance, persistence and quarantine controls."""
from .base import Mutation

TEST = "test_governed_quotes.AdmissionTest."
TARGET = "gen2/router/evidence_writer.py"
MUTATIONS, CONTROLS = [], {}


def guard(name, killer, old, new="if False:", target=TARGET, control="test_exact_control"):
    mid = "2D3B3-" + name
    MUTATIONS.append(Mutation(mid, "2d-3b3", name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "An independently asserted accepted quote (or empty/schema-valid outcome) crosses this boundary without the defect."}


guard("authority", "test_authority", 'if records and (inv["kind"] != "verification" or inv["admission_context"] != "contract/1"):',
      'if records and inv["admission_context"] != "contract/1":')
guard("claim", "test_claim_binding", 'if claim is None or claim["topic_id"] != inv["topic_id"]:')
guard("version", "test_wrong_version", 'source = self._core._one("source_artifacts", {"topic_id": inv["topic_id"], "work_id": record["work_id"], "source_version": record["source_version"]})',
      'source = self._core._one("source_artifacts", {"topic_id": inv["topic_id"], "work_id": record["work_id"], "source_version": "v1"})')
guard("derived-hash", "test_wrong_hash", 'record["span_start"], record["span_end"], source["content_hash"])',
      'record["span_start"], record["span_end"], ref["content_hash"])')
guard("artifact-reference", "test_artifact_reference", 'bind(ref, "quote source")', 'pass')
guard("authenticated-bytes", "test_forged_bytes",
      'artifact = boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"], topic_id=inv["topic_id"], media_type=ref["media_type"])',
      'artifact = self._core._spool.read(ref["content_hash"], topic_id=inv["topic_id"])')
guard("label", "test_protected_and_label_ignored", '"exact_match": "mismatch" if result.quote_quarantined else "matched"',
      '"exact_match": record.get("exact_match", "mismatch" if result.quote_quarantined else "matched")')
guard("diagnostic", "test_near", 'document = asdict(result)', 'document = {**asdict(result), "diagnostic": None}')
guard("original-bytes", "test_exact_control", 'document["quoted_bytes_hex"] = document.pop("quoted_bytes").hex()',
      'document["quoted_bytes_hex"] = document.pop("quoted_bytes").hex() + "00"', control="test_wrong_hash")
guard("persistence", "test_exact_control", 'quotes = self._write_quote_checks(checked, inv, op_id, now)', 'quotes = {}', control="test_noop_control")
guard("wiring", "test_exact_control", 'quote_checks = self._evidence_writer.check_quotes(payload, inv, bind)',
      'quote_checks = []', "gen2/router/service.py", "test_noop_control")
guard("schema", "test_schema_attribution", '"additionalProperties": false', '"additionalProperties": true',
      "gen2/schema/quote-check.schema.json", "test_schema_control")

DDL = "test_store_governed_quotes.DDLTest."
for name, killer, trigger in (("binding", "test_binding", "quote_checks_governed_binding"),
                              ("quarantine", "test_quarantine", "verification_receipts_governed_quarantine")):
    mid = "2D3B3-ddl-" + name
    MUTATIONS.append(Mutation(mid, "2d-3b3", name, (DDL + killer,), drop_trigger=trigger))
    CONTROLS[mid] = {"controls": [DDL + "test_control"], "why": "A matching governed quote with its exact source and authenticated verification commit can supply support."}
mid = "2D3B3-ddl-summary"
MUTATIONS.append(Mutation(mid, "2d-3b3", "computed status equals summary", (DDL + "test_result_summary",),
    old="AND (json_extract(match_result, '$.status') = 'mismatch') = (exact_match = 'mismatch')", new=""))
CONTROLS[mid] = {"controls": [DDL + "test_control"], "why": "A governed matching result has truthful summary columns."}
mid = "2D3B3-ddl-status-required"
MUTATIONS.append(Mutation(mid, "2d-3b3", "missing status fails closed", (DDL + "test_missing_status",),
    old="coalesce(json_extract(match_result, '$.status'), 'missing') IN", new="json_extract(match_result, '$.status') IN"))
CONTROLS[mid] = {"controls": [DDL + "test_control"], "why": "A complete computed result has an explicit status."}
