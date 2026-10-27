-- trace: flow S4 steps 4/8; INVARIANTS V-4/V-8/C-9/C-11;
-- DOSSIER 2d-4c part 1; operator ruling 2026-10-17.
-- Relationships only. No receipt or promotion consumer; no semantic certification.
CREATE TABLE detailed_check_records (
  check_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  performer_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  assessment TEXT NOT NULL CHECK (json_valid(assessment)),
  evidence_ref TEXT CHECK (evidence_ref IS NULL OR json_valid(evidence_ref)),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER detailed_check_records_binding BEFORE INSERT ON detailed_check_records
WHEN NOT EXISTS (
  SELECT 1 FROM claims c JOIN source_artifacts s ON s.topic_id = c.topic_id
  JOIN invocations v ON v.invocation_id = NEW.performer_invocation_id
  JOIN operation_receipts o ON o.operation_id = NEW.recorded_by_operation_id
  WHERE c.claim_id = json_extract(NEW.assessment, '$.claim_id')
    AND c.revision = json_extract(NEW.assessment, '$.claim_revision') AND c.topic_id = NEW.topic_id
    AND s.work_id = json_extract(NEW.assessment, '$.work_id')
    AND s.source_version = json_extract(NEW.assessment, '$.source_version')
    AND s.content_hash = json_extract(NEW.assessment, '$.source_artifact_hash')
    AND v.topic_id = c.topic_id AND v.kind = 'verification' AND v.admission_context = 'contract/1'
    AND v.parent_invocation_id IS NULL AND v.invocation_id <> c.producer_invocation_id
    AND v.invocation_id <> s.invocation_id AND o.invocation_id = v.invocation_id
    AND o.topic_id = c.topic_id AND o.contract_revision = v.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'detailed check needs exact claim/source and independent committing verifier');
END;
CREATE TRIGGER detailed_check_records_artifacts BEFORE INSERT ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed check needs topic-authorized artifact metadata')
  WHERE EXISTS (WITH refs(ref) AS (
    SELECT json_extract(NEW.assessment, '$.examined_artifact_ref')
    UNION ALL SELECT NEW.evidence_ref WHERE NEW.evidence_ref IS NOT NULL)
    SELECT 1 FROM refs WHERE json_type(ref) IS NOT 'object'
      OR (SELECT count(*) FROM json_each(ref)) <> 3
      OR json_type(ref, '$.content_hash') IS NOT 'text'
      OR json_type(ref, '$.size_bytes') IS NOT 'integer'
      OR json_type(ref, '$.media_type') IS NOT 'text'
      OR NOT EXISTS (SELECT 1 FROM artifacts a JOIN artifact_topics t USING (content_hash)
        WHERE t.topic_id = NEW.topic_id AND a.content_hash = json_extract(ref, '$.content_hash')
          AND a.size_bytes = json_extract(ref, '$.size_bytes') AND a.media_type = json_extract(ref, '$.media_type')));
END;
CREATE TRIGGER detailed_check_records_immutable_u BEFORE UPDATE ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed checks are immutable');
END;
CREATE TRIGGER detailed_check_records_immutable_d BEFORE DELETE ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed checks are retained');
END;
