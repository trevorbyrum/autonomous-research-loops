-- 2c-2b2a: attributed branch/contradiction registry histories.
-- trace: flow S4/S6/S7, methodology section 4, INVARIANTS E-7/C-12.
CREATE TABLE registry_dispositions (
  disposition_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  registry_kind TEXT NOT NULL CHECK (registry_kind IN ('contradiction', 'branch')),
  registry_id TEXT NOT NULL CHECK (length(registry_id) > 0),
  subject TEXT NOT NULL CHECK (length(subject) > 0),
  disposition TEXT NOT NULL,
  contract_revision INTEGER NOT NULL,
  eligibility_protocol_version INTEGER NOT NULL CHECK (eligibility_protocol_version >= 1),
  framing_version INTEGER NOT NULL CHECK (framing_version >= 1),
  supersedes_id TEXT REFERENCES registry_dispositions (disposition_id),
  reason_code TEXT NOT NULL CHECK (length(reason_code) > 0),
  evidence_refs TEXT NOT NULL CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array' AND json_array_length(evidence_refs) > 0),
  actor_kind TEXT NOT NULL CHECK (actor_kind = 'primary'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK ((registry_kind = 'contradiction' AND disposition IN ('unresolved', 'resolved', 'contested'))
      OR (registry_kind = 'branch' AND disposition IN ('promote', 'park', 'drop')))
) STRICT;
CREATE TRIGGER registry_dispositions_bound BEFORE INSERT ON registry_dispositions
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
  SELECT RAISE(ABORT, 'registry disposition needs its primary commit and pinned protocol/framing (E-7, C-12)');
END;
CREATE TRIGGER registry_dispositions_predecessor BEFORE INSERT ON registry_dispositions
WHEN NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM registry_dispositions p WHERE p.disposition_id = NEW.supersedes_id
    AND p.topic_id = NEW.topic_id AND p.registry_kind = NEW.registry_kind AND p.registry_id = NEW.registry_id)
BEGIN
  SELECT RAISE(ABORT, 'registry predecessor must exist for this topic, kind and identity');
END;
CREATE TRIGGER registry_dispositions_immutable_u BEFORE UPDATE ON registry_dispositions
BEGIN
  SELECT RAISE(ABORT, 'registry dispositions are append-only');
END;
CREATE TRIGGER registry_dispositions_immutable_d BEFORE DELETE ON registry_dispositions
BEGIN
  SELECT RAISE(ABORT, 'registry disposition history is retained');
END;
