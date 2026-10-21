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

# Capture-bound admission and consumption; Python killers remove the independent
# SQL consumers in their fixtures, and raw-DDL killers never execute the Router.
PY_CAPTURE = "test_capture_support.RouterGuardTest."
SQL_CAPTURE = "test_store_capture_support.CaptureDDLTest."


def capture_guard(name, killer, old=None, new="", target=TARGET, trigger=None, control="test_control", also=()):
    mid = "2D3B3R1-" + name
    prefix = SQL_CAPTURE if target == "ddl" else PY_CAPTURE
    MUTATIONS.append(Mutation(mid, "2d-3b3-repair-1", name, (prefix + killer,), target=target,
        old=old, new=new, drop_trigger=trigger, also=also))
    CONTROLS[mid] = {"controls": [prefix + control], "why": "A literal matching capture and its bound load-bearing receipt promote; non-quote and multiple-span controls retain legitimate paths."}


for field, killer, replacement in (("work_id", "test_work", 'doc["source"]["work_id"]'),
        ("source_version", "test_version", 'doc["source"]["source_version"]'),
        ("normalization_version", "test_normalization", 'exact["normalization_version"]')):
    capture_guard("python-" + field, killer, 'q["' + field + '"]', replacement)
capture_guard("python-hash", "test_hash", 'q["match_result"]["artifact_hash"]', 'doc["obtained_content_hash"]')
capture_guard("python-admission", "test_null_reference", 'if not self._quote_receipt_valid(doc):', 'if False:')
capture_guard("python-spans", "test_span", '(q["span_start"], q["span_end"]) in spans', 'True',
    also=(('and spans <= {(q["span_start"], q["span_end"]) for q in bound}', 'and True'),))
capture_guard("python-each-span", "test_multi_unchecked", 'and spans <= {(q["span_start"], q["span_end"]) for q in bound}', 'and True', control="test_multi_control")
capture_guard("python-quarantine", "test_non_load_bearing", 'if any(q["quote_quarantined"] for q in checks):', 'if False:')
capture_guard("python-existing-receipt", "test_existing_receipt_matching_check",
    'return doc["extraction"]["method"] == "canonical_bytes" and self._quote_receipt_valid(doc)', 'return True')
capture_guard("python-capture-quarantine", "test_same_capture_cannot_clear", 'if support and any(q["quote_quarantined"] for q in checks):', 'if False:')

for name, killer, clause in (("work", "test_work", "AND q.work_id = v.work_id"),
        ("version", "test_version", "AND q.source_version = v.source_version"),
        ("hash", "test_hash", "AND json_extract(q.match_result, '$.artifact_hash') IS v.obtained_content_hash"),
        ("normalization", "test_normalization", "AND q.normalization_version IS json_extract(v.receipt, '$.checks.exact_quote.normalization_version')")):
    capture_guard("ddl-" + name, killer, clause, target="ddl", control="test_capture_control")
capture_guard("ddl-admission", "test_null_reference", target="ddl", trigger="verification_receipts_capture_binding", control="test_capture_control")
capture_guard("ddl-spans", "test_span", "AND b.check_id = v.quote_check_id\n      AND b.span_start IS json_extract(s.value, '$.start') AND b.span_end IS json_extract(s.value, '$.end')",
    "AND b.check_id = v.quote_check_id", target="ddl", control="test_capture_control", also=((
        "WHERE b.verification_receipt_id = v.verification_receipt_id\n      AND b.span_start IS json_extract(s.value, '$.start') AND b.span_end IS json_extract(s.value, '$.end')",
        "WHERE b.verification_receipt_id = v.verification_receipt_id"),))
capture_guard("ddl-each-span", "test_multi_unchecked", "OR EXISTS (SELECT 1 FROM json_each(v.cited_spans) s WHERE NOT EXISTS (",
    "OR 0 AND EXISTS (SELECT 1 FROM json_each(v.cited_spans) s WHERE NOT EXISTS (", target="ddl", control="test_multi_control")
capture_guard("ddl-promotion", "test_non_load_bearing", target="ddl", trigger="claims_accepted_support_needs_capture", control="test_capture_control")
capture_guard("ddl-existing-receipt", "test_existing_receipt_matching", "AND NOT EXISTS (SELECT 1 FROM governed_receipt_failures f WHERE f.verification_receipt_id = r.verification_receipt_id)",
    target="ddl", control="test_capture_control")
capture_guard("ddl-late-check", "test_late_check", target="ddl", trigger="commit_outcome_refence_captures", control="test_late_multi_control")
capture_guard("ddl-capture-quarantine", "test_same_capture_cannot_clear", "(v.verdict IN ('supports', 'partially_supports') AND EXISTS (",
    "(0 AND EXISTS (", target="ddl", control="test_capture_control")
# Retain the installation mutant's identity, now guarding the required absence
# of install-time DML rather than requiring that obsolete rewrite.
capture_guard("ddl-installation", "test_installation_no_dml", "CREATE TRIGGER claims_accepted_support_needs_capture",
    "UPDATE claims SET status = 'quarantined' WHERE status = 'accepted_support' AND EXISTS ("
    "SELECT 1 FROM governed_captures_blocked b WHERE b.claim_id = claims.claim_id AND b.revision = claims.revision);\n"
    "CREATE TRIGGER claims_accepted_support_needs_capture", target="ddl", control="test_upgrade_control")

capture_guard("ddl-intermediate-disposition", "test_late_multi_control",
    "CREATE TRIGGER commit_outcome_refence_captures AFTER INSERT ON audit_events",
    "CREATE TRIGGER quote_checks_refence_capture AFTER INSERT ON quote_checks WHEN NEW.match_result IS NOT NULL\n"
    "BEGIN\n  UPDATE claims SET status = 'quarantined' WHERE claim_id = NEW.claim_id AND revision = NEW.claim_revision\n"
    "    AND status = 'accepted_support' AND EXISTS (SELECT 1 FROM governed_captures_blocked b\n"
    "      WHERE b.claim_id = NEW.claim_id AND b.revision = NEW.claim_revision);\nEND;\n"
    "CREATE TRIGGER commit_outcome_refence_captures AFTER INSERT ON audit_events",
    target="ddl", control="test_late_provisional_control")
capture_guard("ddl-reconciliation-operation", "test_late_unaffected_capture",
    "q.recorded_by_operation_id = NEW.operation_id\n      AND ", "", target="ddl", control="test_late_multi_control")
capture_guard("ddl-reconciliation-status", "test_late_provisional_mismatch",
    "UPDATE claims SET status = 'quarantined' WHERE status = 'accepted_support'",
    "UPDATE claims SET status = 'quarantined' WHERE status IN ('accepted_support', 'provisional', 'contested')",
    target="ddl", control="test_late_multi_control")
