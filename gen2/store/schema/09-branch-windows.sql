-- 2d-2 / DEBT-032: attributable branch/window links; flow S4/S7, E-7.
-- Revisions are deliberately absent: readers derive them from the window.
-- trace: flow S4/S7, methodology section 4, INVARIANTS E-7/C-12/G-1.
CREATE TABLE branch_windows (
  association_id TEXT PRIMARY KEY CHECK (length(association_id) > 0),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  registry_id TEXT NOT NULL CHECK (length(registry_id) > 0),
  branch_disposition_id TEXT NOT NULL REFERENCES registry_dispositions (disposition_id),
  window_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  actor_kind TEXT NOT NULL CHECK (actor_kind = 'primary'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER branch_windows_branch BEFORE INSERT ON branch_windows
WHEN NOT EXISTS (
  SELECT 1 FROM registry_dispositions b WHERE b.disposition_id = NEW.branch_disposition_id
    AND b.topic_id = NEW.topic_id AND b.registry_kind = 'branch' AND b.registry_id = NEW.registry_id)
BEGIN
  SELECT RAISE(ABORT, 'association needs its same-topic registered branch identity');
END;
CREATE TRIGGER branch_windows_window BEFORE INSERT ON branch_windows
WHEN NOT EXISTS (
  SELECT 1 FROM invocations w JOIN contract_revisions c ON c.topic_id = w.topic_id AND c.revision = w.contract_revision
  WHERE w.invocation_id = NEW.window_invocation_id AND w.topic_id = NEW.topic_id
    AND w.kind = 'research_pass' AND w.admission_context = 'contract/1'
    AND c.status IN ('approved', 'superseded') AND c.approved_by_decision_id IS NOT NULL)
BEGIN
  SELECT RAISE(ABORT, 'association needs a same-topic contract-admitted research window');
END;
CREATE TRIGGER branch_windows_commit BEFORE INSERT ON branch_windows
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i JOIN operation_receipts o ON o.invocation_id = i.invocation_id
  WHERE i.invocation_id = NEW.invocation_id AND o.operation_id = NEW.recorded_by_operation_id
    AND i.topic_id = NEW.topic_id AND o.topic_id = NEW.topic_id
    AND i.kind IN ('research_pass', 'checkpoint') AND i.admission_context = 'contract/1'
    AND o.contract_revision = i.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'association needs its primary governed commit');
END;
CREATE TRIGGER branch_windows_immutable_u BEFORE UPDATE ON branch_windows
BEGIN
  SELECT RAISE(ABORT, 'branch/window associations are append-only');
END;
CREATE TRIGGER branch_windows_immutable_d BEFORE DELETE ON branch_windows
BEGIN
  SELECT RAISE(ABORT, 'branch/window provenance is retained');
END;
