-- 2c-2a; flow S4/S4.5, methodology §4, E-3/E-7/V-9.
-- Judgments are retained records, never deductions from counts. A lineage
-- extension inherits its subject, evidence and attribution from its assessment.
-- trace: flow S4/S4.5, methodology §4, INVARIANTS E-7/C-12.
CREATE TABLE semantic_assessments (
  assessment_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL CHECK (length(source_version) > 0),
  contract_revision INTEGER NOT NULL,
  eligibility_protocol_version INTEGER NOT NULL CHECK (eligibility_protocol_version >= 1),
  framing_version INTEGER NOT NULL CHECK (framing_version >= 1),
  novelty TEXT NOT NULL CHECK (novelty IN ('novel', 'not_novel', 'unknown')),
  independence TEXT NOT NULL CHECK (independence IN ('independent', 'shared_origin', 'unknown')),
  applicability TEXT NOT NULL CHECK (applicability IN ('applicable', 'not_applicable', 'unknown')),
  contribution TEXT NOT NULL CHECK (contribution IN ('answer', 'confidence', 'applicability', 'options', 'question_formulation', 'boundary_condition', 'contradiction', 'unknown')),
  evidence_refs TEXT NOT NULL CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array' AND json_array_length(evidence_refs) > 0),
  actor_kind TEXT NOT NULL CHECK (actor_kind = 'primary'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision)
) STRICT;

CREATE TRIGGER semantic_assessments_bound BEFORE INSERT ON semantic_assessments
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i JOIN operation_receipts o ON o.invocation_id = i.invocation_id
    JOIN contract_revisions c ON c.topic_id = i.topic_id AND c.revision = i.contract_revision
  WHERE i.invocation_id = NEW.invocation_id AND o.operation_id = NEW.recorded_by_operation_id
    AND i.topic_id = NEW.topic_id AND o.topic_id = NEW.topic_id
    AND i.kind IN ('research_pass', 'checkpoint') AND i.admission_context = 'contract/1'
    AND i.contract_revision = NEW.contract_revision AND o.contract_revision = NEW.contract_revision
    AND c.framing_version = NEW.framing_version
    AND json_extract(c.document, '$.eligibility_protocol.protocol_version') IS NEW.eligibility_protocol_version)
BEGIN
  SELECT RAISE(ABORT, 'semantic assessment needs its primary commit and pinned protocol/framing (E-7, C-12)');
END;
CREATE TRIGGER semantic_assessments_immutable_u BEFORE UPDATE ON semantic_assessments
BEGIN
  SELECT RAISE(ABORT, 'semantic assessments are append-only (E-7)');
END;
CREATE TRIGGER semantic_assessments_immutable_d BEFORE DELETE ON semantic_assessments
BEGIN
  SELECT RAISE(ABORT, 'semantic assessments are retained (E-7)');
END;

-- trace: flow S4/S4.5, methodology §4, INVARIANTS E-3/V-9.
CREATE TABLE source_lineage (
  assessment_id TEXT PRIMARY KEY REFERENCES semantic_assessments (assessment_id),
  relation TEXT NOT NULL CHECK (relation IN ('shared_study_origin', 'version_of', 'derived_from')),
  study_origin_id TEXT CHECK (study_origin_id IS NULL OR length(study_origin_id) > 0),
  related_work_id TEXT REFERENCES works (work_id),
  related_source_version TEXT CHECK (related_source_version IS NULL OR length(related_source_version) > 0),
  CHECK ((relation = 'shared_study_origin' AND study_origin_id IS NOT NULL AND related_work_id IS NULL AND related_source_version IS NULL)
      OR (relation != 'shared_study_origin' AND study_origin_id IS NULL AND related_work_id IS NOT NULL AND related_source_version IS NOT NULL))
) STRICT;
CREATE TRIGGER source_lineage_immutable_u BEFORE UPDATE ON source_lineage
BEGIN
  SELECT RAISE(ABORT, 'source lineage is append-only (E-3)');
END;
CREATE TRIGGER source_lineage_immutable_d BEFORE DELETE ON source_lineage
BEGIN
  SELECT RAISE(ABORT, 'source lineage is retained (E-3)');
END;
