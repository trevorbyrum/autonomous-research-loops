-- trace: flow S7/S8, INVARIANTS E-7/C-12/G-1; DEBT-033.
-- Judgments and open states are retained independently, including every
-- deferral and competing successor. There is no inferred current judgment.
CREATE TABLE obligation_assessments (
  record_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  obligation_id TEXT NOT NULL,
  subject TEXT NOT NULL CHECK (length(trim(subject)) > 0),
  contract_revision INTEGER NOT NULL,
  contract_content_hash TEXT NOT NULL,
  eligibility_protocol_version INTEGER NOT NULL,
  framing_version INTEGER NOT NULL,
  disposition TEXT CHECK (disposition IN ('supported', 'contradicted', 'unresolved', 'deferred')),
  state TEXT CHECK (state = 'open'),
  confidence TEXT NOT NULL CHECK (json_valid(confidence) AND json_type(confidence) = 'object'),
  evidence_refs TEXT NOT NULL CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array' AND json_array_length(evidence_refs) > 0),
  actor_kind TEXT NOT NULL CHECK (actor_kind = 'primary'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  supersedes_id TEXT REFERENCES obligation_assessments (record_id),
  FOREIGN KEY (topic_id, contract_revision, obligation_id) REFERENCES obligations (topic_id, contract_revision, obligation_id),
  CHECK ((disposition IS NOT NULL AND state IS NULL) OR (disposition IS NULL AND state IS 'open')),
  CHECK ((json_extract(confidence, '$.basis') IS 'unknown' AND json_type(confidence, '$.reason') IS 'text'
          AND length(trim(json_extract(confidence, '$.reason'))) > 0)
      OR (json_extract(confidence, '$.basis') IS 'recorded_assessment' AND state IS NULL))
) STRICT;

-- Part 01's contract_approval_bound_to_revision admits the whole approval
-- family and contract_content_immutable retains that decision pointer. Use
-- that authority here rather than maintaining a second approval-kind list.
CREATE TRIGGER obligation_assessments_bound BEFORE INSERT ON obligation_assessments
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i JOIN operation_receipts o ON o.invocation_id = i.invocation_id
    JOIN contract_revisions c ON c.topic_id = i.topic_id AND c.revision = i.contract_revision
    JOIN operator_decisions d ON d.decision_id = c.approved_by_decision_id
  WHERE i.invocation_id = NEW.invocation_id AND o.operation_id = NEW.recorded_by_operation_id
    AND i.topic_id = NEW.topic_id AND o.topic_id = NEW.topic_id
    AND i.kind IN ('research_pass', 'checkpoint') AND i.admission_context = 'contract/1'
    AND i.contract_revision = NEW.contract_revision AND o.contract_revision = NEW.contract_revision
    AND c.content_hash = NEW.contract_content_hash AND c.framing_version = NEW.framing_version
    AND json_extract(c.document, '$.eligibility_protocol.protocol_version') IS NEW.eligibility_protocol_version
    AND c.status IN ('approved', 'superseded') AND d.disposition = 'approved'
    AND d.topic_id = NEW.topic_id AND d.subject_revision = c.revision AND d.subject_hash = c.content_hash)
BEGIN
  SELECT RAISE(ABORT, 'obligation assessment needs its primary commit and exact approved contract pins');
END;

CREATE TRIGGER obligation_assessments_scheme BEFORE INSERT ON obligation_assessments
WHEN json_extract(NEW.confidence, '$.basis') IS 'recorded_assessment' AND NOT EXISTS (
  SELECT 1 FROM contract_revisions c, json_each(c.document, '$.confidence_scheme.labels') label
  WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision
    AND json_extract(NEW.confidence, '$.scheme.scheme_id') IS json_extract(c.document, '$.confidence_scheme.scheme_id')
    AND json_extract(NEW.confidence, '$.scheme.version') IS json_extract(c.document, '$.confidence_scheme.version')
    AND json_extract(NEW.confidence, '$.label') IS label.key
    AND json_extract(NEW.confidence, '$.assessed_by_invocation_id') IS NEW.invocation_id)
BEGIN
  SELECT RAISE(ABORT, 'confidence must name the approved scheme, label and committing invocation');
END;

CREATE TRIGGER obligation_assessments_predecessor BEFORE INSERT ON obligation_assessments
WHEN NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM obligation_assessments p WHERE p.record_id = NEW.supersedes_id
    AND p.topic_id = NEW.topic_id AND p.obligation_id = NEW.obligation_id)
BEGIN
  SELECT RAISE(ABORT, 'obligation predecessor belongs to this topic and obligation');
END;
CREATE TRIGGER obligation_assessments_immutable_u BEFORE UPDATE ON obligation_assessments
BEGIN
  SELECT RAISE(ABORT, 'obligation assessments are append-only');
END;
CREATE TRIGGER obligation_assessments_immutable_d BEFORE DELETE ON obligation_assessments
BEGIN
  SELECT RAISE(ABORT, 'obligation assessments are retained');
END;
