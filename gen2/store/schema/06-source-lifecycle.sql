-- 2c-2b1.
-- Primary judgments, never overwritten; explicit successors reverse a record.
-- trace: flow S4.5, methodology section 4, INVARIANTS E-7/C-12.
CREATE TABLE source_lifecycle (
  disposition_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL CHECK (length(source_version) > 0),
  contract_revision INTEGER NOT NULL,
  eligibility_protocol_version INTEGER NOT NULL CHECK (eligibility_protocol_version >= 1),
  framing_version INTEGER NOT NULL CHECK (framing_version >= 1),
  action TEXT NOT NULL CHECK (action IN ('add', 'keep', 'supersede', 'coexist', 'quarantine', 'duplicate-report')),
  related_work_id TEXT REFERENCES works (work_id),
  related_source_version TEXT CHECK (related_source_version IS NULL OR length(related_source_version) > 0),
  supersedes_id TEXT REFERENCES source_lifecycle (disposition_id),
  reason_code TEXT NOT NULL CHECK (length(reason_code) > 0),
  evidence_refs TEXT NOT NULL CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array' AND json_array_length(evidence_refs) > 0),
  actor_kind TEXT NOT NULL CHECK (actor_kind = 'primary'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK ((action IN ('supersede', 'coexist', 'duplicate-report') AND related_work_id IS NOT NULL AND related_source_version IS NOT NULL)
      OR (action NOT IN ('supersede', 'coexist', 'duplicate-report') AND related_work_id IS NULL AND related_source_version IS NULL))
) STRICT;
CREATE TRIGGER source_lifecycle_bound BEFORE INSERT ON source_lifecycle
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
  SELECT RAISE(ABORT, 'lifecycle needs its primary commit and pinned protocol/framing (E-7, C-12)');
END;
CREATE TRIGGER source_lifecycle_predecessor BEFORE INSERT ON source_lifecycle
WHEN NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM source_lifecycle p WHERE p.disposition_id = NEW.supersedes_id
    AND p.topic_id = NEW.topic_id AND p.work_id = NEW.work_id AND p.source_version = NEW.source_version)
BEGIN
  SELECT RAISE(ABORT, 'lifecycle predecessor must exist for this topic and source version');
END;
CREATE TRIGGER source_lifecycle_immutable_u BEFORE UPDATE ON source_lifecycle
BEGIN
  SELECT RAISE(ABORT, 'source lifecycle is append-only');
END;
CREATE TRIGGER source_lifecycle_immutable_d BEFORE DELETE ON source_lifecycle
BEGIN
  SELECT RAISE(ABORT, 'source lifecycle is retained');
END;
