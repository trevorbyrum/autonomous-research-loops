-- Gen-2 authoritative engine store — SQLite DDL draft (task 0a deliverable 3).
--
-- Trace: design review §5 ("Use normalized rows for contract revisions/
-- obligations, queue entries, invocations/leases, review episodes and
-- triggers, evidence observations/assessments, operator decisions, operation
-- receipts, and outbox deliveries"; the commit_outcome protocol; crash
-- fencing) and §8 (typed evidence records); flow doc S4 step 2 (retrieval-
-- event inventory, four candidate units), S4 steps 8-9 (verification receipts,
-- accepted-support boundary), §3 (decision receipts), S8 (outbox, per-sink
-- receipts), §4.4 (typed holds); docs/gen2/BOUNDARIES.md Router ("every state
-- commit via commit_outcome"; "holds (typed, owned, deadlined)"); invariant IDs
-- refer to docs/gen2/INVARIANTS.md.
--
-- Scope: this is the store the router alone writes (boundaries.toml: only the
-- `store` module may use sqlite3 and only `router` may import it). Constraints
-- below express uniqueness and fencing wherever SQLite can; the rest is router
-- logic, listed in gen2/store/README.md along with what this draft defers.
--
-- Connection settings: every connection applies gen2/store/connection.sql
-- (foreign_keys = ON, recursive_triggers = ON) and reads them back before use;
-- the store module adds journal_mode = WAL, synchronous = FULL and a
-- busy_timeout, and keeps transactions short (INVARIANTS C-8). Without
-- recursive_triggers, a REPLACE conflict resolution deletes a stored row
-- without firing its BEFORE DELETE guard, so the history guarantees below
-- hold only on a connection that applied connection.sql (INVARIANTS C-11).
--
-- Conventions: every table is STRICT; IDs are prefix-typed TEXT matching
-- gen2/schema/common.schema.json; timestamps are RFC 3339 UTC TEXT validated
-- at the router boundary; JSON columns carry json_valid() checks; booleans are
-- INTEGER 0/1. In CHECK constraints a NULL result passes, so every
-- conditional check below tests IS NOT NULL explicitly. Records of fact
-- (receipts, decisions, transitions, triggers) reject UPDATE and DELETE.
-- EVERY table has a BEFORE DELETE guard (tools/check_gen2_schemas.py fails
-- the build otherwise), and no constraint carries an ON CONFLICT clause:
-- nothing here is deletable through an ordinary write path, and REPLACE
-- cannot overwrite a stored row (INVARIANTS C-11). Retention/pruning is a
-- deferred, explicit policy (gen2/store/README.md).

PRAGMA user_version = 1;

-- ===========================================================================
-- Queue and contracts
-- ===========================================================================

-- trace: design review §5 (queue entries), §4 (fleet-prefixed topic IDs);
-- flow S3 ("-> queue"), S7 outcomes; INVARIANTS G-8, G-9, RG-1b(c).
-- state_revision is the optimistic-concurrency counter commit_outcome binds
-- to (expected_state_revision); it only ever advances by exactly one.
CREATE TABLE queue_entries (
  topic_id TEXT PRIMARY KEY,
  fleet_id TEXT NOT NULL,
  priority INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'awaiting_brief_confirmation', 'scoping', 'awaiting_scope_approval',
    'awaiting_contract_approval', 'queued', 'active', 'resting', 'held',
    'completed_with_qualified_conclusions', 'capability_blocked',
    'stopped_for_resources', 'awaiting_judgment', 'retired')),
  active_contract_revision INTEGER,
  state_revision INTEGER NOT NULL DEFAULT 0 CHECK (state_revision >= 0),
  paused_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (substr(topic_id, 1, length(fleet_id) + 1) = fleet_id || ':'),
  FOREIGN KEY (topic_id, active_contract_revision)
    REFERENCES contract_revisions (topic_id, revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TRIGGER queue_state_revision_advances_by_one
BEFORE UPDATE OF state_revision ON queue_entries
WHEN NEW.state_revision IS NOT OLD.state_revision + 1
BEGIN
  SELECT RAISE(ABORT, 'state_revision advances by exactly one per commit (RG-1b)');
END;

CREATE TRIGGER queue_topic_identity_immutable
BEFORE UPDATE OF topic_id, fleet_id ON queue_entries
BEGIN
  SELECT RAISE(ABORT, 'topic identity is immutable');
END;

CREATE TRIGGER queue_entries_no_delete BEFORE DELETE ON queue_entries
BEGIN
  SELECT RAISE(ABORT, 'queue entries are never deleted; retirement is an operator decision (C-11)');
END;

-- G-8: completion is bound to operator approval of the CURRENT dossier
-- revision; an approval of an older revision is stale.
CREATE TRIGGER queue_completion_needs_current_dossier_approval
BEFORE UPDATE OF status ON queue_entries
WHEN NEW.status = 'completed_with_qualified_conclusions'
  AND OLD.status IS NOT NEW.status
  AND NOT EXISTS (
    SELECT 1 FROM operator_decisions d
    WHERE d.topic_id = NEW.topic_id
      AND d.kind = 'completion_approval'
      AND d.disposition = 'approved'
      AND d.dossier_revision = (SELECT max(x.dossier_revision) FROM dossiers x WHERE x.topic_id = NEW.topic_id))
BEGIN
  SELECT RAISE(ABORT, 'completion requires operator approval of the current dossier revision (G-8)');
END;

-- P-6 / G-9: retirement is an operator decision.
CREATE TRIGGER queue_retirement_needs_operator_decision
BEFORE UPDATE OF status ON queue_entries
WHEN NEW.status = 'retired'
  AND OLD.status IS NOT NEW.status
  AND NOT EXISTS (
    SELECT 1 FROM operator_decisions d
    WHERE d.topic_id = NEW.topic_id AND d.kind = 'retirement' AND d.disposition = 'approved')
BEGIN
  SELECT RAISE(ABORT, 'retirement requires an approved operator retirement decision');
END;

-- trace: flow S3 (Contract v2, hash-locked with its protocol revision);
-- design review §4 (immutable approved revision; older revisions preserved);
-- schema contract-v2.schema.json; INVARIANTS G-1.
-- Every revision's content is immutable once written (a change is a new
-- revision); only status and the approving decision move, draft ->
-- approved -> superseded.
CREATE TABLE contract_revisions (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  parent_revision INTEGER,
  protocol_revision INTEGER NOT NULL CHECK (protocol_revision >= 1),
  framing_version INTEGER NOT NULL CHECK (framing_version >= 1),
  content_hash TEXT NOT NULL UNIQUE CHECK (content_hash GLOB 'sha256:*' AND length(content_hash) = 71),
  document TEXT NOT NULL CHECK (json_valid(document)),
  status TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'superseded')),
  approved_by_decision_id TEXT REFERENCES operator_decisions (decision_id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, revision),
  FOREIGN KEY (topic_id, parent_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK (status = 'draft' OR approved_by_decision_id IS NOT NULL),
  CHECK (json_extract(document, '$.topic_id') IS topic_id
     AND json_extract(document, '$.revision') IS revision
     AND json_extract(document, '$.content_hash') IS content_hash
     AND json_extract(document, '$.protocol_revision') IS protocol_revision
     AND json_extract(document, '$.facet_map.framing_version') IS framing_version)
) STRICT;

CREATE UNIQUE INDEX contract_one_approved_revision_per_topic
  ON contract_revisions (topic_id) WHERE status = 'approved';

CREATE TRIGGER contract_content_immutable
BEFORE UPDATE ON contract_revisions
WHEN NEW.document IS NOT OLD.document
  OR NEW.content_hash IS NOT OLD.content_hash
  OR NEW.protocol_revision IS NOT OLD.protocol_revision
  OR NEW.framing_version IS NOT OLD.framing_version
  OR NEW.parent_revision IS NOT OLD.parent_revision
  OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.revision IS NOT OLD.revision
  OR NEW.created_at IS NOT OLD.created_at
  OR (OLD.approved_by_decision_id IS NOT NULL AND NEW.approved_by_decision_id IS NOT OLD.approved_by_decision_id)
BEGIN
  SELECT RAISE(ABORT, 'contract revisions are immutable; amend by writing a new revision (G-1)');
END;

CREATE TRIGGER contract_status_forward_only
BEFORE UPDATE OF status ON contract_revisions
WHEN NOT ((OLD.status = 'draft' AND NEW.status IN ('draft', 'approved', 'superseded'))
       OR (OLD.status = 'approved' AND NEW.status IN ('approved', 'superseded'))
       OR (OLD.status = 'superseded' AND NEW.status = 'superseded'))
BEGIN
  SELECT RAISE(ABORT, 'contract status moves draft -> approved -> superseded only');
END;

CREATE TRIGGER contract_no_delete BEFORE DELETE ON contract_revisions
BEGIN
  SELECT RAISE(ABORT, 'contract revisions are never deleted (G-1)');
END;

-- trace: flow S3 (templated, importance-rated, facet-tagged obligations),
-- §6.4 (only operator-confirmed ratings authorize auto-promotion);
-- methodology §2 (GRADE bands 7-9 / 4-6 / 1-3, score optional);
-- adjudication (a)G-R9, K-R4, K-A7; INVARIANTS G-2.
-- Normalized projection of one contract revision's obligations; immutable
-- with that revision. Proposed and operator-approved importance are separate
-- columns: only the operator's band authorizes anything.
CREATE TABLE obligations (
  topic_id TEXT NOT NULL,
  contract_revision INTEGER NOT NULL,
  obligation_id TEXT NOT NULL,
  template_id TEXT NOT NULL,
  template_version INTEGER NOT NULL CHECK (template_version >= 1),
  claim_type TEXT NOT NULL,
  facet_ids TEXT NOT NULL CHECK (json_valid(facet_ids) AND json_type(facet_ids) = 'array' AND json_array_length(facet_ids) >= 1),
  stopping_profile_id TEXT NOT NULL,
  exploratory INTEGER NOT NULL CHECK (exploratory IN (0, 1)),
  proposed_importance_source TEXT CHECK (proposed_importance_source IN ('jev_score', 'primary_draft')),
  proposed_importance_score INTEGER CHECK (proposed_importance_score BETWEEN 1 AND 9),
  proposed_decision_receipt_id TEXT REFERENCES decision_receipts (decision_receipt_id),
  operator_importance_band TEXT CHECK (operator_importance_band IN ('critical', 'important', 'limited')),
  operator_importance_score INTEGER CHECK (operator_importance_score BETWEEN 1 AND 9),
  operator_rating_decision_id TEXT REFERENCES operator_decisions (decision_id),
  PRIMARY KEY (topic_id, contract_revision, obligation_id),
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK ((proposed_importance_source IS NULL) = (proposed_importance_score IS NULL)),
  CHECK (proposed_importance_source IS NOT 'jev_score' OR proposed_decision_receipt_id IS NOT NULL),
  CHECK ((operator_importance_band IS NULL) = (operator_rating_decision_id IS NULL)),
  CHECK (operator_importance_score IS NULL OR operator_importance_band IS NOT NULL),
  CHECK (operator_importance_score IS NULL
      OR (operator_importance_band = 'critical' AND operator_importance_score BETWEEN 7 AND 9)
      OR (operator_importance_band = 'important' AND operator_importance_score BETWEEN 4 AND 6)
      OR (operator_importance_band = 'limited' AND operator_importance_score BETWEEN 1 AND 3))
) STRICT;

CREATE TRIGGER obligations_immutable BEFORE UPDATE ON obligations
BEGIN
  SELECT RAISE(ABORT, 'obligations are immutable with their contract revision');
END;

CREATE TRIGGER obligations_no_delete BEFORE DELETE ON obligations
BEGIN
  SELECT RAISE(ABORT, 'obligations are never deleted');
END;

-- ===========================================================================
-- Leases and invocations
-- ===========================================================================

-- trace: flow S4 ("router mints a fenced lease"); design review §5 (step 3:
-- current lease and generation; crash fencing), §3 (gen-1 accepted an
-- unminted run with generation -1); BOUNDARIES.md Router ("leases with
-- generations"); INVARIANTS RG-1a, RG-1b(c).
-- One live lease per (topic, scope); generations strictly increase per topic;
-- release is write-once.
CREATE TABLE leases (
  lease_id TEXT PRIMARY KEY CHECK (lease_id GLOB 'lease_*'),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  scope TEXT NOT NULL CHECK (scope IN ('research', 'discovery', 'verification', 'checkpoint')),
  generation INTEGER NOT NULL CHECK (generation >= 0),
  station_id TEXT NOT NULL,
  granted_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  released_at TEXT,
  release_reason TEXT,
  UNIQUE (topic_id, generation),
  CHECK ((released_at IS NULL) = (release_reason IS NULL))
) STRICT;

CREATE UNIQUE INDEX leases_one_live_per_topic_scope
  ON leases (topic_id, scope) WHERE released_at IS NULL;

CREATE TRIGGER leases_generation_increases
BEFORE INSERT ON leases
WHEN NEW.generation <= (SELECT coalesce(max(generation), -1) FROM leases WHERE topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'lease generation must exceed every earlier generation for the topic');
END;

CREATE TRIGGER leases_release_final_identity_immutable
BEFORE UPDATE ON leases
WHEN OLD.released_at IS NOT NULL
  OR NEW.lease_id IS NOT OLD.lease_id
  OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.scope IS NOT OLD.scope
  OR NEW.generation IS NOT OLD.generation
  OR NEW.station_id IS NOT OLD.station_id
  OR NEW.granted_at IS NOT OLD.granted_at
BEGIN
  SELECT RAISE(ABORT, 'a released lease is final and lease identity is immutable (RG-1a: one release)');
END;

CREATE TRIGGER leases_no_delete BEFORE DELETE ON leases
BEGIN
  SELECT RAISE(ABORT, 'leases are never deleted');
END;

-- trace: design review §5 (launch intent before spawn; job handle + host/
-- container + boot identity + start fingerprint, never a bare PID), §6 (one
-- lifecycle for every kind); BOUNDARIES.md Station supervisor; schema
-- invocation.schema.json; INVARIANTS L-1, L-2, L-3, L-8, RG-2.
-- There is no PID column. Delegates run under their parent's reservation.
CREATE TABLE invocations (
  invocation_id TEXT PRIMARY KEY CHECK (invocation_id GLOB 'inv_*'),
  kind TEXT NOT NULL CHECK (kind IN ('research_pass', 'discovery', 'delegate', 'verification', 'checkpoint')),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  parent_invocation_id TEXT REFERENCES invocations (invocation_id),
  lease_id TEXT REFERENCES leases (lease_id),
  capability_id TEXT NOT NULL UNIQUE CHECK (capability_id GLOB 'cap_*'),
  config_bundle_hash TEXT NOT NULL,
  contract_revision INTEGER,
  state TEXT NOT NULL CHECK (state IN ('admitted', 'launching', 'running', 'result_ready', 'committed', 'cancelled', 'failed', 'outcome_unknown')),
  admitted_at TEXT NOT NULL,
  deadline_at TEXT NOT NULL,
  launch_intent_at TEXT,
  job_handle TEXT UNIQUE,
  host_id TEXT,
  container_id TEXT,
  boot_id TEXT,
  start_fingerprint TEXT,
  cancel_requested_at TEXT,
  cancel_requested_by TEXT CHECK (cancel_requested_by IN ('router', 'operator')),
  descendants_confirmed_at TEXT,
  result_payload_digest TEXT,
  result_staged_at TEXT,
  outcome_unknown_since TEXT,
  state_changed_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK (kind != 'delegate' OR parent_invocation_id IS NOT NULL),
  CHECK (kind = 'delegate' OR lease_id IS NOT NULL),
  CHECK (launch_intent_at IS NOT NULL OR state IN ('admitted', 'cancelled')),
  CHECK (state != 'running' OR (job_handle IS NOT NULL AND host_id IS NOT NULL AND boot_id IS NOT NULL AND start_fingerprint IS NOT NULL)),
  CHECK (state NOT IN ('result_ready', 'committed') OR (result_payload_digest IS NOT NULL AND result_staged_at IS NOT NULL)),
  CHECK (state != 'cancelled' OR descendants_confirmed_at IS NOT NULL),
  CHECK (state != 'outcome_unknown' OR outcome_unknown_since IS NOT NULL),
  CHECK ((cancel_requested_at IS NULL) = (cancel_requested_by IS NULL))
) STRICT;

CREATE TRIGGER invocations_start_admitted
BEFORE INSERT ON invocations
WHEN NEW.state IS NOT 'admitted'
BEGIN
  SELECT RAISE(ABORT, 'invocations are created admitted and move only through L-1 transitions');
END;

CREATE TRIGGER invocations_allowed_transitions
BEFORE UPDATE OF state ON invocations
WHEN NEW.state IS NOT OLD.state AND NOT (
     (OLD.state = 'admitted' AND NEW.state IN ('launching', 'cancelled'))
  OR (OLD.state = 'launching' AND NEW.state IN ('running', 'failed', 'cancelled', 'outcome_unknown'))
  OR (OLD.state = 'running' AND NEW.state IN ('result_ready', 'failed', 'cancelled', 'outcome_unknown'))
  OR (OLD.state = 'result_ready' AND NEW.state IN ('committed', 'failed', 'outcome_unknown'))
  OR (OLD.state = 'outcome_unknown' AND NEW.state IN ('running', 'result_ready', 'committed', 'failed', 'cancelled')))
BEGIN
  SELECT RAISE(ABORT, 'invocation state transition not allowed (INVARIANTS.md L-1)');
END;

CREATE TRIGGER invocations_identity_immutable
BEFORE UPDATE ON invocations
WHEN NEW.invocation_id IS NOT OLD.invocation_id
  OR NEW.kind IS NOT OLD.kind
  OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.parent_invocation_id IS NOT OLD.parent_invocation_id
  OR NEW.lease_id IS NOT OLD.lease_id
  OR NEW.capability_id IS NOT OLD.capability_id
  OR NEW.config_bundle_hash IS NOT OLD.config_bundle_hash
  OR (OLD.launch_intent_at IS NOT NULL AND NEW.launch_intent_at IS NOT OLD.launch_intent_at)
  OR (OLD.job_handle IS NOT NULL AND NEW.job_handle IS NOT OLD.job_handle)
  OR (OLD.boot_id IS NOT NULL AND NEW.boot_id IS NOT OLD.boot_id)
  OR (OLD.start_fingerprint IS NOT NULL AND NEW.start_fingerprint IS NOT OLD.start_fingerprint)
  OR (OLD.result_payload_digest IS NOT NULL AND NEW.result_payload_digest IS NOT OLD.result_payload_digest)
BEGIN
  SELECT RAISE(ABORT, 'invocation identity, launch intent, process identity and staged result are write-once');
END;

CREATE TRIGGER invocations_no_delete BEFORE DELETE ON invocations
BEGIN
  SELECT RAISE(ABORT, 'invocations are never deleted');
END;

-- trace: INVARIANTS L-1 (transition audit); flow §4.1.
CREATE TABLE invocation_transitions (
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  seq INTEGER NOT NULL CHECK (seq >= 1),
  from_state TEXT,
  to_state TEXT NOT NULL,
  at TEXT NOT NULL,
  cause TEXT NOT NULL,
  PRIMARY KEY (invocation_id, seq)
) STRICT;

CREATE TRIGGER invocation_transitions_append_only_u BEFORE UPDATE ON invocation_transitions
BEGIN
  SELECT RAISE(ABORT, 'invocation transitions are append-only');
END;
CREATE TRIGGER invocation_transitions_append_only_d BEFORE DELETE ON invocation_transitions
BEGIN
  SELECT RAISE(ABORT, 'invocation transitions are append-only');
END;

-- ===========================================================================
-- Artifacts, operator decisions, dossiers
-- ===========================================================================

-- trace: design review §5 ("Artifacts and the sole-writer promise": immutable,
-- content-addressed artifacts staged by trusted station code); INVARIANTS C-9.
-- Supporting table (see README "Supporting tables").
CREATE TABLE artifacts (
  content_hash TEXT PRIMARY KEY CHECK (content_hash GLOB 'sha256:*' AND length(content_hash) = 71),
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
  media_type TEXT NOT NULL,
  topic_id TEXT REFERENCES queue_entries (topic_id),
  staged_by_invocation_id TEXT REFERENCES invocations (invocation_id),
  staged_at TEXT NOT NULL
) STRICT;

CREATE TRIGGER artifacts_immutable_u BEFORE UPDATE ON artifacts
BEGIN
  SELECT RAISE(ABORT, 'artifacts are immutable');
END;
CREATE TRIGGER artifacts_immutable_d BEFORE DELETE ON artifacts
BEGIN
  SELECT RAISE(ABORT, 'artifact records are never deleted (retention is a separate, explicit policy)');
END;

-- trace: design review §5 (normalized rows: operator decisions), §8 (approval
-- bound to an exact dossier revision); flow S1 (brief confirmation), S3
-- (framework/ratings/set/method approval), S7, §2 (blind samples: initial
-- disposition captured separately from advised feedback); BOUNDARIES.md
-- Operator; INVARIANTS G-2, G-4, G-8, D-9.
-- subject_hash is the exact content decided on; completion approvals name
-- the dossier revision.
CREATE TABLE operator_decisions (
  decision_id TEXT PRIMARY KEY CHECK (decision_id GLOB 'opd_*'),
  topic_id TEXT REFERENCES queue_entries (topic_id),
  kind TEXT NOT NULL CHECK (kind IN (
    'brief_confirmation', 'scope_approval', 'rating_approval', 'contract_approval',
    'amendment_approval', 'reframe_approval', 'completion_approval', 'retirement',
    'hold_clearance', 'publication_approval', 'blind_initial_disposition', 'advised_feedback')),
  disposition TEXT NOT NULL CHECK (disposition IN ('approved', 'rejected', 'deferred', 'recorded')),
  subject_kind TEXT NOT NULL,
  subject_ref TEXT NOT NULL,
  subject_hash TEXT CHECK (subject_hash IS NULL OR (subject_hash GLOB 'sha256:*' AND length(subject_hash) = 71)),
  dossier_revision INTEGER,
  operator_id TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  notes TEXT,
  FOREIGN KEY (topic_id, dossier_revision) REFERENCES dossiers (topic_id, dossier_revision),
  CHECK (kind NOT IN ('rating_approval', 'contract_approval', 'amendment_approval', 'reframe_approval',
                      'completion_approval', 'publication_approval') OR subject_hash IS NOT NULL),
  CHECK (kind != 'completion_approval' OR dossier_revision IS NOT NULL),
  CHECK (kind NOT IN ('blind_initial_disposition', 'advised_feedback') OR disposition = 'recorded')
) STRICT;

CREATE TRIGGER operator_decisions_immutable_u BEFORE UPDATE ON operator_decisions
BEGIN
  SELECT RAISE(ABORT, 'operator decisions are immutable records; supersede with a new decision');
END;
CREATE TRIGGER operator_decisions_immutable_d BEFORE DELETE ON operator_decisions
BEGIN
  SELECT RAISE(ABORT, 'operator decisions are never deleted');
END;

-- trace: flow S7 (versioned stopping dossier; approval bound to that exact
-- revision), §4.6; design review §8 ("The dossier is a versioned decision
-- input"); BOUNDARIES.md Evidence accounting ("versioned dossiers");
-- INVARIANTS G-8, E-6. Supporting table (see README).
CREATE TABLE dossiers (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  dossier_revision INTEGER NOT NULL CHECK (dossier_revision >= 1),
  contract_revision INTEGER NOT NULL,
  evidence_revision INTEGER NOT NULL CHECK (evidence_revision >= 1),
  evaluator_version TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  document_ref TEXT NOT NULL REFERENCES artifacts (content_hash),
  created_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, dossier_revision),
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision)
) STRICT;

CREATE TRIGGER dossiers_immutable_u BEFORE UPDATE ON dossiers
BEGIN
  SELECT RAISE(ABORT, 'dossiers are immutable; every completion permanently carries its evidence');
END;
CREATE TRIGGER dossiers_immutable_d BEFORE DELETE ON dossiers
BEGIN
  SELECT RAISE(ABORT, 'dossiers are never deleted');
END;

-- ===========================================================================
-- Commit receipts and ordinals
-- ===========================================================================

-- trace: design review §5 commit_outcome steps 3-5 (replay an identical
-- operation, reject a conflicting reuse, check lease/generation before
-- mutation, receipt after commit), §3 (gen-1 split finalization and replay
-- probes); schema commit-outcome.schema.json#/$defs/receipt; INVARIANTS C-4,
-- C-5, RG-1a, RG-1b.
-- operation_id is the idempotency key; the router compares
-- request_fingerprint on reuse. One final outcome per invocation; one commit
-- per produced state revision; the lease must be the invocation's (or, for a
-- delegate, its parent's), live, same topic and same generation.
CREATE TABLE operation_receipts (
  operation_id TEXT PRIMARY KEY CHECK (operation_id GLOB 'op_*'),
  receipt_id TEXT NOT NULL UNIQUE CHECK (receipt_id GLOB 'rcpt_*'),
  operation_kind TEXT NOT NULL CHECK (operation_kind IN ('final_outcome', 'interim_transition')),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  request_fingerprint TEXT NOT NULL CHECK (request_fingerprint GLOB 'sha256:*'),
  payload_digest TEXT NOT NULL CHECK (payload_digest GLOB 'sha256:*'),
  lease_id TEXT NOT NULL REFERENCES leases (lease_id),
  lease_generation INTEGER NOT NULL,
  contract_revision INTEGER NOT NULL,
  config_bundle_hash TEXT NOT NULL,
  state_revision_before INTEGER NOT NULL CHECK (state_revision_before >= 0),
  state_revision_after INTEGER NOT NULL,
  validator_version TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  committed_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK (state_revision_after = state_revision_before + 1),
  CHECK (json_extract(receipt, '$.operation_id') IS operation_id
     AND json_extract(receipt, '$.receipt_id') IS receipt_id
     AND json_extract(receipt, '$.payload_digest') IS payload_digest)
) STRICT;

CREATE UNIQUE INDEX operation_receipts_one_final_outcome_per_invocation
  ON operation_receipts (invocation_id) WHERE operation_kind = 'final_outcome';

CREATE UNIQUE INDEX operation_receipts_one_commit_per_state_revision
  ON operation_receipts (topic_id, state_revision_after);

CREATE TRIGGER operation_receipts_fenced
BEFORE INSERT ON operation_receipts
WHEN (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id
  OR (SELECT topic_id FROM leases WHERE lease_id = NEW.lease_id) IS NOT NEW.topic_id
  OR (SELECT generation FROM leases WHERE lease_id = NEW.lease_id) IS NOT NEW.lease_generation
  OR (SELECT released_at FROM leases WHERE lease_id = NEW.lease_id) IS NOT NULL
  OR NEW.lease_id IS NOT (
       SELECT coalesce(i.lease_id, p.lease_id)
       FROM invocations i LEFT JOIN invocations p ON p.invocation_id = i.parent_invocation_id
       WHERE i.invocation_id = NEW.invocation_id)
BEGIN
  SELECT RAISE(ABORT, 'commit rejected: cross-topic, foreign lease, stale generation or released lease (RG-1b, RG-5)');
END;

CREATE TRIGGER operation_receipts_immutable_u BEFORE UPDATE ON operation_receipts
BEGIN
  SELECT RAISE(ABORT, 'operation receipts are immutable (RG-1b)');
END;
CREATE TRIGGER operation_receipts_immutable_d BEFORE DELETE ON operation_receipts
BEGIN
  SELECT RAISE(ABORT, 'operation receipts are never deleted; replay protection depends on them');
END;

-- trace: design review §5 ("Review, verification, and delegate invocations
-- must not increment ordinary-research ordinals accidentally"), §10 release
-- gate 1 (one ordinal); INVARIANTS C-7, RG-1a.
-- Dense per topic; one per research_pass invocation, bound to its final
-- outcome.
CREATE TABLE research_ordinals (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
  invocation_id TEXT NOT NULL UNIQUE REFERENCES invocations (invocation_id),
  operation_id TEXT NOT NULL UNIQUE REFERENCES operation_receipts (operation_id),
  PRIMARY KEY (topic_id, ordinal)
) STRICT;

CREATE TRIGGER research_ordinals_only_research_final_outcomes
BEFORE INSERT ON research_ordinals
WHEN (SELECT kind FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT 'research_pass'
  OR (SELECT operation_kind FROM operation_receipts WHERE operation_id = NEW.operation_id) IS NOT 'final_outcome'
  OR (SELECT invocation_id FROM operation_receipts WHERE operation_id = NEW.operation_id) IS NOT NEW.invocation_id
  OR (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id
  OR NEW.ordinal IS NOT (SELECT coalesce(max(ordinal), 0) + 1 FROM research_ordinals WHERE topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'ordinals go only to research_pass final outcomes, densely, one per invocation (C-7)');
END;

CREATE TRIGGER research_ordinals_immutable_u BEFORE UPDATE ON research_ordinals
BEGIN
  SELECT RAISE(ABORT, 'ordinals are immutable');
END;
CREATE TRIGGER research_ordinals_immutable_d BEFORE DELETE ON research_ordinals
BEGIN
  SELECT RAISE(ABORT, 'ordinals are never deleted');
END;

-- ===========================================================================
-- Review episodes and triggers
-- ===========================================================================

-- trace: flow S5 (types and cadence; fixed floor + coalesced signal queue);
-- design review §5 (review episodes and triggers); INVARIANTS G-12.
CREATE TABLE review_episodes (
  episode_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  kind TEXT NOT NULL CHECK (kind IN ('fixed_cadence', 'obligations_scope', 'method_fit', 'facet_audit', 'calibration', 'state_integrity_audit')),
  opened_at TEXT NOT NULL,
  opened_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  closed_at TEXT,
  closed_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  CHECK ((closed_at IS NULL) = (closed_by_operation_id IS NULL))
) STRICT;

CREATE TRIGGER review_episodes_close_once
BEFORE UPDATE ON review_episodes
WHEN OLD.closed_at IS NOT NULL
  OR NEW.episode_id IS NOT OLD.episode_id OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.kind IS NOT OLD.kind OR NEW.opened_at IS NOT OLD.opened_at
BEGIN
  SELECT RAISE(ABORT, 'a closed review episode is final');
END;
CREATE TRIGGER review_episodes_no_delete BEFORE DELETE ON review_episodes
BEGIN
  SELECT RAISE(ABORT, 'review episodes are never deleted');
END;

-- trace: flow S5 (seven method-fit reason codes, cheap deterministic signals
-- first, primary-recorded semantic observations; causes recorded, never
-- dropped); design review §5 ("Unique trigger identities remain handled after
-- their episode closes; pruning must preserve the receipts/tombstones
-- necessary to prevent replay"), §3 (gen-1 stall-trigger replay opened a new
-- episode); adjudication (a)G-A7; INVARIANTS RG-1a, RG-1b(e), G-12.
-- trigger_identity is a deterministic hash of (topic, reason, cause ref,
-- source revision), so a replayed trigger collides instead of re-opening.
CREATE TABLE review_triggers (
  trigger_identity TEXT PRIMARY KEY CHECK (trigger_identity GLOB 'sha256:*' AND length(trigger_identity) = 71),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  reason_code TEXT NOT NULL CHECK (reason_code IN (
    'cadence_floor', 'persistent_contradiction', 'yield_exhaustion_open_obligations',
    'cross_context_heterogeneity', 'definitional_disagreement', 'evidence_type_mismatch',
    'inapplicable_synthesis_plan', 'out_of_frame_concepts',
    'amendment', 'reframe', 'capability_change', 'facet_audit_due', 'calibration_due')),
  signal_source TEXT NOT NULL CHECK (signal_source IN ('deterministic', 'primary_observation', 'operator')),
  cause_ref TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  recorded_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  episode_id TEXT REFERENCES review_episodes (episode_id),
  handled_at TEXT
) STRICT;

CREATE TRIGGER review_triggers_handled_is_final
BEFORE UPDATE ON review_triggers
WHEN OLD.handled_at IS NOT NULL
  OR NEW.trigger_identity IS NOT OLD.trigger_identity OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.reason_code IS NOT OLD.reason_code OR NEW.cause_ref IS NOT OLD.cause_ref
  OR (OLD.episode_id IS NOT NULL AND NEW.episode_id IS NOT OLD.episode_id)
BEGIN
  SELECT RAISE(ABORT, 'a handled trigger stays handled; trigger identity is immutable (RG-1b(e))');
END;
CREATE TRIGGER review_triggers_no_delete BEFORE DELETE ON review_triggers
BEGIN
  SELECT RAISE(ABORT, 'review triggers are never deleted; replay protection depends on them');
END;

-- ===========================================================================
-- Capability facts and holds
-- ===========================================================================

-- trace: flow §4.2 (capability facts first-class, dated, alert on
-- transition; the vault outage example), §4.3; BOUNDARIES.md Gateway (a
-- failed secrets read is a dated "secrets backend failing" fact, never "no
-- key configured"); INVARIANTS H-2. DEVIATION PROPOSAL (not in the 0a brief's
-- table list) — see README.
-- A transition is a new row superseding the current one; one current fact
-- per capability.
CREATE TABLE capability_facts (
  fact_id TEXT PRIMARY KEY,
  capability TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('healthy', 'degraded', 'failing', 'unknown')),
  detail TEXT NOT NULL,
  since TEXT NOT NULL,
  last_success_at TEXT,
  affected_lanes TEXT NOT NULL CHECK (json_valid(affected_lanes) AND json_type(affected_lanes) = 'array'),
  observed_by_invocation_id TEXT REFERENCES invocations (invocation_id),
  superseded_by_fact_id TEXT REFERENCES capability_facts (fact_id),
  recorded_at TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX capability_facts_one_current_per_capability
  ON capability_facts (capability) WHERE superseded_by_fact_id IS NULL;

CREATE TRIGGER capability_facts_supersede_only
BEFORE UPDATE ON capability_facts
WHEN OLD.superseded_by_fact_id IS NOT NULL
  OR NEW.fact_id IS NOT OLD.fact_id OR NEW.capability IS NOT OLD.capability
  OR NEW.state IS NOT OLD.state OR NEW.detail IS NOT OLD.detail OR NEW.since IS NOT OLD.since
  OR NEW.last_success_at IS NOT OLD.last_success_at OR NEW.affected_lanes IS NOT OLD.affected_lanes
BEGIN
  SELECT RAISE(ABORT, 'capability facts are dated records: supersede, never edit');
END;
CREATE TRIGGER capability_facts_no_delete BEFORE DELETE ON capability_facts
BEGIN
  SELECT RAISE(ABORT, 'capability facts are never deleted');
END;

-- trace: flow §4.4 (typed holds with owner and deadline; what clears them;
-- failed hold persistence is a control failure), S4 step 8 / §6.6
-- (adjudication holds, class judgment); design review §6, §7 (cause,
-- recoverability and required authority are separate dimensions; a model
-- label never clears an operator hold); BOUNDARIES.md Router ("holds (typed,
-- owned, deadlined)"); INVARIANTS H-3, RG-3, V-5.
CREATE TABLE holds (
  hold_id TEXT PRIMARY KEY CHECK (hold_id GLOB 'hold_*'),
  topic_id TEXT REFERENCES queue_entries (topic_id),
  subject_ref TEXT NOT NULL,
  hold_class TEXT NOT NULL CHECK (hold_class IN ('transient', 'capability', 'scope', 'judgment', 'unknown')),
  cause TEXT NOT NULL CHECK (length(cause) > 0),
  recoverability TEXT NOT NULL CHECK (recoverability IN ('retry_within_budget', 'needs_remediation', 'needs_decision', 'unknown')),
  required_authority TEXT NOT NULL CHECK (required_authority IN ('router', 'primary', 'operator')),
  owner TEXT NOT NULL CHECK (length(owner) > 0),
  deadline_at TEXT NOT NULL,
  clears_when TEXT NOT NULL CHECK (length(clears_when) > 0),
  capability_fact_id TEXT REFERENCES capability_facts (fact_id),
  created_at TEXT NOT NULL,
  created_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  cleared_at TEXT,
  cleared_by_decision_id TEXT REFERENCES operator_decisions (decision_id),
  cleared_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  CHECK (hold_class != 'capability' OR capability_fact_id IS NOT NULL),
  CHECK (cleared_at IS NULL OR cleared_by_decision_id IS NOT NULL OR cleared_by_operation_id IS NOT NULL),
  CHECK (required_authority != 'operator' OR cleared_at IS NULL OR cleared_by_decision_id IS NOT NULL)
) STRICT;

CREATE TRIGGER holds_clear_once_identity_immutable
BEFORE UPDATE ON holds
WHEN OLD.cleared_at IS NOT NULL
  OR NEW.hold_id IS NOT OLD.hold_id OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.subject_ref IS NOT OLD.subject_ref OR NEW.hold_class IS NOT OLD.hold_class
  OR NEW.required_authority IS NOT OLD.required_authority OR NEW.created_at IS NOT OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'a cleared hold is final; hold identity, class and authority are immutable');
END;
CREATE TRIGGER holds_no_delete BEFORE DELETE ON holds
BEGIN
  SELECT RAISE(ABORT, 'holds are never deleted');
END;

-- ===========================================================================
-- Evidence: observations, the four candidate units, assessments
-- ===========================================================================

-- trace: flow S4 step 2 (every search records request identity, coverage and
-- yield; captured by station/gateway, persisted by the router), §4.3;
-- design review §8 (search observation fields; unknown usage distinguished
-- from zero), §9 (complete normalized request identity; payload validation);
-- gateway/docs/STATION-CONTRACT.md §2 (coverage vocabulary);
-- BOUNDARIES.md Gateway; INVARIANTS RG-4, RG-U, E-2, H-2, H-5.
-- A result count exists only for a successful search state; every degraded
-- state carries an error class, and NULL means unknown — never 0.
CREATE TABLE search_observations (
  observation_id TEXT PRIMARY KEY,
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  request_identity TEXT NOT NULL CHECK (request_identity GLOB 'sha256:*'),
  attempt INTEGER NOT NULL CHECK (attempt >= 1),
  lane TEXT NOT NULL,
  request TEXT NOT NULL CHECK (json_valid(request)),
  obligation_ids TEXT NOT NULL CHECK (json_valid(obligation_ids) AND json_type(obligation_ids) = 'array'),
  started_at TEXT NOT NULL,
  ended_at TEXT,
  coverage_state TEXT NOT NULL CHECK (coverage_state IN (
    'searched_ok', 'searched_empty', 'not_searched', 'provider_unavailable',
    'auth_failed', 'metadata_only', 'exhausted', 'unknown')),
  result_count INTEGER CHECK (result_count >= 0),
  error_class TEXT CHECK (error_class IN (
    'payload_invalid', 'timeout', 'rate_limited', 'breaker_open', 'budget_refused',
    'provider_outage', 'credentials_rejected', 'credentials_not_configured',
    'secrets_backend_failing', 'transport_failure', 'telemetry_missing', 'partial_pagination')),
  capability_fact_id TEXT REFERENCES capability_facts (fact_id),
  policy_version TEXT NOT NULL,
  cost_units INTEGER CHECK (cost_units >= 0),
  gateway_call_ref TEXT,
  UNIQUE (invocation_id, request_identity, attempt),
  CHECK (coverage_state NOT IN ('searched_ok', 'metadata_only') OR (result_count IS NOT NULL AND result_count >= 1)),
  CHECK (coverage_state != 'searched_empty' OR (result_count IS NOT NULL AND result_count = 0)),
  CHECK (coverage_state IN ('searched_ok', 'searched_empty', 'metadata_only') OR result_count IS NULL),
  CHECK (coverage_state NOT IN ('provider_unavailable', 'auth_failed', 'unknown') OR error_class IS NOT NULL),
  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR error_class IS NULL),
  CHECK (error_class IS NOT 'secrets_backend_failing' OR capability_fact_id IS NOT NULL)
) STRICT;

CREATE TRIGGER search_observations_immutable_u BEFORE UPDATE ON search_observations
BEGIN
  SELECT RAISE(ABORT, 'observations are immutable; a retry is a new attempt');
END;
CREATE TRIGGER search_observations_immutable_d BEFORE DELETE ON search_observations
BEGIN
  SELECT RAISE(ABORT, 'observations are never deleted');
END;

-- trace: flow S4 step 2 ("retrieved candidate identities at retrieval time
-- (before any screening)"; unit 1: retrieved records); adjudication (a)G-A2,
-- (b)7; INVARIANTS E-2, E-3.
-- Rows exist only for observations whose search actually returned records.
CREATE TABLE retrieval_events (
  event_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL REFERENCES search_observations (observation_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  provider_record_id TEXT NOT NULL,
  rank INTEGER CHECK (rank >= 1),
  captured_at TEXT NOT NULL,
  UNIQUE (observation_id, provider_record_id)
) STRICT;

CREATE TRIGGER retrieval_events_from_successful_search
BEFORE INSERT ON retrieval_events
WHEN (SELECT coverage_state FROM search_observations WHERE observation_id = NEW.observation_id) NOT IN ('searched_ok', 'metadata_only')
  OR (SELECT topic_id FROM search_observations WHERE observation_id = NEW.observation_id) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'retrieval events come only from successful searches of the same topic (E-2)');
END;
CREATE TRIGGER retrieval_events_immutable_u BEFORE UPDATE ON retrieval_events
BEGIN
  SELECT RAISE(ABORT, 'retrieval events are immutable');
END;
CREATE TRIGGER retrieval_events_immutable_d BEFORE DELETE ON retrieval_events
BEGIN
  SELECT RAISE(ABORT, 'retrieval events are never deleted');
END;

-- trace: flow S4 step 2 (unit 2: deduplicated works/studies); design review
-- §4 (link shared primary sources across fleets without counting copied
-- research as independent), §8 (group multiple reports of one study);
-- methodology §4 (dedup removes identity duplicates only); INVARIANTS E-3.
-- study_group_id groups reports of one study (lineage), set by a recorded
-- assessment — not by deduplication.
CREATE TABLE works (
  work_id TEXT PRIMARY KEY CHECK (work_id GLOB 'wrk_*'),
  identity_scheme TEXT NOT NULL CHECK (identity_scheme IN ('doi', 'arxiv', 'pmid', 'isbn', 'url', 'gateway_record')),
  identity_value TEXT NOT NULL,
  study_group_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (identity_scheme, identity_value)
) STRICT;

CREATE TRIGGER works_identity_immutable
BEFORE UPDATE ON works
WHEN NEW.work_id IS NOT OLD.work_id
  OR NEW.identity_scheme IS NOT OLD.identity_scheme
  OR NEW.identity_value IS NOT OLD.identity_value
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'work identity is immutable');
END;
CREATE TRIGGER works_no_delete BEFORE DELETE ON works
BEGIN
  SELECT RAISE(ABORT, 'works are never deleted; retrieval provenance links to them (C-11)');
END;

-- trace: flow S4 step 2 (cross-lane overlap never multiplies evidence);
-- INVARIANTS E-3. Each retrieved record maps to at most one work.
CREATE TABLE record_work_links (
  event_id TEXT PRIMARY KEY REFERENCES retrieval_events (event_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  dedup_method_version TEXT NOT NULL,
  linked_at TEXT NOT NULL
) STRICT;

CREATE TRIGGER record_work_links_immutable_u BEFORE UPDATE ON record_work_links
BEGIN
  SELECT RAISE(ABORT, 'record-work links are immutable');
END;
CREATE TRIGGER record_work_links_no_delete BEFORE DELETE ON record_work_links
BEGIN
  SELECT RAISE(ABORT, 'record-work links are never deleted (C-11)');
END;

-- trace: flow S4 step 3 (deterministic predicates -> Jev -> primary; every
-- exclusion reason-coded, framing-versioned, reversible), §5 (screening in
-- shadow until qualified); design review §7 (screening assessment fields);
-- methodology §4; INVARIANTS E-3 (unit 3), E-5, E-9, D-5.
-- Deferral is the ABSENCE of a row (resource-deferred candidates stay
-- unassessed). Reversal is a new row that supersedes. A decision-provider
-- assessment may only exist here if its receipt had qualified authority —
-- shadow/advisory screening never writes authoritative assessments.
CREATE TABLE screening_assessments (
  assessment_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  contract_revision INTEGER NOT NULL,
  eligibility_protocol_version INTEGER NOT NULL CHECK (eligibility_protocol_version >= 1),
  framing_version INTEGER NOT NULL CHECK (framing_version >= 1),
  stage TEXT NOT NULL CHECK (stage IN ('metadata', 'abstract', 'full_text')),
  decision TEXT NOT NULL CHECK (decision IN ('include', 'exclude', 'borderline')),
  reason_code TEXT,
  criterion_results TEXT NOT NULL CHECK (json_valid(criterion_results)),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('code', 'decision_provider', 'primary', 'operator')),
  invocation_id TEXT REFERENCES invocations (invocation_id),
  decision_receipt_id TEXT REFERENCES decision_receipts (decision_receipt_id),
  operator_decision_id TEXT REFERENCES operator_decisions (decision_id),
  supersedes_assessment_id TEXT UNIQUE REFERENCES screening_assessments (assessment_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK (decision != 'exclude' OR reason_code IS NOT NULL),
  CHECK (actor_kind != 'decision_provider' OR decision_receipt_id IS NOT NULL),
  CHECK (actor_kind != 'operator' OR operator_decision_id IS NOT NULL),
  CHECK (actor_kind NOT IN ('decision_provider', 'primary') OR invocation_id IS NOT NULL)
) STRICT;

CREATE TRIGGER screening_provider_needs_qualified_authority
BEFORE INSERT ON screening_assessments
WHEN NEW.actor_kind = 'decision_provider'
  AND (SELECT authority_level FROM decision_receipts WHERE decision_receipt_id = NEW.decision_receipt_id) IS NOT 'qualified'
BEGIN
  SELECT RAISE(ABORT, 'shadow/advisory decision providers never write authoritative screening assessments (D-5)');
END;
CREATE TRIGGER screening_assessments_immutable_u BEFORE UPDATE ON screening_assessments
BEGIN
  SELECT RAISE(ABORT, 'assessments are immutable; reverse by superseding (E-9)');
END;
CREATE TRIGGER screening_assessments_immutable_d BEFORE DELETE ON screening_assessments
BEGIN
  SELECT RAISE(ABORT, 'exclusions are retained with provenance, never deleted (E-9)');
END;

-- trace: flow S4 steps 6 and 9 (provisional capture vs accepted support),
-- §5 (hybrid verification: inline for load-bearing claims); design review
-- §9; adjudication (b)7, (d)3; INVARIANTS E-3 (unit 4: accepted claims),
-- V-2, V-4.
-- Claims start provisional. A load-bearing claim becomes accepted support
-- only with a supporting verification receipt at or above its required tier.
CREATE TABLE claims (
  claim_id TEXT NOT NULL CHECK (claim_id GLOB 'clm_*'),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  text_ref TEXT NOT NULL REFERENCES artifacts (content_hash),
  producer_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  load_bearing INTEGER NOT NULL CHECK (load_bearing IN (0, 1)),
  required_access_tier TEXT CHECK (required_access_tier IN ('bibliographic', 'abstract', 'full_text', 'reproduced')),
  status TEXT NOT NULL CHECK (status IN ('provisional', 'accepted_support', 'contested', 'rejected', 'quarantined', 'superseded')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (claim_id, revision),
  CHECK (load_bearing = 0 OR required_access_tier IS NOT NULL)
) STRICT;

CREATE TRIGGER claims_start_provisional
BEFORE INSERT ON claims
WHEN NEW.status IS NOT 'provisional'
BEGIN
  SELECT RAISE(ABORT, 'claims are captured provisional (V-4)');
END;

CREATE TRIGGER claims_accepted_support_needs_receipt
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (
  SELECT 1 FROM verification_receipts v
  WHERE v.claim_id = NEW.claim_id AND v.claim_revision = NEW.revision AND v.verdict = 'supports'
    AND (CASE v.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
     >= (CASE NEW.required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END))
BEGIN
  SELECT RAISE(ABORT, 'a load-bearing claim needs a supporting verification receipt at its required tier (V-2, V-4)');
END;

CREATE TRIGGER claims_identity_immutable
BEFORE UPDATE ON claims
WHEN NEW.claim_id IS NOT OLD.claim_id OR NEW.revision IS NOT OLD.revision
  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.text_ref IS NOT OLD.text_ref
  OR NEW.producer_invocation_id IS NOT OLD.producer_invocation_id
  OR NEW.load_bearing IS NOT OLD.load_bearing OR NEW.required_access_tier IS NOT OLD.required_access_tier
BEGIN
  SELECT RAISE(ABORT, 'claim content is immutable per revision; write a new revision');
END;
CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims
BEGIN
  SELECT RAISE(ABORT, 'claims are never deleted');
END;

-- trace: methodology §4-§5 (claim-source-obligation links; independence via
-- lineage; contribution types); adjudication (b)5 (independent checking,
-- independent evidence origins and different analytical methods are
-- distinct fields); design review §8 (timestamped source-claim-obligation
-- links); INVARIANTS V-9.
CREATE TABLE claim_source_links (
  claim_id TEXT NOT NULL,
  claim_revision INTEGER NOT NULL,
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL,
  topic_id TEXT NOT NULL,
  contract_revision INTEGER NOT NULL,
  obligation_id TEXT NOT NULL,
  spans TEXT NOT NULL CHECK (json_valid(spans) AND json_type(spans) = 'array'),
  contribution TEXT NOT NULL CHECK (contribution IN ('answer', 'confidence', 'applicability', 'options', 'question_formulation', 'boundary_condition', 'contradiction')),
  evidence_origin_lineage TEXT NOT NULL,
  analytical_method TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (claim_id, claim_revision, work_id, obligation_id),
  FOREIGN KEY (claim_id, claim_revision) REFERENCES claims (claim_id, revision),
  FOREIGN KEY (topic_id, contract_revision, obligation_id) REFERENCES obligations (topic_id, contract_revision, obligation_id)
) STRICT;

CREATE TRIGGER claim_source_links_immutable_u BEFORE UPDATE ON claim_source_links
BEGIN
  SELECT RAISE(ABORT, 'claim-source links are immutable per claim revision');
END;
CREATE TRIGGER claim_source_links_no_delete BEFORE DELETE ON claim_source_links
BEGIN
  SELECT RAISE(ABORT, 'claim-source links are never deleted (C-11)');
END;

-- trace: flow S4 step 8 (receipt bindings; role separation and required
-- access tier enforced by the router; identical canonical bytes allowed,
-- the producer's unvalidated extraction not), S4 step 4 (exact quote match);
-- BOUNDARIES.md Verifier; schema verification-receipt.schema.json;
-- adjudication (a)K-A2, (b)5; INVARIANTS V-1, V-2, V-3, RG-5.
-- The verifier must be a separate verification-kind invocation of the same
-- topic, not launched by the producer, checking the claim's actual producer.
CREATE TABLE verification_receipts (
  verification_receipt_id TEXT PRIMARY KEY CHECK (verification_receipt_id GLOB 'ver_*'),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  claim_id TEXT NOT NULL,
  claim_revision INTEGER NOT NULL,
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL,
  cited_spans TEXT NOT NULL CHECK (json_valid(cited_spans) AND json_type(cited_spans) = 'array' AND json_array_length(cited_spans) >= 1),
  obtained_content_hash TEXT NOT NULL CHECK (obtained_content_hash GLOB 'sha256:*'),
  access_tier TEXT NOT NULL CHECK (access_tier IN ('bibliographic', 'abstract', 'full_text', 'reproduced')),
  use TEXT NOT NULL CHECK (use IN ('load_bearing', 'sampled')),
  required_access_tier TEXT NOT NULL CHECK (required_access_tier IN ('bibliographic', 'abstract', 'full_text', 'reproduced')),
  acquisition TEXT NOT NULL CHECK (json_valid(acquisition)),
  extraction_method TEXT NOT NULL CHECK (extraction_method IN ('verifier_extraction', 'validated_extraction', 'canonical_bytes')),
  extraction_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  extraction_validation_ref TEXT,
  producer_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  verifier_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  verdict TEXT NOT NULL CHECK (verdict IN ('supports', 'partially_supports', 'does_not_support', 'cannot_assess_at_required_tier')),
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  verified_at TEXT NOT NULL,
  FOREIGN KEY (claim_id, claim_revision) REFERENCES claims (claim_id, revision),
  CHECK (producer_invocation_id != verifier_invocation_id),
  CHECK (extraction_invocation_id != producer_invocation_id OR extraction_validation_ref IS NOT NULL),
  CHECK (extraction_method != 'validated_extraction' OR extraction_validation_ref IS NOT NULL),
  CHECK (verdict != 'supports'
      OR (CASE access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
      >= (CASE required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END))
) STRICT;

CREATE TRIGGER verification_receipts_role_separation
BEFORE INSERT ON verification_receipts
WHEN (SELECT kind FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT 'verification'
  OR (SELECT topic_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT NEW.topic_id
  OR (SELECT parent_invocation_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NEW.producer_invocation_id
  OR (SELECT producer_invocation_id FROM claims WHERE claim_id = NEW.claim_id AND revision = NEW.claim_revision) IS NOT NEW.producer_invocation_id
  OR (SELECT topic_id FROM claims WHERE claim_id = NEW.claim_id AND revision = NEW.claim_revision) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'verification must come from a separate verification invocation of the same topic, independent of the claim producer (RG-5)');
END;
CREATE TRIGGER verification_receipts_immutable_u BEFORE UPDATE ON verification_receipts
BEGIN
  SELECT RAISE(ABORT, 'verification receipts are immutable');
END;
CREATE TRIGGER verification_receipts_immutable_d BEFORE DELETE ON verification_receipts
BEGIN
  SELECT RAISE(ABORT, 'verification receipts are never deleted');
END;

-- trace: flow S4 step 4 (exact byte match against a versioned source
-- artifact with normalization and span offsets comes first; NLI is the
-- semantic alarm), §6.7 (a failed entailment check quarantines the quote, not
-- the source); BOUNDARIES.md Tier-0 checker (versioned checker identity);
-- INVARIANTS V-6, V-7.
CREATE TABLE quote_checks (
  check_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL,
  claim_revision INTEGER NOT NULL,
  source_artifact_hash TEXT NOT NULL REFERENCES artifacts (content_hash),
  span_start INTEGER NOT NULL CHECK (span_start >= 0),
  span_end INTEGER NOT NULL,
  normalization_version TEXT NOT NULL,
  exact_match TEXT NOT NULL CHECK (exact_match IN ('matched', 'mismatch')),
  nli_checker TEXT,
  nli_checker_version TEXT,
  nli_signal TEXT NOT NULL CHECK (nli_signal IN ('pass', 'alarm', 'not_run')),
  quote_quarantined INTEGER NOT NULL CHECK (quote_quarantined IN (0, 1)),
  checked_at TEXT NOT NULL,
  FOREIGN KEY (claim_id, claim_revision) REFERENCES claims (claim_id, revision),
  CHECK (span_end > span_start),
  CHECK (nli_signal = 'not_run' OR (nli_checker IS NOT NULL AND nli_checker_version IS NOT NULL)),
  CHECK (nli_signal != 'alarm' OR quote_quarantined = 1),
  CHECK (exact_match != 'mismatch' OR quote_quarantined = 1)
) STRICT;

CREATE TRIGGER quote_checks_immutable_u BEFORE UPDATE ON quote_checks
BEGIN
  SELECT RAISE(ABORT, 'quote checks are immutable; re-capture writes a new check');
END;
CREATE TRIGGER quote_checks_no_delete BEFORE DELETE ON quote_checks
BEGIN
  SELECT RAISE(ABORT, 'quote checks are never deleted; a quarantine stays on record (C-11)');
END;

-- ===========================================================================
-- Decision layer
-- ===========================================================================

-- trace: flow §2 (DecisionSpec; qualification bound to the exact spec);
-- schema decision-spec.schema.json; INVARIANTS D-1, D-4.
-- Supporting table (see README): immutable specs referenced by receipts.
CREATE TABLE decision_specs (
  spec_hash TEXT PRIMARY KEY CHECK (spec_hash GLOB 'sha256:*' AND length(spec_hash) = 71),
  spec_id TEXT NOT NULL UNIQUE CHECK (spec_id GLOB 'dspec_*'),
  decision_class TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('jev', 'llm_fallback')),
  document TEXT NOT NULL CHECK (json_valid(document)),
  created_at TEXT NOT NULL,
  CHECK (json_extract(document, '$.spec_id') IS spec_id
     AND json_extract(document, '$.provider') IS provider
     AND json_extract(document, '$.decision_class') IS decision_class)
) STRICT;

CREATE TRIGGER decision_specs_immutable_u BEFORE UPDATE ON decision_specs
BEGIN
  SELECT RAISE(ABORT, 'decision specs are immutable; a behavior change is a new spec (D-4)');
END;
CREATE TRIGGER decision_specs_immutable_d BEFORE DELETE ON decision_specs
BEGIN
  SELECT RAISE(ABORT, 'decision specs are never deleted');
END;

-- trace: flow §3 steps 2-5 (receipt links inputs, provider response, policy,
-- authorization, action, outcome; raw digest retained), §2 (fallback carries
-- no synthetic probability; unqualified = advisory at most; bad input
-- abstains), §6.8 (calibration custody in the router's store); schema
-- decision-receipt.schema.json; BOUNDARIES.md Decision layer; INVARIANTS
-- D-1, D-2, D-3, D-5, D-6, D-10, D-12.
CREATE TABLE decision_receipts (
  decision_receipt_id TEXT PRIMARY KEY CHECK (decision_receipt_id GLOB 'dec_*'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  spec_hash TEXT NOT NULL REFERENCES decision_specs (spec_hash),
  decision_class TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('jev', 'llm_fallback')),
  input_status TEXT NOT NULL CHECK (input_status IN ('complete', 'oversized', 'stale', 'truncated', 'disallowed')),
  response_status TEXT NOT NULL CHECK (response_status IN ('answered', 'abstained', 'rejected_input', 'error', 'timeout')),
  raw_response_digest TEXT CHECK (raw_response_digest IS NULL OR raw_response_digest GLOB 'sha256:*'),
  answer TEXT CHECK (answer IS NULL OR json_valid(answer)),
  policy_id TEXT NOT NULL,
  policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
  authority_level TEXT NOT NULL CHECK (authority_level IN ('shadow', 'advisory', 'qualified')),
  qualification_ref TEXT,
  action TEXT NOT NULL CHECK (action IN ('commit_reversible_action', 'attach_proposal', 'escalate', 'abstain_hold', 'shadow_log_only')),
  commit_operation_id TEXT REFERENCES operation_receipts (operation_id) DEFERRABLE INITIALLY DEFERRED,
  hold_id TEXT REFERENCES holds (hold_id) DEFERRABLE INITIALLY DEFERRED,
  blind_sample INTEGER NOT NULL CHECK (blind_sample IN (0, 1)),
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  decided_at TEXT NOT NULL,
  CHECK (qualification_ref IS NOT NULL OR authority_level IN ('shadow', 'advisory')),
  CHECK (action != 'commit_reversible_action' OR (authority_level = 'qualified' AND commit_operation_id IS NOT NULL)),
  CHECK (authority_level != 'shadow' OR action = 'shadow_log_only'),
  CHECK (input_status = 'complete' OR response_status = 'rejected_input'),
  CHECK (response_status != 'answered' OR (answer IS NOT NULL AND raw_response_digest IS NOT NULL)),
  CHECK (response_status = 'answered' OR answer IS NULL),
  CHECK (response_status = 'answered' OR action IN ('escalate', 'abstain_hold', 'shadow_log_only')),
  CHECK (action != 'abstain_hold' OR hold_id IS NOT NULL),
  CHECK (provider != 'llm_fallback' OR answer IS NULL OR (
         json_extract(answer, '$.primitive') IS 'label'
     AND json_type(answer, '$.probability') IS NULL
     AND json_type(answer, '$.confidence') IS NULL
     AND json_type(answer, '$.distribution') IS NULL)),
  CHECK (provider != 'jev' OR answer IS NULL OR coalesce(json_extract(answer, '$.primitive'), '') IN ('noul', 'choice', 'score')),
  CHECK (answer IS NULL OR coalesce(json_extract(answer, '$.primitive'), '') NOT IN ('choice', 'score')
      OR coalesce(json_type(answer, '$.confidence'), 'missing') IN ('real', 'integer')),
  CHECK (answer IS NULL OR json_extract(answer, '$.primitive') IS NOT 'noul'
      OR (coalesce(json_type(answer, '$.probability'), 'missing') IN ('real', 'integer') AND json_type(answer, '$.confidence') IS NULL))
) STRICT;

CREATE TRIGGER decision_receipts_match_spec
BEFORE INSERT ON decision_receipts
WHEN (SELECT provider FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.provider
  OR (SELECT decision_class FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.decision_class
  OR (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'decision receipt provider/class must match its spec; invocation topic must match');
END;
CREATE TRIGGER decision_receipts_immutable_u BEFORE UPDATE ON decision_receipts
BEGIN
  SELECT RAISE(ABORT, 'decision receipts are immutable; overrides join as separate records (D-9)');
END;
CREATE TRIGGER decision_receipts_immutable_d BEFORE DELETE ON decision_receipts
BEGIN
  SELECT RAISE(ABORT, 'decision receipts are never deleted (replay audit, D-10)');
END;

-- ===========================================================================
-- Publication
-- ===========================================================================

-- trace: flow S8 publication contract items 1 and 5 (outbox event
-- referencing an immutable manifest, committed atomically with the approved
-- revision; corrections and checkpoint publications are new events); design
-- review §9; schema publication-manifest.schema.json; BOUNDARIES.md Router
-- ("publication outbox commits with immutable manifests"); INVARIANTS P-1,
-- P-5.
-- Generations increase per topic; unapproved work is never published.
CREATE TABLE outbox_events (
  outbox_event_id TEXT PRIMARY KEY CHECK (outbox_event_id GLOB 'obx_*'),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  manifest_id TEXT NOT NULL UNIQUE CHECK (manifest_id GLOB 'man_*'),
  manifest_hash TEXT NOT NULL UNIQUE CHECK (manifest_hash GLOB 'sha256:*'),
  artifact_kind TEXT NOT NULL CHECK (artifact_kind IN ('completion_publication', 'evidence_correction', 'checkpoint_publication')),
  generation INTEGER NOT NULL CHECK (generation >= 1),
  supersedes_generation INTEGER,
  source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
  approval_decision_id TEXT NOT NULL REFERENCES operator_decisions (decision_id),
  expected_sinks TEXT NOT NULL CHECK (json_valid(expected_sinks) AND json_type(expected_sinks) = 'array' AND json_array_length(expected_sinks) >= 1),
  manifest TEXT NOT NULL CHECK (json_valid(manifest)),
  committed_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  UNIQUE (topic_id, generation),
  CHECK (supersedes_generation IS NULL OR supersedes_generation < generation),
  CHECK (generation != 1 OR supersedes_generation IS NULL),
  CHECK (json_extract(manifest, '$.manifest_id') IS manifest_id
     AND json_extract(manifest, '$.generation') IS generation
     AND json_extract(manifest, '$.topic_id') IS topic_id)
) STRICT;

CREATE TRIGGER outbox_events_generation_increases
BEFORE INSERT ON outbox_events
WHEN NEW.generation <= (SELECT coalesce(max(generation), 0) FROM outbox_events WHERE topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'publication generations strictly increase per topic (P-2)');
END;
CREATE TRIGGER outbox_events_only_approved
BEFORE INSERT ON outbox_events
WHEN (SELECT disposition FROM operator_decisions WHERE decision_id = NEW.approval_decision_id) IS NOT 'approved'
  OR (SELECT topic_id FROM operator_decisions WHERE decision_id = NEW.approval_decision_id) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'unapproved work is never published (P-5)');
END;
CREATE TRIGGER outbox_events_immutable_u BEFORE UPDATE ON outbox_events
BEGIN
  SELECT RAISE(ABORT, 'outbox events and their manifests are immutable (P-1)');
END;
CREATE TRIGGER outbox_events_immutable_d BEFORE DELETE ON outbox_events
BEGIN
  SELECT RAISE(ABORT, 'outbox events are never deleted');
END;

-- trace: flow S8 item 2 (per-sink receipts; supersession/tombstones
-- acknowledged per sink); BOUNDARIES.md Projector / publication;
-- adjudication (a)G-A1 (mutable delivery receipts stored separately);
-- INVARIANTS P-2, P-4.
-- Projector-owned records, written through the router's ack_delivery.
CREATE TABLE sink_delivery_receipts (
  delivery_receipt_id TEXT PRIMARY KEY,
  outbox_event_id TEXT NOT NULL REFERENCES outbox_events (outbox_event_id),
  sink TEXT NOT NULL CHECK (sink IN ('neo4j', 'qdrant')),
  attempt INTEGER NOT NULL CHECK (attempt >= 1),
  status TEXT NOT NULL CHECK (status IN ('delivered', 'failed', 'skipped_superseded')),
  tombstones_acknowledged INTEGER NOT NULL CHECK (tombstones_acknowledged IN (0, 1)),
  error_class TEXT,
  attempted_at TEXT NOT NULL,
  acked_at TEXT,
  UNIQUE (outbox_event_id, sink, attempt),
  CHECK (status != 'failed' OR error_class IS NOT NULL),
  CHECK (status != 'delivered' OR (acked_at IS NOT NULL AND tombstones_acknowledged = 1))
) STRICT;

CREATE TRIGGER sink_delivery_receipts_expected_sink
BEFORE INSERT ON sink_delivery_receipts
WHEN NOT EXISTS (
  SELECT 1 FROM outbox_events e, json_each(e.expected_sinks) j
  WHERE e.outbox_event_id = NEW.outbox_event_id AND j.value = NEW.sink)
BEGIN
  SELECT RAISE(ABORT, 'delivery receipt for a sink the manifest does not expect');
END;
CREATE TRIGGER sink_delivery_receipts_immutable_u BEFORE UPDATE ON sink_delivery_receipts
BEGIN
  SELECT RAISE(ABORT, 'delivery receipts are immutable; a retry is a new attempt');
END;
CREATE TRIGGER sink_delivery_receipts_no_delete BEFORE DELETE ON sink_delivery_receipts
BEGIN
  SELECT RAISE(ABORT, 'delivery receipts are never deleted (C-11)');
END;

-- trace: flow S8 item 2 ("old retries cannot overwrite newer generations");
-- BOUNDARIES.md Projector / publication (must never overwrite newer
-- generations with old retries); INVARIANTS P-2.
-- Per-sink high-water mark; it never decreases.
CREATE TABLE sink_generations (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  sink TEXT NOT NULL CHECK (sink IN ('neo4j', 'qdrant')),
  delivered_generation INTEGER NOT NULL CHECK (delivered_generation >= 1),
  delivered_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, sink)
) STRICT;

CREATE TRIGGER sink_generations_never_regress
BEFORE UPDATE ON sink_generations
WHEN NEW.delivered_generation < OLD.delivered_generation
  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.sink IS NOT OLD.sink
BEGIN
  SELECT RAISE(ABORT, 'an old retry never overwrites a newer delivered generation (P-2)');
END;
CREATE TRIGGER sink_generations_no_delete BEFORE DELETE ON sink_generations
BEGIN
  SELECT RAISE(ABORT, 'a sink high-water mark is never deleted: delete-and-reinsert would regress it (P-2, C-11)');
END;

-- ===========================================================================
-- Audit
-- ===========================================================================

-- trace: design review §5 step 4 (the transaction records an audit event);
-- flow §3 step 6 (control incidents), §4; INVARIANTS C-4, RG-1b (rejected
-- operations are logged here — a rejection writes no receipt).
-- Supporting table (see README).
CREATE TABLE audit_events (
  audit_event_id TEXT PRIMARY KEY CHECK (audit_event_id GLOB 'aud_*'),
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  topic_id TEXT,
  invocation_id TEXT,
  operation_id TEXT,
  detail TEXT NOT NULL CHECK (json_valid(detail))
) STRICT;

CREATE TRIGGER audit_events_append_only_u BEFORE UPDATE ON audit_events
BEGIN
  SELECT RAISE(ABORT, 'audit events are append-only');
END;
CREATE TRIGGER audit_events_append_only_d BEFORE DELETE ON audit_events
BEGIN
  SELECT RAISE(ABORT, 'audit events are append-only');
END;
