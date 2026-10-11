-- trace: flow S4 step 4 / §6.7; BOUNDARIES.md Router/Verifier; V-6, C-11, RG-5.
-- Historical checks stay immutable. Governed checks retain the entire computed
-- result, including lossless byte hex, normalization, versions and diagnostics.
-- Responsibility split (NB2): Router authenticates bytes, runs the matcher and
-- constructs the full document. SQL below checks JSON validity, expected hash,
-- offsets, recognized status/summary agreement and normalization identity.
-- The binding trigger checks topic/claim/source/hash, obtained artifact topic
-- authorization, verification admission, operation/contract and not_run NLI.
-- SQL does not compute matching or validate byte hex, normalized text,
-- protection/token identities, diagnostic shape/score/spans or the full shape.
ALTER TABLE quote_checks ADD COLUMN topic_id TEXT REFERENCES queue_entries (topic_id);
ALTER TABLE quote_checks ADD COLUMN work_id TEXT REFERENCES works (work_id);
ALTER TABLE quote_checks ADD COLUMN source_version TEXT;
ALTER TABLE quote_checks ADD COLUMN verifier_invocation_id TEXT REFERENCES invocations (invocation_id);
ALTER TABLE quote_checks ADD COLUMN recorded_by_operation_id TEXT REFERENCES operation_receipts (operation_id);
ALTER TABLE quote_checks ADD COLUMN match_result TEXT CHECK (match_result IS NULL OR (
  json_valid(match_result)
  AND json_extract(match_result, '$.expected_artifact_hash') IS source_artifact_hash
  AND json_extract(match_result, '$.span_start') IS span_start
  AND json_extract(match_result, '$.span_end') IS span_end
  AND coalesce(json_extract(match_result, '$.status'), 'missing') IN ('match', 'match_normalized', 'mismatch')
  AND (json_extract(match_result, '$.status') = 'mismatch') = (exact_match = 'mismatch')
  AND normalization_version IS json_extract(match_result, '$.normalization[0]') || '/' || json_extract(match_result, '$.normalization[1]')
));

CREATE TRIGGER quote_checks_governed_binding BEFORE INSERT ON quote_checks
WHEN NEW.match_result IS NOT NULL AND (NEW.nli_signal IS NOT 'not_run' OR NOT EXISTS (
  SELECT 1 FROM source_artifacts s
  JOIN claims c ON c.claim_id = NEW.claim_id AND c.revision = NEW.claim_revision AND c.topic_id = s.topic_id
  JOIN invocations i ON i.invocation_id = NEW.verifier_invocation_id AND i.topic_id = s.topic_id
  JOIN operation_receipts o ON o.operation_id = NEW.recorded_by_operation_id AND o.invocation_id = i.invocation_id AND o.topic_id = s.topic_id
  WHERE s.topic_id = NEW.topic_id AND s.work_id = NEW.work_id AND s.source_version = NEW.source_version
    AND s.content_hash = NEW.source_artifact_hash AND i.kind = 'verification' AND i.admission_context = 'contract/1'
    AND o.contract_revision = i.contract_revision
    AND EXISTS (SELECT 1 FROM artifact_topics a WHERE a.topic_id = s.topic_id AND a.content_hash = json_extract(NEW.match_result, '$.artifact_hash'))))
BEGIN
  SELECT RAISE(ABORT, 'governed quote needs its exact source binding, topic claim and verification commit (V-6)');
END;

-- A computed quarantine may grant neither full nor partial support.
CREATE TRIGGER verification_receipts_governed_quarantine BEFORE INSERT ON verification_receipts
WHEN NEW.verdict IN ('supports', 'partially_supports') AND EXISTS (
  SELECT 1 FROM quote_checks q WHERE q.check_id = NEW.quote_check_id
    AND q.match_result IS NOT NULL AND q.quote_quarantined = 1)
BEGIN
  SELECT RAISE(ABORT, 'governed quarantined quote cannot supply support (V-6)');
END;
