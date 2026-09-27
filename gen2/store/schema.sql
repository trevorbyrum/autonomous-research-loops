-- Gen-2 authoritative engine store — SQLite DDL draft (task 0a deliverable 3).
--
-- Trace: design review §5 ("Use normalized rows for contract revisions/
-- obligations, queue entries, invocations/leases, review episodes and
-- triggers, evidence observations/assessments, operator decisions, operation
-- receipts, and outbox deliveries"; the commit_outcome protocol; crash
-- fencing) and §8 (typed evidence records); flow doc S4 step 2 (retrieval-
-- event inventory, four candidate units), S4 steps 8-9 (verification receipts,
-- accepted-support boundary), §3 (decision receipts), S8 (outbox, per-
-- connector receipts; operator ruling 2026-09-26), §4.4 (typed holds); docs/gen2/BOUNDARIES.md Router ("every state
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
-- to (expected_state_revision); it only ever advances by exactly one, and
-- every status change advances it (so a decision bound to a state revision
-- authorizes at most one transition). A topic is created at the start of
-- intake; terminal statuses are reached only by a decision-bound transition
-- (Astra 0a review A2). The historical importer (task 0b) gets its own
-- explicit, audited path; it does not reuse ordinary creation.
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
  status_decision_id TEXT REFERENCES operator_decisions (decision_id),
  paused_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (substr(topic_id, 1, length(fleet_id) + 1) = fleet_id || ':'),
  CHECK ((status IN ('completed_with_qualified_conclusions', 'retired')) = (status_decision_id IS NOT NULL)),
  FOREIGN KEY (topic_id, active_contract_revision)
    REFERENCES contract_revisions (topic_id, revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TRIGGER queue_state_revision_advances_by_one
BEFORE UPDATE OF state_revision ON queue_entries
WHEN NEW.state_revision IS NOT OLD.state_revision + 1
BEGIN
  SELECT RAISE(ABORT, 'state_revision advances by exactly one per commit (RG-1b)');
END;

CREATE TRIGGER queue_entries_created_at_intake
BEFORE INSERT ON queue_entries
WHEN NEW.status IS NOT 'awaiting_brief_confirmation' OR NEW.state_revision IS NOT 0
BEGIN
  SELECT RAISE(ABORT, 'a topic is created awaiting brief confirmation at state revision 0 (G-4; A2: no terminal insertion)');
END;

CREATE TRIGGER queue_status_change_advances_revision
BEFORE UPDATE OF status ON queue_entries
WHEN NEW.status IS NOT OLD.status AND NEW.state_revision IS NOT OLD.state_revision + 1
BEGIN
  SELECT RAISE(ABORT, 'a status change is a commit: it advances state_revision by one (RG-1b)');
END;

-- Ruling R2.5: the queue-status vocabulary is a DRAFT with explicit
-- transition semantics (gen2/store/README.md "Draft vocabularies" gives the
-- owner of each move and the amendment rule). Pre-contract lane: intake ->
-- scoping -> scope approval -> contract approval -> queued. Research lane:
-- queued <-> active <-> resting; held / capability_blocked /
-- stopped_for_resources / awaiting_judgment are waiting states, never
-- scientific outcomes; completion and retirement are decision-bound (above);
-- a completed topic may be requeued (approved amendment or mandatory
-- surveillance review); retired is terminal.
CREATE TRIGGER queue_status_transitions
BEFORE UPDATE OF status ON queue_entries
WHEN NEW.status IS NOT OLD.status AND NOT (
     (OLD.status = 'awaiting_brief_confirmation' AND NEW.status IN ('scoping', 'retired'))
  OR (OLD.status = 'scoping' AND NEW.status IN ('awaiting_scope_approval', 'held', 'capability_blocked', 'retired'))
  OR (OLD.status = 'awaiting_scope_approval' AND NEW.status IN ('awaiting_contract_approval', 'scoping', 'retired'))
  OR (OLD.status = 'awaiting_contract_approval' AND NEW.status IN ('queued', 'scoping', 'retired'))
  OR (OLD.status = 'queued' AND NEW.status IN ('active', 'held', 'capability_blocked', 'retired'))
  OR (OLD.status = 'active' AND NEW.status IN ('resting', 'queued', 'held', 'awaiting_judgment', 'completed_with_qualified_conclusions',
                                                'capability_blocked', 'stopped_for_resources', 'retired'))
  OR (OLD.status = 'resting' AND NEW.status IN ('active', 'queued', 'held', 'retired'))
  OR (OLD.status = 'held' AND NEW.status IN ('scoping', 'awaiting_scope_approval', 'awaiting_contract_approval', 'queued', 'retired'))
  OR (OLD.status = 'capability_blocked' AND NEW.status IN ('scoping', 'queued', 'held', 'retired'))
  OR (OLD.status = 'stopped_for_resources' AND NEW.status IN ('queued', 'awaiting_judgment', 'retired'))
  OR (OLD.status = 'awaiting_judgment' AND NEW.status IN ('active', 'queued', 'completed_with_qualified_conclusions', 'stopped_for_resources', 'retired'))
  OR (OLD.status = 'completed_with_qualified_conclusions' AND NEW.status IN ('queued', 'retired')))
BEGIN
  SELECT RAISE(ABORT, 'queue status transition not allowed (draft vocabulary, ruling R2.5)');
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

-- G-8: completion names the decision that authorizes it, and that decision
-- must be an approved completion approval of this topic's CURRENT dossier
-- revision with that dossier's exact content hash, and the dossier must have
-- been evaluated against the topic's active, approved contract revision
-- (protocol binding). An approval of an older revision is stale.
CREATE TRIGGER queue_completion_needs_current_dossier_approval
BEFORE UPDATE OF status ON queue_entries
WHEN NEW.status = 'completed_with_qualified_conclusions'
  AND OLD.status IS NOT NEW.status
  AND NOT EXISTS (
    SELECT 1 FROM operator_decisions d
    JOIN dossiers x ON x.topic_id = NEW.topic_id AND x.dossier_revision = d.subject_revision AND x.content_hash = d.subject_hash
    JOIN contract_revisions c ON c.topic_id = NEW.topic_id AND c.revision = x.contract_revision
    WHERE d.decision_id = NEW.status_decision_id
      AND d.topic_id = NEW.topic_id
      AND d.kind = 'completion_approval'
      AND d.disposition = 'approved'
      AND x.dossier_revision = (SELECT max(y.dossier_revision) FROM dossiers y WHERE y.topic_id = NEW.topic_id)
      AND x.contract_revision IS NEW.active_contract_revision
      AND c.status = 'approved')
BEGIN
  SELECT RAISE(ABORT, 'completion requires operator approval of the current dossier revision, its hash and the active approved contract (G-8)');
END;

-- P-6 / G-9: retirement names an approved retirement decision about this
-- topic, made against the state revision being left (a decision about an
-- earlier state is stale and cannot be reused).
CREATE TRIGGER queue_retirement_needs_operator_decision
BEFORE UPDATE OF status ON queue_entries
WHEN NEW.status = 'retired'
  AND OLD.status IS NOT NEW.status
  AND NOT EXISTS (
    SELECT 1 FROM operator_decisions d
    WHERE d.decision_id = NEW.status_decision_id
      AND d.topic_id = NEW.topic_id
      AND d.kind = 'retirement'
      AND d.disposition = 'approved'
      AND d.subject_revision = OLD.state_revision)
BEGIN
  SELECT RAISE(ABORT, 'retirement requires an approved operator retirement decision for this topic at its current state revision');
END;

-- G-13 (Astra re-review RA1): the authorizing-decision pointer moves only
-- together with the status transition it authorizes — whose gate above then
-- checks the decision. On a completed or retired topic it therefore stays the
-- decision actually used: it cannot be swapped for another decision (a
-- rejected or other-topic one, or even another valid approval) or cleared
-- without a status change, and advancing state_revision alone is not an
-- authorized transition.
CREATE TRIGGER queue_status_decision_moves_with_status
BEFORE UPDATE OF status_decision_id ON queue_entries
WHEN NEW.status_decision_id IS NOT OLD.status_decision_id AND NEW.status IS OLD.status
BEGIN
  SELECT RAISE(ABORT, 'the authorizing decision changes only with the status transition it authorizes (G-13, RA1)');
END;

-- trace: flow S1 (Intake Brief v1; the operator confirms it — an explicit,
-- versioned act; "unconfirmed briefs cannot advance — structural"; a draft
-- brief is a durable intake item with an operator owner, awaiting_confirmation
-- state, creation time and review deadline; expiry marks it overdue, never
-- advances it; cancellation/archival is an explicit act), §6.1 (an edited
-- brief re-versions); adjudication (a)G-A8; BOUNDARIES.md Operator (owners
-- and deadlines; status that answers why a waiting item waits); schema
-- intake-brief.schema.json; INVARIANTS G-4, C-12, G-13, §13 (the 0b row).
-- One row per brief version (task 0b: minimal versioned rows). Content
-- (document, hash, lineage, owner, deadline) is immutable; a change is a new
-- version. A version is written awaiting confirmation and moves:
--   awaiting_confirmation -> confirmed   naming an approved brief_confirmation
--                                        decision about exactly this topic,
--                                        brief id, version and hash (G-13);
--                                        the decision pointer is recorded only
--                                        by this transition and never changes
--   awaiting_confirmation -> cancelled   explicit: closed_by/at/reason
--   awaiting_confirmation | confirmed -> superseded   only once a later
--                                        version of the same brief exists
--   confirmed -> archived                explicit: closed_by/at/reason
-- cancelled, superseded and archived are terminal (no further change).
-- One confirmed brief version per topic. overdue_since is set once, only on a
-- version awaiting confirmation and never together with a status change:
-- expiry marks, it does not advance. Whether the deadline has passed is the
-- router's comparison (timestamps are router-validated text here; the text
-- order of RFC 3339 instants with fractions is not their time order).
-- Pre-contract admission (invocations_admission_context) and the queue's
-- first step (queue_scoping_needs_confirmed_brief) read these rows.
CREATE TABLE intake_briefs (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  brief_id TEXT NOT NULL CHECK (length(brief_id) BETWEEN 1 AND 64 AND brief_id GLOB '[A-Za-z]*' AND brief_id NOT GLOB '*[^A-Za-z0-9._-]*'),
  version INTEGER NOT NULL CHECK (version >= 1),
  parent_version INTEGER,
  content_hash TEXT NOT NULL UNIQUE CHECK (content_hash GLOB 'sha256:*' AND length(content_hash) = 71),
  document TEXT NOT NULL CHECK (json_valid(document)),
  owner_operator_id TEXT NOT NULL CHECK (length(owner_operator_id) > 0),
  status TEXT NOT NULL CHECK (status IN ('awaiting_confirmation', 'confirmed', 'superseded', 'cancelled', 'archived')),
  created_at TEXT NOT NULL,
  review_deadline TEXT NOT NULL,
  overdue_since TEXT,
  confirmed_by_decision_id TEXT REFERENCES operator_decisions (decision_id),
  closed_by TEXT,
  closed_at TEXT,
  close_reason TEXT,
  PRIMARY KEY (topic_id, brief_id, version),
  FOREIGN KEY (topic_id, brief_id, parent_version) REFERENCES intake_briefs (topic_id, brief_id, version),
  CONSTRAINT intake_brief_parent_is_earlier CHECK (parent_version IS NULL OR parent_version < version),
  CHECK (status NOT IN ('confirmed', 'archived') OR confirmed_by_decision_id IS NOT NULL),
  CHECK (status NOT IN ('awaiting_confirmation', 'cancelled') OR confirmed_by_decision_id IS NULL),
  CHECK ((closed_by IS NULL) = (closed_at IS NULL) AND (closed_at IS NULL) = (close_reason IS NULL)),
  CHECK ((status IN ('cancelled', 'archived')) = (closed_at IS NOT NULL)),
  CHECK (json_extract(document, '$.topic_id') IS topic_id
     AND json_extract(document, '$.brief_id') IS brief_id
     AND json_extract(document, '$.version') IS version
     AND json_extract(document, '$.parent_version') IS parent_version
     AND json_extract(document, '$.created_at') IS created_at
     AND json_extract(document, '$.content_hash') IS content_hash)
) STRICT;

CREATE UNIQUE INDEX intake_briefs_one_confirmed_per_topic
  ON intake_briefs (topic_id) WHERE status = 'confirmed';

CREATE TRIGGER intake_briefs_created_awaiting
BEFORE INSERT ON intake_briefs
WHEN NEW.status IS NOT 'awaiting_confirmation' OR NEW.confirmed_by_decision_id IS NOT NULL
  OR NEW.overdue_since IS NOT NULL OR NEW.closed_at IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'an intake brief version is written awaiting confirmation, not overdue and not closed (G-4; G-13: no decided insertion)');
END;

CREATE TRIGGER intake_briefs_status_transitions
BEFORE UPDATE OF status ON intake_briefs
WHEN NEW.status IS NOT OLD.status AND NOT (
     (OLD.status = 'awaiting_confirmation' AND NEW.status IN ('confirmed', 'cancelled', 'superseded'))
  OR (OLD.status = 'confirmed' AND NEW.status IN ('superseded', 'archived')))
BEGIN
  SELECT RAISE(ABORT, 'intake brief status moves awaiting_confirmation -> confirmed | cancelled | superseded, confirmed -> superseded | archived only (G-4)');
END;

CREATE TRIGGER intake_briefs_confirmation_bound
BEFORE UPDATE OF status ON intake_briefs
WHEN NEW.status = 'confirmed' AND OLD.status IS NOT 'confirmed' AND NOT EXISTS (
  SELECT 1 FROM operator_decisions d
  WHERE d.decision_id = NEW.confirmed_by_decision_id
    AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'
    AND d.topic_id = NEW.topic_id
    AND d.subject_ref = NEW.brief_id AND d.subject_revision = NEW.version AND d.subject_hash = NEW.content_hash)
BEGIN
  SELECT RAISE(ABORT, 'confirming a brief needs an approved brief_confirmation decision about this exact topic, brief, version and hash (G-4, G-13)');
END;

-- The confirmation pointer is evidence the version passed the gate above: it
-- is first recorded only by awaiting_confirmation -> confirmed, and never
-- changes after (the contract approval pointer's rule, RA3-R). A version
-- awaiting confirmation holds no pointer (CHECK), so "changes only on that
-- transition" is both rules at once.
CREATE TRIGGER intake_briefs_confirmation_pointer_set_by_confirmation
BEFORE UPDATE OF confirmed_by_decision_id ON intake_briefs
WHEN NEW.confirmed_by_decision_id IS NOT OLD.confirmed_by_decision_id
  AND (OLD.status IS NOT 'awaiting_confirmation' OR NEW.status IS NOT 'confirmed')
BEGIN
  SELECT RAISE(ABORT, 'the confirming decision is recorded only by the awaiting_confirmation -> confirmed transition, and never changes (G-13)');
END;

CREATE TRIGGER intake_briefs_superseded_by_a_later_version
BEFORE UPDATE OF status ON intake_briefs
WHEN NEW.status = 'superseded' AND OLD.status IS NOT 'superseded' AND NOT EXISTS (
  SELECT 1 FROM intake_briefs n WHERE n.topic_id = NEW.topic_id AND n.brief_id = NEW.brief_id AND n.version > NEW.version)
BEGIN
  SELECT RAISE(ABORT, 'a brief version is superseded only by a later version of the same brief (flow §6.1)');
END;

CREATE TRIGGER intake_briefs_overdue_marks_only
BEFORE UPDATE OF overdue_since ON intake_briefs
WHEN NEW.overdue_since IS NOT OLD.overdue_since
  AND (OLD.overdue_since IS NOT NULL OR OLD.status IS NOT 'awaiting_confirmation' OR NEW.status IS NOT OLD.status)
BEGIN
  SELECT RAISE(ABORT, 'overdue is marked once, on a brief awaiting confirmation, and never advances it (G-4: expiry marks, it does not advance)');
END;

CREATE TRIGGER intake_briefs_content_immutable
BEFORE UPDATE ON intake_briefs
WHEN NEW.topic_id IS NOT OLD.topic_id OR NEW.brief_id IS NOT OLD.brief_id OR NEW.version IS NOT OLD.version
  OR NEW.parent_version IS NOT OLD.parent_version OR NEW.content_hash IS NOT OLD.content_hash OR NEW.document IS NOT OLD.document
  OR NEW.owner_operator_id IS NOT OLD.owner_operator_id OR NEW.created_at IS NOT OLD.created_at OR NEW.review_deadline IS NOT OLD.review_deadline
BEGIN
  SELECT RAISE(ABORT, 'a brief version''s content, lineage, owner and deadline are immutable; a change is a new version (flow §6.1)');
END;

CREATE TRIGGER intake_briefs_terminal_immutable
BEFORE UPDATE ON intake_briefs
WHEN OLD.status IN ('cancelled', 'superseded', 'archived')
BEGIN
  SELECT RAISE(ABORT, 'a cancelled, superseded or archived brief version never changes');
END;

CREATE TRIGGER intake_briefs_no_delete BEFORE DELETE ON intake_briefs
BEGIN
  SELECT RAISE(ABORT, 'intake briefs are never deleted; cancellation and archival are explicit status changes (G-4)');
END;

-- G-4 (flow S1: unconfirmed briefs cannot advance — structurally): a topic
-- leaves intake for scoping only while it has a confirmed brief version.
CREATE TRIGGER queue_scoping_needs_confirmed_brief
BEFORE UPDATE OF status ON queue_entries
WHEN OLD.status = 'awaiting_brief_confirmation' AND NEW.status = 'scoping' AND NOT EXISTS (
  SELECT 1 FROM intake_briefs b WHERE b.topic_id = NEW.topic_id AND b.status = 'confirmed')
BEGIN
  SELECT RAISE(ABORT, 'a topic leaves intake only with a confirmed intake brief (G-4)');
END;

-- trace: flow S3 (Contract v2, hash-locked with its protocol revision);
-- design review §4 (immutable approved revision; older revisions preserved);
-- schema contract-v2.schema.json; INVARIANTS G-1.
-- Every revision's content is immutable once written (a change is a new
-- revision); only status and the approving decision move, draft ->
-- approved -> superseded. A parent is a strictly earlier revision of the
-- same topic (Astra third review RA2-R): revisions are ordered numbers, so
-- one CHECK (contract_parent_is_earlier, named so its refusal reads the same
-- whatever its expression) excludes self-parentage and every cycle
-- (including one written by a single multi-row INSERT, which the immediate
-- foreign key only checks at statement end), and the rating triggers'
-- parent-chain walk visits proper ancestors only.
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
  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision < revision),
  CHECK (status = 'draft' OR approved_by_decision_id IS NOT NULL),
  CHECK (json_extract(document, '$.topic_id') IS topic_id
     AND json_extract(document, '$.revision') IS revision
     AND json_extract(document, '$.parent_revision') IS parent_revision
     AND json_extract(document, '$.created_at') IS created_at
     AND json_extract(document, '$.content_hash') IS content_hash
     AND json_extract(document, '$.protocol_revision') IS protocol_revision
     AND json_extract(document, '$.facet_map.framing_version') IS framing_version)
) STRICT;

CREATE UNIQUE INDEX contract_one_approved_revision_per_topic
  ON contract_revisions (topic_id) WHERE status = 'approved';

CREATE TRIGGER contract_created_as_draft
BEFORE INSERT ON contract_revisions
WHEN NEW.status IS NOT 'draft' OR NEW.approved_by_decision_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'a contract revision is written as a draft; approval is a separate, decision-bound update (A2)');
END;

-- A2: the approving decision must be an approved contract/amendment/reframe
-- approval of THIS revision of THIS topic with THIS content hash.
CREATE TRIGGER contract_approval_bound_to_revision
BEFORE UPDATE OF approved_by_decision_id ON contract_revisions
WHEN NEW.approved_by_decision_id IS NOT NULL
  AND NEW.approved_by_decision_id IS NOT OLD.approved_by_decision_id
  AND NOT EXISTS (
    SELECT 1 FROM operator_decisions d
    WHERE d.decision_id = NEW.approved_by_decision_id
      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')
      AND d.disposition = 'approved'
      AND d.topic_id = NEW.topic_id
      AND d.subject_revision = NEW.revision
      AND d.subject_hash = NEW.content_hash)
BEGIN
  SELECT RAISE(ABORT, 'contract approval must be an approved decision about this exact topic, revision and content hash (A2)');
END;

-- C-12 / G-13 (Astra third review RA3-R): the approving decision is first
-- recorded only by the draft -> approved update itself (a row without one is
-- a draft, by the CHECK above, so an update giving it one and moving it to
-- approved is exactly that transition), whose gate
-- (contract_approval_needs_rated_covered_facets) runs in the same statement;
-- once recorded it never changes (contract_content_immutable). So a retained
-- pointer is evidence that the revision passed approval, and a draft never
-- holds one. draft -> superseded is refused first by
-- contract_status_forward_only (ruling 1); this trigger (no pointer can be
-- first recorded on a superseded row) and the CHECK (a superseded row holds
-- a pointer) stay behind it as second layers for that edge.
CREATE TRIGGER contract_approval_pointer_set_by_approval
BEFORE UPDATE OF approved_by_decision_id ON contract_revisions
WHEN OLD.approved_by_decision_id IS NULL AND NEW.approved_by_decision_id IS NOT NULL
  AND NEW.status IS NOT 'approved'
BEGIN
  SELECT RAISE(ABORT, 'the approving decision is recorded only by the draft -> approved transition it authorizes (C-12, RA3-R)');
END;

-- G-3 / A3: approval needs the revision's normalized obligation and facet
-- rows to be complete (one row per document entry, each bound to its entry
-- by the insert triggers below), every facet to carry an operator rating
-- (the operator approves framework, ratings, set and method together — flow
-- S3), and no critical facet without an obligation (uncovered_critical_facets).
CREATE TRIGGER contract_approval_needs_rated_covered_facets
BEFORE UPDATE OF status ON contract_revisions
WHEN NEW.status = 'approved' AND OLD.status = 'draft' AND (
     (SELECT count(*) FROM obligations o WHERE o.topic_id = NEW.topic_id AND o.contract_revision = NEW.revision)
       IS NOT json_array_length(NEW.document, '$.obligations')
  OR (SELECT count(*) FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.revision)
       IS NOT json_array_length(NEW.document, '$.facet_map.facets')
  OR EXISTS (SELECT 1 FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.revision AND f.operator_importance_band IS NULL)
  OR EXISTS (SELECT 1 FROM uncovered_critical_facets u WHERE u.topic_id = NEW.topic_id AND u.contract_revision = NEW.revision))
BEGIN
  SELECT RAISE(ABORT, 'approval needs complete obligation/facet rows, every facet operator-rated, and no uncovered critical facet (G-3)');
END;

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

-- Astra third review (0a-repair-3), ruling 1: a draft reaches only
-- approved. draft -> superseded is not an edge (since RA3-R it could never
-- complete anyway, see contract_approval_pointer_set_by_approval), so this
-- trigger is its first refusal; superseded is reached only from approved.
CREATE TRIGGER contract_status_forward_only
BEFORE UPDATE OF status ON contract_revisions
WHEN NOT ((OLD.status = 'draft' AND NEW.status IN ('draft', 'approved'))
       OR (OLD.status = 'approved' AND NEW.status IN ('approved', 'superseded'))
       OR (OLD.status = 'superseded' AND NEW.status = 'superseded'))
BEGIN
  SELECT RAISE(ABORT, 'contract status moves draft -> approved -> superseded only');
END;

CREATE TRIGGER contract_no_delete BEFORE DELETE ON contract_revisions
BEGIN
  SELECT RAISE(ABORT, 'contract revisions are never deleted (G-1)');
END;

-- trace: flow S3 (facet map; "Jev scores (Score: facet importance)";
-- operator approves framework, ratings, set and method design together;
-- "critical facet uncovered -> blocks approval (deterministic check on the
-- matrix)"), §6.4 (auto-promotion keyed to an existing facet's
-- operator-confirmed rating); methodology §2 (GRADE bands); adjudication
-- (a)G-R9, K-R4, K-A7; Astra 0a review A3; INVARIANTS G-2, G-3, G-5.
-- Normalized projection of one contract revision's facet_map.facets,
-- immutable with that revision. Facet importance is stored here in its own
-- right — never inferred from obligation ratings, which would make the
-- uncovered-critical-facet check circular (a facet with no obligation would
-- have no importance at all). Rows are bound to their document entry and
-- rating decision by facets_bound_to_document_and_decision.
CREATE TABLE facets (
  topic_id TEXT NOT NULL,
  contract_revision INTEGER NOT NULL,
  facet_id TEXT NOT NULL,
  proposed_importance_source TEXT CHECK (proposed_importance_source IN ('jev_score', 'primary_draft')),
  proposed_importance_score INTEGER CHECK (proposed_importance_score BETWEEN 1 AND 9),
  proposed_decision_receipt_id TEXT REFERENCES decision_receipts (decision_receipt_id),
  operator_importance_band TEXT CHECK (operator_importance_band IN ('critical', 'important', 'limited')),
  operator_importance_score INTEGER CHECK (operator_importance_score BETWEEN 1 AND 9),
  operator_rating_decision_id TEXT REFERENCES operator_decisions (decision_id),
  PRIMARY KEY (topic_id, contract_revision, facet_id),
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

-- G-2 / G-13 (Astra re-review RA2): an operator rating is exactly what the
-- operator rated. The rating decision cannot be about the revision that
-- carries its ID (that would be a self-hash cycle), so it is about an
-- earlier DRAFT — and not an arbitrary one: an ANCESTOR of this revision
-- (parent_revision chain; every parent is strictly earlier, RA2-R, so the
-- chain never reaches this revision) whose entry for this facet is the same subject,
-- defined exactly as here (the whole entry minus its importance object; the
-- router stores documents in their canonical JCS form, so equal entries are
-- equal text and a reordered one fails closed), and the decision's retained
-- rating payload gives this facet exactly this band and score. So an empty
-- or unrelated draft authorizes nothing, a rating cannot be changed or
-- invented under an old decision, and an unchanged rating carries forward.
-- This trigger and the document binding below both only refuse, so a row
-- either refuses is refused whichever fires first; nothing here depends on
-- SQLite's trigger order, and tests accept either reason where both apply.
CREATE TRIGGER facets_rating_is_what_the_operator_rated
BEFORE INSERT ON facets
WHEN NEW.operator_rating_decision_id IS NOT NULL AND NOT EXISTS (
  SELECT 1
  FROM operator_decisions d, json_each(d.payload, '$.facets') p,
       contract_revisions rated, json_each(rated.document, '$.facet_map.facets') re,
       contract_revisions here, json_each(here.document, '$.facet_map.facets') he
  WHERE d.decision_id = NEW.operator_rating_decision_id
    AND d.kind = 'rating_approval' AND d.disposition = 'approved'
    AND d.topic_id = NEW.topic_id
    AND d.subject_revision IN (
          WITH RECURSIVE lineage(rev) AS (
            SELECT parent_revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision
            UNION SELECT c.parent_revision FROM contract_revisions c JOIN lineage l ON c.topic_id = NEW.topic_id AND c.revision = l.rev)
          SELECT rev FROM lineage)
    AND p.key = NEW.facet_id
    AND json_extract(p.value, '$.band') IS NEW.operator_importance_band
    AND json_extract(p.value, '$.score') IS NEW.operator_importance_score
    AND rated.topic_id = d.topic_id AND rated.revision = d.subject_revision
    AND json_extract(re.value, '$.facet_id') IS NEW.facet_id
    AND here.topic_id = NEW.topic_id AND here.revision = NEW.contract_revision
    AND json_extract(he.value, '$.facet_id') IS NEW.facet_id
    AND json_remove(he.value, '$.importance') IS json_remove(re.value, '$.importance'))
BEGIN
  SELECT RAISE(ABORT, 'a facet rating is exactly what the operator rated: an approved rating decision of this topic about an ancestor draft defining this facet exactly as here, whose payload gives it this band and score (G-2, RA2)');
END;

-- A3: a facet row equals its entry in the revision's document (the
-- hash-locked content); a Jev proposal cites this topic's importance_score
-- receipt. (The operator rating is bound by the trigger above.)
CREATE TRIGGER facets_bound_to_document_and_decision
BEFORE INSERT ON facets
WHEN NOT EXISTS (
       SELECT 1 FROM contract_revisions c, json_each(c.document, '$.facet_map.facets') e
       WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision
         AND json_extract(e.value, '$.facet_id') IS NEW.facet_id
         AND json_extract(e.value, '$.importance.proposed.source') IS NEW.proposed_importance_source
         AND json_extract(e.value, '$.importance.proposed.score') IS NEW.proposed_importance_score
         AND json_extract(e.value, '$.importance.proposed.decision_receipt_id') IS NEW.proposed_decision_receipt_id
         AND json_extract(e.value, '$.importance.operator_rating.band') IS NEW.operator_importance_band
         AND json_extract(e.value, '$.importance.operator_rating.score') IS NEW.operator_importance_score
         AND json_extract(e.value, '$.importance.operator_rating.operator_decision_id') IS NEW.operator_rating_decision_id)
  OR (NEW.proposed_decision_receipt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM decision_receipts r
        WHERE r.decision_receipt_id = NEW.proposed_decision_receipt_id
          AND r.topic_id = NEW.topic_id AND r.decision_class = 'importance_score'))
BEGIN
  SELECT RAISE(ABORT, 'a facet row must equal its document entry, and its proposal must cite this topic''s importance_score receipt (A3)');
END;

CREATE TRIGGER facets_immutable BEFORE UPDATE ON facets
BEGIN
  SELECT RAISE(ABORT, 'facets are immutable with their contract revision');
END;

CREATE TRIGGER facets_no_delete BEFORE DELETE ON facets
BEGIN
  SELECT RAISE(ABORT, 'facets are never deleted');
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

-- A2: a proposed Jev score names a same-topic importance_score decision
-- receipt.
CREATE TRIGGER obligations_proposal_cites_importance_receipt
BEFORE INSERT ON obligations
WHEN NEW.proposed_decision_receipt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM decision_receipts r
        WHERE r.decision_receipt_id = NEW.proposed_decision_receipt_id
          AND r.topic_id = NEW.topic_id AND r.decision_class = 'importance_score')
BEGIN
  SELECT RAISE(ABORT, 'an obligation proposal must cite this topic''s importance_score receipt (A2)');
END;

-- G-2 / G-13 (RA2, RA2-R): the same binding as facets_rating_is_what_the_operator_rated
-- — an approved rating decision of this topic about a proper-ancestor draft whose
-- entry is this obligation defined exactly as here (template, slots, text,
-- facet tags, traces, exploratory flag, stopping profile), and whose retained
-- payload gives it exactly this band and score.
CREATE TRIGGER obligations_rating_is_what_the_operator_rated
BEFORE INSERT ON obligations
WHEN NEW.operator_rating_decision_id IS NOT NULL AND NOT EXISTS (
  SELECT 1
  FROM operator_decisions d, json_each(d.payload, '$.obligations') p,
       contract_revisions rated, json_each(rated.document, '$.obligations') re,
       contract_revisions here, json_each(here.document, '$.obligations') he
  WHERE d.decision_id = NEW.operator_rating_decision_id
    AND d.kind = 'rating_approval' AND d.disposition = 'approved'
    AND d.topic_id = NEW.topic_id
    AND d.subject_revision IN (
          WITH RECURSIVE lineage(rev) AS (
            SELECT parent_revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision
            UNION SELECT c.parent_revision FROM contract_revisions c JOIN lineage l ON c.topic_id = NEW.topic_id AND c.revision = l.rev)
          SELECT rev FROM lineage)
    AND p.key = NEW.obligation_id
    AND json_extract(p.value, '$.band') IS NEW.operator_importance_band
    AND json_extract(p.value, '$.score') IS NEW.operator_importance_score
    AND rated.topic_id = d.topic_id AND rated.revision = d.subject_revision
    AND json_extract(re.value, '$.obligation_id') IS NEW.obligation_id
    AND here.topic_id = NEW.topic_id AND here.revision = NEW.contract_revision
    AND json_extract(he.value, '$.obligation_id') IS NEW.obligation_id
    AND json_remove(he.value, '$.importance') IS json_remove(re.value, '$.importance'))
BEGIN
  SELECT RAISE(ABORT, 'an obligation rating is exactly what the operator rated: an approved rating decision of this topic about an ancestor draft defining this obligation exactly as here, whose payload gives it this band and score (G-2, RA2)');
END;

-- A3 / RA6: an obligation row equals its document entry in every normalized
-- field (template id/version/claim type, facet tags, stopping profile,
-- exploratory flag, importance), and every facet it tags is a facet of the
-- same revision — so coverage (uncovered_critical_facets) and the protocol
-- fields accounting reads are the hash-locked content, not free-standing rows.
CREATE TRIGGER obligations_bound_to_document_and_facets
BEFORE INSERT ON obligations
WHEN NOT EXISTS (
       SELECT 1 FROM contract_revisions c, json_each(c.document, '$.obligations') e
       WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision
         AND json_extract(e.value, '$.obligation_id') IS NEW.obligation_id
         AND json_extract(e.value, '$.template.template_id') IS NEW.template_id
         AND json_extract(e.value, '$.template.template_version') IS NEW.template_version
         AND json_extract(e.value, '$.template.claim_type') IS NEW.claim_type
         AND json_extract(e.value, '$.stopping_profile_id') IS NEW.stopping_profile_id
         AND json_extract(e.value, '$.exploratory') IS NEW.exploratory
         AND json_extract(e.value, '$.facet_ids') IS json(NEW.facet_ids)
         AND json_extract(e.value, '$.importance.proposed.source') IS NEW.proposed_importance_source
         AND json_extract(e.value, '$.importance.proposed.score') IS NEW.proposed_importance_score
         AND json_extract(e.value, '$.importance.proposed.decision_receipt_id') IS NEW.proposed_decision_receipt_id
         AND json_extract(e.value, '$.importance.operator_rating.band') IS NEW.operator_importance_band
         AND json_extract(e.value, '$.importance.operator_rating.score') IS NEW.operator_importance_score
         AND json_extract(e.value, '$.importance.operator_rating.operator_decision_id') IS NEW.operator_rating_decision_id)
  OR EXISTS (
       SELECT 1 FROM json_each(NEW.facet_ids) j
       WHERE NOT EXISTS (SELECT 1 FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.contract_revision AND f.facet_id = j.value))
BEGIN
  SELECT RAISE(ABORT, 'an obligation row must equal its document entry and tag only facets of its revision (A3)');
END;

CREATE TRIGGER obligations_immutable BEFORE UPDATE ON obligations
BEGIN
  SELECT RAISE(ABORT, 'obligations are immutable with their contract revision');
END;

CREATE TRIGGER obligations_no_delete BEFORE DELETE ON obligations
BEGIN
  SELECT RAISE(ABORT, 'obligations are never deleted');
END;

-- G-3: critical facets (operator band) that no obligation of the same
-- revision tags. Structural only: a tagged facet can still be semantically
-- under-covered (flow S3) — that stays with the operator and the facet audit.
CREATE VIEW uncovered_critical_facets AS
SELECT f.topic_id, f.contract_revision, f.facet_id
FROM facets f
WHERE f.operator_importance_band = 'critical'
  AND NOT EXISTS (
    SELECT 1 FROM obligations o, json_each(o.facet_ids) j
    WHERE o.topic_id = f.topic_id AND o.contract_revision = f.contract_revision AND j.value = f.facet_id);

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
-- invocation.schema.json; INVARIANTS L-1, L-2, L-3, L-8, RG-2, C-12.
-- There is no PID column.
-- Parentage (Astra ruling R2.2): parent_invocation_id is CONTROL/RESERVATION
-- parentage only — the invocation whose lease and reservation a delegate runs
-- under. Only delegates have one; a verifier never has a controlling parent
-- (the supervisor owns it). requested_by_invocation_id is the separate
-- causal link ("which invocation asked for this work") and carries no
-- authority: a verification requested by the producing pass is legitimate.
-- Leases (R2.1): every non-delegate owns exactly one lease, of the scope its
-- kind requires, live and of its topic when admitted; delegates inherit the
-- parent's lease and admission pins.
-- Admission (Astra A4; INVARIANTS C-12): contract/1 work is pinned to an
-- approved contract revision; pre-contract/1 work (S2 scoping, S3 drafting:
-- kinds discovery, delegate, research_pass) is pinned to a confirmed intake
-- brief (id, version, hash and the operator's brief_confirmation) and is
-- admissible only while the topic has never had an approved contract.
-- Ends (task 1c; BOUNDARIES.md Station supervisor; INVARIANTS L-5, L-7, L-9):
-- a failure records its structural class — what the supervisor's checks
-- found, never the agent's self-report — and a failure or a cancellation of
-- launched work names the supervisor's execution record (an artifact) as its
-- evidence. Cancellation is requested by the operator, the router, or the
-- supervisor (work it may not launch: its launch-admission check keeps
-- refusing). Every one of these facts is write-once.
CREATE TABLE invocations (
  invocation_id TEXT PRIMARY KEY CHECK (invocation_id GLOB 'inv_*'),
  kind TEXT NOT NULL CHECK (kind IN ('research_pass', 'discovery', 'delegate', 'verification', 'checkpoint')),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  parent_invocation_id TEXT REFERENCES invocations (invocation_id),
  requested_by_invocation_id TEXT REFERENCES invocations (invocation_id),
  lease_id TEXT REFERENCES leases (lease_id),
  capability_id TEXT NOT NULL UNIQUE CHECK (capability_id GLOB 'cap_*'),
  config_bundle_hash TEXT NOT NULL,
  admission_context TEXT NOT NULL CHECK (admission_context IN ('contract/1', 'pre-contract/1')),
  contract_revision INTEGER,
  brief_ref TEXT,
  brief_version INTEGER CHECK (brief_version >= 1),
  brief_hash TEXT CHECK (brief_hash IS NULL OR (brief_hash GLOB 'sha256:*' AND length(brief_hash) = 71)),
  brief_confirmation_decision_id TEXT REFERENCES operator_decisions (decision_id),
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
  cancel_requested_by TEXT CHECK (cancel_requested_by IN ('router', 'operator', 'supervisor')),
  descendants_confirmed_at TEXT,
  result_payload_digest TEXT,
  result_staged_at TEXT,
  outcome_unknown_since TEXT,
  unknown_episode INTEGER NOT NULL DEFAULT 0 CHECK (unknown_episode >= 0),
  state_changed_at TEXT NOT NULL,
  failure_class TEXT CHECK (failure_class IN ('spawn_failed', 'never_started', 'exit_nonzero', 'killed', 'timeout', 'empty_output',
                                              'output_refused', 'output_digest_mismatch', 'result_rejected', 'no_exit_record')),
  end_evidence_ref TEXT REFERENCES artifacts (content_hash),
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK ((kind = 'delegate') = (parent_invocation_id IS NOT NULL)),
  CHECK ((kind = 'delegate') = (lease_id IS NULL)),
  CHECK ((admission_context = 'contract/1') = (contract_revision IS NOT NULL)),
  CHECK (CASE admission_context
           WHEN 'pre-contract/1' THEN brief_ref IS NOT NULL AND brief_version IS NOT NULL AND brief_hash IS NOT NULL AND brief_confirmation_decision_id IS NOT NULL
           ELSE brief_ref IS NULL AND brief_version IS NULL AND brief_hash IS NULL AND brief_confirmation_decision_id IS NULL END),
  CHECK (admission_context = 'contract/1' OR kind IN ('discovery', 'delegate', 'research_pass')),
  CHECK (launch_intent_at IS NOT NULL OR state IN ('admitted', 'cancelled')),
  CHECK (launch_intent_at IS NULL OR job_handle IS NOT NULL),
  CHECK (state != 'running' OR (job_handle IS NOT NULL AND host_id IS NOT NULL AND boot_id IS NOT NULL AND start_fingerprint IS NOT NULL)),
  CHECK (state NOT IN ('result_ready', 'committed') OR (result_payload_digest IS NOT NULL AND result_staged_at IS NOT NULL)),
  CHECK (state != 'cancelled' OR descendants_confirmed_at IS NOT NULL),
  CHECK (state != 'outcome_unknown' OR (outcome_unknown_since IS NOT NULL AND unknown_episode >= 1)),
  CHECK ((cancel_requested_at IS NULL) = (cancel_requested_by IS NULL)),
  CHECK (failure_class IS NULL OR state = 'failed'),
  CHECK (end_evidence_ref IS NULL OR state IN ('failed', 'cancelled'))
) STRICT;

CREATE UNIQUE INDEX invocations_one_owner_per_lease ON invocations (lease_id) WHERE lease_id IS NOT NULL;

-- R2.1: a non-delegate's lease is live, of its topic, and of the scope its
-- kind requires. ("Live" here means unreleased: expiry is a runtime check.)
CREATE TRIGGER invocations_lease_matches_kind
BEFORE INSERT ON invocations
WHEN NEW.kind != 'delegate' AND NOT EXISTS (
  SELECT 1 FROM leases l
  WHERE l.lease_id = NEW.lease_id AND l.topic_id = NEW.topic_id AND l.released_at IS NULL
    AND l.scope = CASE NEW.kind WHEN 'research_pass' THEN 'research' WHEN 'discovery' THEN 'discovery'
                                WHEN 'verification' THEN 'verification' WHEN 'checkpoint' THEN 'checkpoint' END)
BEGIN
  SELECT RAISE(ABORT, 'an invocation owns a live lease of its topic and of its kind''s scope (R2.1)');
END;

-- R2.1/R2.2: a delegate runs under a running non-delegate parent of its topic
-- and inherits that parent's admission pins (no delegate chains, so no cycles).
CREATE TRIGGER invocations_delegate_inherits_parent
BEFORE INSERT ON invocations
WHEN NEW.kind = 'delegate' AND NOT EXISTS (
  SELECT 1 FROM invocations p
  WHERE p.invocation_id = NEW.parent_invocation_id AND p.topic_id = NEW.topic_id
    AND p.kind != 'delegate' AND p.state IN ('launching', 'running')
    AND p.admission_context IS NEW.admission_context AND p.contract_revision IS NEW.contract_revision
    AND p.brief_ref IS NEW.brief_ref AND p.brief_version IS NEW.brief_version AND p.brief_hash IS NEW.brief_hash
    AND p.brief_confirmation_decision_id IS NEW.brief_confirmation_decision_id)
BEGIN
  SELECT RAISE(ABORT, 'a delegate runs under a launching/running non-delegate parent of its topic with the same admission pins (R2.1)');
END;

-- (The requester must already exist, so an invocation cannot name itself.)
CREATE TRIGGER invocations_requested_by_same_topic
BEFORE INSERT ON invocations
WHEN NEW.requested_by_invocation_id IS NOT NULL
  AND (SELECT topic_id FROM invocations WHERE invocation_id = NEW.requested_by_invocation_id) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'the requesting invocation must be of the same topic');
END;

-- A4 / C-12: contract/1 admission pins an approved contract revision;
-- pre-contract/1 admission pins an operator-confirmed brief and is open only
-- while the topic has never had an approved contract. Since 0b the brief is
-- a stored row: the pins must name the topic's currently confirmed brief
-- version (exact id, version and hash), and the pinned decision must be the
-- one that confirmed it (whose gate checked kind, disposition, topic and
-- exact subject — intake_briefs_confirmation_bound). Checked when a
-- non-delegate is admitted; a delegate inherits its parent's already-checked
-- pins even if an amendment has since superseded them (in-flight work keeps
-- its pins; amendment invalidation is explicit router work, ruling R2.1).
CREATE TRIGGER invocations_admission_context
BEFORE INSERT ON invocations
WHEN NEW.kind != 'delegate' AND ((NEW.admission_context = 'contract/1' AND NOT EXISTS (
        SELECT 1 FROM contract_revisions c
        WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision AND c.status = 'approved'))
  OR (NEW.admission_context = 'pre-contract/1' AND (
        EXISTS (SELECT 1 FROM contract_revisions c WHERE c.topic_id = NEW.topic_id AND c.status != 'draft')
     OR NOT EXISTS (
        SELECT 1 FROM intake_briefs b
        WHERE b.topic_id = NEW.topic_id
          AND b.brief_id = NEW.brief_ref AND b.version = NEW.brief_version AND b.content_hash = NEW.brief_hash
          AND b.status = 'confirmed'
          AND b.confirmed_by_decision_id = NEW.brief_confirmation_decision_id))))
BEGIN
  SELECT RAISE(ABORT, 'admission: contract work needs an approved contract revision; pre-contract work needs a confirmed brief and no approved contract (A4, C-12)');
END;

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
  OR NEW.requested_by_invocation_id IS NOT OLD.requested_by_invocation_id
  OR NEW.lease_id IS NOT OLD.lease_id
  OR NEW.capability_id IS NOT OLD.capability_id
  OR NEW.config_bundle_hash IS NOT OLD.config_bundle_hash
  OR NEW.admission_context IS NOT OLD.admission_context
  OR NEW.contract_revision IS NOT OLD.contract_revision
  OR NEW.brief_ref IS NOT OLD.brief_ref OR NEW.brief_version IS NOT OLD.brief_version
  OR NEW.brief_hash IS NOT OLD.brief_hash OR NEW.brief_confirmation_decision_id IS NOT OLD.brief_confirmation_decision_id
  OR NEW.admitted_at IS NOT OLD.admitted_at
  OR (OLD.launch_intent_at IS NOT NULL AND NEW.launch_intent_at IS NOT OLD.launch_intent_at)
  OR (OLD.job_handle IS NOT NULL AND NEW.job_handle IS NOT OLD.job_handle)
  OR (OLD.host_id IS NOT NULL AND NEW.host_id IS NOT OLD.host_id)
  OR (OLD.container_id IS NOT NULL AND NEW.container_id IS NOT OLD.container_id)
  OR (OLD.boot_id IS NOT NULL AND NEW.boot_id IS NOT OLD.boot_id)
  OR (OLD.start_fingerprint IS NOT NULL AND NEW.start_fingerprint IS NOT OLD.start_fingerprint)
  OR (OLD.result_payload_digest IS NOT NULL AND NEW.result_payload_digest IS NOT OLD.result_payload_digest)
  OR (OLD.cancel_requested_at IS NOT NULL AND (NEW.cancel_requested_at IS NOT OLD.cancel_requested_at OR NEW.cancel_requested_by IS NOT OLD.cancel_requested_by))
  OR (OLD.descendants_confirmed_at IS NOT NULL AND NEW.descendants_confirmed_at IS NOT OLD.descendants_confirmed_at)
  OR (OLD.failure_class IS NOT NULL AND NEW.failure_class IS NOT OLD.failure_class)
  OR (OLD.end_evidence_ref IS NOT NULL AND NEW.end_evidence_ref IS NOT OLD.end_evidence_ref)
BEGIN
  SELECT RAISE(ABORT, 'invocation identity, admission pins, launch intent, process identity, staged result, cancellation request, descendant confirmation and failure record are write-once');
END;

-- L-4 (Astra re-review RA4): every outcome_unknown episode has its own,
-- never-reused identity. Entering outcome_unknown takes the next episode
-- number (exactly +1) with its start time; at any other moment — while the
-- episode is active, and after it ends — neither the episode number nor its
-- start time can change. So a later episode can never be made to look like
-- an earlier, already-reconciled one: rewinding the timestamp is refused,
-- and a re-entry at a reused timestamp is still a new episode.
CREATE TRIGGER invocations_unknown_episode_is_fresh
BEFORE UPDATE ON invocations
WHEN CASE WHEN OLD.state IS NOT 'outcome_unknown' AND NEW.state = 'outcome_unknown'
          THEN NEW.unknown_episode IS NOT OLD.unknown_episode + 1
          ELSE NEW.unknown_episode IS NOT OLD.unknown_episode OR NEW.outcome_unknown_since IS NOT OLD.outcome_unknown_since END
BEGIN
  SELECT RAISE(ABORT, 'an outcome_unknown episode takes a fresh identity on entry, and its identity and start time never change (L-4, RA4)');
END;

-- A5 / L-4: leaving outcome_unknown for any state L-1 allows needs the
-- durable reconciliation record of THIS unknown episode (by its identity,
-- RA4) whose resolution supports the target: found_running -> running;
-- found_result -> result_ready (same payload digest); found_committed ->
-- committed (a final receipt exists); confirmed_failed/terminated_group ->
-- failed; terminated_group -> cancelled. A timestamp or a result digest
-- alone is not reconciliation.
CREATE TRIGGER invocations_unknown_needs_reconciliation
BEFORE UPDATE OF state ON invocations
WHEN OLD.state = 'outcome_unknown'
  AND NEW.state IN ('running', 'result_ready', 'committed', 'failed', 'cancelled')
  AND NOT EXISTS (
    SELECT 1 FROM invocation_reconciliations r
    WHERE r.invocation_id = NEW.invocation_id AND r.unknown_episode = OLD.unknown_episode
      AND ((NEW.state = 'running' AND r.resolution = 'found_running')
        OR (NEW.state = 'result_ready' AND r.result_payload_digest = NEW.result_payload_digest)  -- only found_result carries a digest (CHECK)
        OR (NEW.state = 'committed' AND r.resolution = 'found_committed'
            AND EXISTS (SELECT 1 FROM operation_receipts o WHERE o.invocation_id = NEW.invocation_id AND o.operation_kind = 'final_outcome'))
        OR (NEW.state = 'failed' AND r.resolution IN ('confirmed_failed', 'terminated_group'))
        OR (NEW.state = 'cancelled' AND r.resolution = 'terminated_group')))
BEGIN
  SELECT RAISE(ABORT, 'outcome_unknown is left only through a reconciliation record of this episode that supports the target state (L-4, A5)');
END;

CREATE TRIGGER invocations_no_delete BEFORE DELETE ON invocations
BEGIN
  SELECT RAISE(ABORT, 'invocations are never deleted');
END;

-- trace: design review §6 ("outcome_unknown ... must be reconciled"), §5
-- (a crash between spawn and identity record is resolved by idempotent job
-- lookup or by terminating/reconciling the owned execution group, never by
-- PID adoption); BOUNDARIES.md Station supervisor (never treat
-- outcome_unknown as vanished/failed/retryable/done without reconciliation);
-- schema invocation.schema.json#/properties/reconciliation; Astra 0a review
-- A5 and ruling R2.4; INVARIANTS L-4.
-- One immutable row per resolved unknown episode (keyed by the episode's
-- identity, RA4 — a start time can recur, an episode number cannot),
-- recorded while the invocation is still in that episode.
-- The evidence is the retained lookup/termination record, never a bare
-- digest; terminal resolutions confirm descendant handling.
CREATE TABLE invocation_reconciliations (
  reconciliation_id TEXT PRIMARY KEY CHECK (reconciliation_id GLOB 'rec_*'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  unknown_episode INTEGER NOT NULL CHECK (unknown_episode >= 1),
  unknown_since TEXT NOT NULL,
  resolution TEXT NOT NULL CHECK (resolution IN ('found_running', 'found_result', 'found_committed', 'confirmed_failed', 'terminated_group')),
  method TEXT NOT NULL CHECK (method IN ('job_handle_lookup', 'execution_group_termination')),
  evidence_ref TEXT NOT NULL REFERENCES artifacts (content_hash),
  result_payload_digest TEXT CHECK (result_payload_digest IS NULL OR result_payload_digest GLOB 'sha256:*'),
  descendants_confirmed_at TEXT,
  resolved_at TEXT NOT NULL,
  UNIQUE (invocation_id, unknown_episode),
  CHECK ((resolution = 'found_result') = (result_payload_digest IS NOT NULL)),
  CHECK (resolution NOT IN ('confirmed_failed', 'terminated_group') OR descendants_confirmed_at IS NOT NULL),
  CHECK ((resolution = 'terminated_group') = (method = 'execution_group_termination'))
) STRICT;

CREATE TRIGGER invocation_reconciliations_for_current_episode
BEFORE INSERT ON invocation_reconciliations
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i
  WHERE i.invocation_id = NEW.invocation_id AND i.state = 'outcome_unknown'
    AND i.unknown_episode = NEW.unknown_episode AND i.outcome_unknown_since = NEW.unknown_since)
BEGIN
  SELECT RAISE(ABORT, 'a reconciliation records the current outcome_unknown episode of its invocation');
END;
CREATE TRIGGER invocation_reconciliations_immutable_u BEFORE UPDATE ON invocation_reconciliations
BEGIN
  SELECT RAISE(ABORT, 'reconciliation records are immutable');
END;
CREATE TRIGGER invocation_reconciliations_no_delete BEFORE DELETE ON invocation_reconciliations
BEGIN
  SELECT RAISE(ABORT, 'reconciliation records are never deleted (C-11)');
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

-- trace: design review §5 ("Artifacts and the sole-writer promise":
-- topic-scoped uploads, no cross-topic access); INVARIANTS C-9, RG-5; Astra
-- 1c review A6 and its Q6 ruling (content identity alone cannot authorize
-- another topic's use). Supporting table (see README "Supporting tables").
-- An artifacts row is the physical, content-addressed record, deduplicated
-- across topics; the topics that may reference it are recorded here, one row
-- per (artifact, topic). The router adds a topic's row only for bytes staged
-- in that topic's spool and recorded by that topic's own commit or evidence,
-- and resolves a reference to already-recorded bytes only through its
-- topic's row. Written once, never deleted.
CREATE TABLE artifact_topics (
  content_hash TEXT NOT NULL REFERENCES artifacts (content_hash),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  recorded_by_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (content_hash, topic_id)
) STRICT;

CREATE TRIGGER artifact_topics_by_the_topics_own_work
BEFORE INSERT ON artifact_topics
WHEN NOT EXISTS (SELECT 1 FROM invocations i WHERE i.invocation_id = NEW.recorded_by_invocation_id AND i.topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'an artifact is authorized for a topic only by that topic''s own invocation (C-9)');
END;
CREATE TRIGGER artifact_topics_immutable_u BEFORE UPDATE ON artifact_topics
BEGIN
  SELECT RAISE(ABORT, 'artifact topic authorizations are immutable');
END;
CREATE TRIGGER artifact_topics_immutable_d BEFORE DELETE ON artifact_topics
BEGIN
  SELECT RAISE(ABORT, 'artifact topic authorizations are never deleted');
END;

-- trace: design review §5 (normalized rows: operator decisions), §8 (approval
-- bound to an exact dossier revision); flow S1 (brief confirmation), S3
-- (framework/ratings/set/method approval), S7, §2 (blind samples: initial
-- disposition captured separately from advised feedback); BOUNDARIES.md
-- Operator; INVARIANTS G-2, G-4, G-8, D-9.
-- Every decision names a typed subject; each kind admits exactly one subject
-- kind (Astra 0a review A2: a decision ID is not authorization regardless
-- of its subject). subject_ref / subject_revision / subject_hash by kind:
--   intake_brief       brief id / brief version / brief content hash
--   scoping_report     report id / report version / report content hash
--   contract_revision  topic id / contract revision / contract content_hash
--   dossier            topic id / dossier revision / dossier content_hash
--   topic              topic id / queue state_revision decided against / -
--   hold               hold id / - / -
--   publication_source source ref / source revision / source content hash
--   decision_receipt   decision receipt id / - / -
-- The kind -> subject-kind mapping is a CHECK, so consuming gates test the
-- decision kind (which fixes the subject kind). Subjects stored here are
-- checked to exist with that exact hash when the decision is recorded
-- (intake briefs since 0b: topic, brief id, version and hash); scoping-report
-- and publication-source subjects are not store rows yet, so only their
-- shape is checked. Consuming gates then re-check kind, disposition,
-- topic and exact subject.
-- A rating decision retains what the operator rated (RA2): payload =
-- {"facets": {facet_id: {"band", "score"}}, "obligations": {obligation_id:
-- {"band", "score"}}}, every key an entry of the rated draft (its subject
-- revision). Immutable with the decision; no other kind carries a payload.
CREATE TABLE operator_decisions (
  decision_id TEXT PRIMARY KEY CHECK (decision_id GLOB 'opd_*'),
  topic_id TEXT REFERENCES queue_entries (topic_id),
  kind TEXT NOT NULL CHECK (kind IN (
    'brief_confirmation', 'scope_approval', 'rating_approval', 'contract_approval',
    'amendment_approval', 'reframe_approval', 'completion_approval', 'retirement',
    'hold_clearance', 'publication_approval', 'blind_initial_disposition', 'advised_feedback')),
  disposition TEXT NOT NULL CHECK (disposition IN ('approved', 'rejected', 'deferred', 'recorded')),
  subject_kind TEXT NOT NULL CHECK (subject_kind IN (
    'intake_brief', 'scoping_report', 'contract_revision', 'dossier', 'topic', 'hold',
    'publication_source', 'decision_receipt')),
  subject_ref TEXT NOT NULL CHECK (length(subject_ref) > 0),
  subject_revision INTEGER CHECK (subject_revision >= 0),
  subject_hash TEXT CHECK (subject_hash IS NULL OR (subject_hash GLOB 'sha256:*' AND length(subject_hash) = 71)),
  operator_id TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  notes TEXT,
  payload TEXT CHECK (payload IS NULL OR json_valid(payload)),
  CHECK ((kind = 'rating_approval') = (payload IS NOT NULL)),
  CHECK (kind != 'rating_approval' OR (json_type(payload, '$.facets') IS 'object' AND json_type(payload, '$.obligations') IS 'object')),
  CHECK ((kind = 'brief_confirmation' AND subject_kind = 'intake_brief')
      OR (kind = 'scope_approval' AND subject_kind = 'scoping_report')
      OR (kind IN ('rating_approval', 'contract_approval', 'amendment_approval', 'reframe_approval') AND subject_kind = 'contract_revision')
      OR (kind = 'completion_approval' AND subject_kind = 'dossier')
      OR (kind = 'retirement' AND subject_kind = 'topic')
      OR (kind = 'hold_clearance' AND subject_kind = 'hold')
      OR (kind = 'publication_approval' AND subject_kind = 'publication_source')
      OR (kind IN ('blind_initial_disposition', 'advised_feedback') AND subject_kind = 'decision_receipt')),
  CHECK (subject_kind NOT IN ('intake_brief', 'scoping_report', 'contract_revision', 'dossier', 'publication_source')
      OR (subject_revision IS NOT NULL AND subject_hash IS NOT NULL)),
  CHECK (subject_kind NOT IN ('contract_revision', 'dossier', 'topic') OR subject_ref IS topic_id),
  CHECK (subject_kind != 'topic' OR subject_revision IS NOT NULL),
  CHECK (subject_kind = 'hold' OR topic_id IS NOT NULL),
  CHECK ((kind IN ('blind_initial_disposition', 'advised_feedback')) = (disposition = 'recorded'))
) STRICT;

CREATE TRIGGER operator_decisions_subject_exists
BEFORE INSERT ON operator_decisions
WHEN (NEW.subject_kind = 'contract_revision' AND NOT EXISTS (
        SELECT 1 FROM contract_revisions c
        WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.subject_revision AND c.content_hash = NEW.subject_hash))
  OR (NEW.subject_kind = 'dossier' AND NOT EXISTS (
        SELECT 1 FROM dossiers x
        WHERE x.topic_id = NEW.topic_id AND x.dossier_revision = NEW.subject_revision AND x.content_hash = NEW.subject_hash))
  OR (NEW.subject_kind = 'hold' AND NOT EXISTS (
        SELECT 1 FROM holds k WHERE k.hold_id = NEW.subject_ref AND k.topic_id IS NEW.topic_id))
  OR (NEW.subject_kind = 'decision_receipt' AND NOT EXISTS (
        SELECT 1 FROM decision_receipts r WHERE r.decision_receipt_id = NEW.subject_ref AND r.topic_id = NEW.topic_id))
  OR (NEW.subject_kind = 'intake_brief' AND NOT EXISTS (
        SELECT 1 FROM intake_briefs b
        WHERE b.topic_id = NEW.topic_id AND b.brief_id = NEW.subject_ref AND b.version = NEW.subject_revision AND b.content_hash = NEW.subject_hash))
BEGIN
  SELECT RAISE(ABORT, 'an operator decision must name an existing subject of its topic with that exact revision and hash (A2)');
END;

-- RA2: a rating payload names only subjects of the draft it is about, with a
-- band from the vocabulary (the score/band fit is the rated rows' CHECK).
CREATE TRIGGER operator_decisions_rating_payload_of_its_draft
BEFORE INSERT ON operator_decisions
WHEN NEW.kind = 'rating_approval' AND (
     EXISTS (SELECT 1 FROM json_each(NEW.payload, '$.facets') p
             WHERE coalesce(json_extract(p.value, '$.band'), '') NOT IN ('critical', 'important', 'limited')
                OR NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.facet_map.facets') e
                               WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.subject_revision
                                 AND json_extract(e.value, '$.facet_id') IS p.key))
  OR EXISTS (SELECT 1 FROM json_each(NEW.payload, '$.obligations') p
             WHERE coalesce(json_extract(p.value, '$.band'), '') NOT IN ('critical', 'important', 'limited')
                OR NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.obligations') e
                               WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.subject_revision
                                 AND json_extract(e.value, '$.obligation_id') IS p.key)))
BEGIN
  SELECT RAISE(ABORT, 'a rating payload rates only entries of the draft the decision is about, each with a band (RA2)');
END;

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

-- C-12 (RA3, RA3-R): a dossier is evaluated against a revision that passed
-- approval — current or since superseded, so history keeps its pins; never
-- a draft. The approving-decision pointer is that evidence: it is recorded
-- only by the draft -> approved transition and its gate
-- (contract_approval_pointer_set_by_approval), never alone. Completion
-- additionally requires that revision to be the topic's active, currently
-- approved one.
CREATE TRIGGER dossiers_under_approved_protocol
BEFORE INSERT ON dossiers
WHEN NOT EXISTS (
  SELECT 1 FROM contract_revisions c
  WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision AND c.approved_by_decision_id IS NOT NULL)
BEGIN
  SELECT RAISE(ABORT, 'a dossier is evaluated against an approved protocol revision, never a draft (C-12, RA3)');
END;

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
-- delegate, its parent's), live, same topic and same generation; and the
-- receipt carries the invocation's own admission pins (contract revision or
-- confirmed brief) and config bundle — a stale contract/config is refused.
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
  admission_context TEXT NOT NULL CHECK (admission_context IN ('contract/1', 'pre-contract/1')),
  contract_revision INTEGER,
  brief_hash TEXT,
  config_bundle_hash TEXT NOT NULL,
  state_revision_before INTEGER NOT NULL CHECK (state_revision_before >= 0),
  state_revision_after INTEGER NOT NULL,
  validator_version TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  committed_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK (state_revision_after = state_revision_before + 1),
  -- RA6: every identity/version field the receipt JSON (commit-outcome
  -- schema #/$defs/receipt) duplicates equals its column, so the stored
  -- receipt cannot describe another topic, invocation, revision or validator
  -- than the row that fences it. (A released lease, when the receipt records
  -- one, is the fencing lease.) Admission references that need a join are
  -- bound by operation_receipts_admission_references.
  CHECK (json_extract(receipt, '$.operation_id') IS operation_id
     AND json_extract(receipt, '$.receipt_id') IS receipt_id
     AND json_extract(receipt, '$.operation_kind') IS operation_kind
     AND json_extract(receipt, '$.invocation_id') IS invocation_id
     AND json_extract(receipt, '$.topic_id') IS topic_id
     AND json_extract(receipt, '$.request_fingerprint') IS request_fingerprint
     AND json_extract(receipt, '$.payload_digest') IS payload_digest
     AND json_extract(receipt, '$.state_revision_before') IS state_revision_before
     AND json_extract(receipt, '$.state_revision_after') IS state_revision_after
     AND json_extract(receipt, '$.validation.validator_version') IS validator_version
     AND json_extract(receipt, '$.validation.policy_version') IS policy_version
     AND json_extract(receipt, '$.committed_at') IS committed_at
     AND json_extract(receipt, '$.admission.context') IS admission_context
     AND json_extract(receipt, '$.admission.contract.revision') IS contract_revision
     AND json_extract(receipt, '$.admission.brief.content_hash') IS brief_hash),
  CHECK (json_type(receipt, '$.effects.lease_release') IS NOT 'object'
      OR (json_extract(receipt, '$.effects.lease_release.lease_id') IS lease_id
          AND json_extract(receipt, '$.effects.lease_release.generation') IS lease_generation)),
  -- C-13 / Astra 0a ruling R1 (frozen in 0b): every commit receipt records
  -- the canonicalization and request-fingerprint contracts its hashes were
  -- computed under, and only the frozen versions are admitted (a new
  -- contract adds a version here, never edits one in place).
  CONSTRAINT operation_receipts_hash_contract_frozen CHECK (
        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')
    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))
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

CREATE TRIGGER operation_receipts_admission_pinned
BEFORE INSERT ON operation_receipts
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i
  WHERE i.invocation_id = NEW.invocation_id
    AND i.admission_context IS NEW.admission_context
    AND i.contract_revision IS NEW.contract_revision
    AND i.brief_hash IS NEW.brief_hash
    AND i.config_bundle_hash IS NEW.config_bundle_hash)
BEGIN
  SELECT RAISE(ABORT, 'commit rejected: admission pins or config bundle differ from the invocation''s (stale contract/config, RG-1b(c))');
END;

-- RA6 / C-12: the receipt JSON's admission references are the pinned ones —
-- the contract content hash of the pinned revision, and the brief id,
-- version and confirming decision of the invocation's pre-contract pins.
CREATE TRIGGER operation_receipts_admission_references
BEFORE INSERT ON operation_receipts
WHEN json_extract(NEW.receipt, '$.admission.contract.content_hash')
       IS NOT (SELECT content_hash FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision)
  OR NOT EXISTS (
       SELECT 1 FROM invocations i
       WHERE i.invocation_id = NEW.invocation_id
         AND json_extract(NEW.receipt, '$.admission.brief.brief_id') IS i.brief_ref
         AND json_extract(NEW.receipt, '$.admission.brief.version') IS i.brief_version
         AND json_extract(NEW.receipt, '$.admission.brief_confirmation_decision_id') IS i.brief_confirmation_decision_id)
BEGIN
  SELECT RAISE(ABORT, 'the receipt''s admission references must be its pins: the pinned contract revision''s hash, the pinned brief and its confirmation (RA6, C-12)');
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
  OR (SELECT admission_context FROM operation_receipts WHERE operation_id = NEW.operation_id) IS NOT 'contract/1'
  OR (SELECT invocation_id FROM operation_receipts WHERE operation_id = NEW.operation_id) IS NOT NEW.invocation_id
  OR (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id
  OR NEW.ordinal IS NOT (SELECT coalesce(max(ordinal), 0) + 1 FROM research_ordinals WHERE topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'ordinals go only to contract-admitted research_pass final outcomes, densely, one per invocation (C-7, C-12)');
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
-- Mandatory signals (G-12; ruling R2.5): retraction and decision_record_change
-- are raised by code policy or the operator, never by a model observation,
-- and route to mandatory review (the surveillance policy schema already
-- requires both, code-triaged).
CREATE TABLE review_triggers (
  trigger_identity TEXT PRIMARY KEY CHECK (trigger_identity GLOB 'sha256:*' AND length(trigger_identity) = 71),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  reason_code TEXT NOT NULL CHECK (reason_code IN (
    'cadence_floor', 'persistent_contradiction', 'yield_exhaustion_open_obligations',
    'cross_context_heterogeneity', 'definitional_disagreement', 'evidence_type_mismatch',
    'inapplicable_synthesis_plan', 'out_of_frame_concepts',
    'amendment', 'reframe', 'capability_change', 'facet_audit_due', 'calibration_due',
    'retraction', 'decision_record_change')),
  signal_source TEXT NOT NULL CHECK (signal_source IN ('deterministic', 'primary_observation', 'operator')),
  cause_ref TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  recorded_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  episode_id TEXT REFERENCES review_episodes (episode_id),
  handled_at TEXT,
  CHECK (reason_code NOT IN ('retraction', 'decision_record_change') OR signal_source IN ('deterministic', 'operator'))
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
-- per capability. The supersession contract (Astra 0a review A9) is one
-- transaction: UPDATE the current fact's superseded_by_fact_id to the new
-- id, then INSERT the new fact. The successor FK is DEFERRABLE INITIALLY
-- DEFERRED so that order satisfies both the one-current index and the FK at
-- COMMIT; a transaction that links a successor it never inserts fails at
-- COMMIT and must be rolled back (nothing changes). Facts are inserted
-- current; a successor is of the same capability, never itself, and never a
-- fact that is already superseded (so no cycles, and at most one current fact).
CREATE TABLE capability_facts (
  fact_id TEXT PRIMARY KEY,
  capability TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('healthy', 'degraded', 'failing', 'unknown')),
  detail TEXT NOT NULL,
  since TEXT NOT NULL,
  last_success_at TEXT,
  affected_lanes TEXT NOT NULL CHECK (json_valid(affected_lanes) AND json_type(affected_lanes) = 'array'),
  observed_by_invocation_id TEXT REFERENCES invocations (invocation_id),
  superseded_by_fact_id TEXT REFERENCES capability_facts (fact_id) DEFERRABLE INITIALLY DEFERRED,
  recorded_at TEXT NOT NULL,
  CHECK (superseded_by_fact_id IS NOT fact_id)
) STRICT;

CREATE UNIQUE INDEX capability_facts_one_current_per_capability
  ON capability_facts (capability) WHERE superseded_by_fact_id IS NULL;

CREATE TRIGGER capability_facts_insert_current_same_capability
BEFORE INSERT ON capability_facts
WHEN NEW.superseded_by_fact_id IS NOT NULL
  OR EXISTS (SELECT 1 FROM capability_facts o WHERE o.superseded_by_fact_id = NEW.fact_id AND o.capability IS NOT NEW.capability)
BEGIN
  SELECT RAISE(ABORT, 'a capability fact is inserted current, and only as the successor of a fact of the same capability (A9)');
END;

CREATE TRIGGER capability_facts_link_successor
BEFORE UPDATE OF superseded_by_fact_id ON capability_facts
WHEN NEW.superseded_by_fact_id IS NOT NULL AND EXISTS (
  SELECT 1 FROM capability_facts n
  WHERE n.fact_id = NEW.superseded_by_fact_id
    AND (n.capability IS NOT OLD.capability OR n.superseded_by_fact_id IS NOT NULL))
BEGIN
  SELECT RAISE(ABORT, 'a successor fact must be current and of the same capability (A9: no cross-capability or cyclic supersession)');
END;

CREATE TRIGGER capability_facts_supersede_only
BEFORE UPDATE ON capability_facts
WHEN OLD.superseded_by_fact_id IS NOT NULL
  OR NEW.fact_id IS NOT OLD.fact_id OR NEW.capability IS NOT OLD.capability
  OR NEW.state IS NOT OLD.state OR NEW.detail IS NOT OLD.detail OR NEW.since IS NOT OLD.since
  OR NEW.last_success_at IS NOT OLD.last_success_at OR NEW.affected_lanes IS NOT OLD.affected_lanes
  OR NEW.observed_by_invocation_id IS NOT OLD.observed_by_invocation_id OR NEW.recorded_at IS NOT OLD.recorded_at
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
  cleared_by_reconciliation_id TEXT REFERENCES invocation_reconciliations (reconciliation_id),
  CHECK (hold_class != 'capability' OR capability_fact_id IS NOT NULL),
  CHECK (cleared_at IS NULL OR cleared_by_decision_id IS NOT NULL OR cleared_by_operation_id IS NOT NULL OR cleared_by_reconciliation_id IS NOT NULL),
  CHECK (required_authority != 'operator' OR cleared_at IS NULL OR cleared_by_decision_id IS NOT NULL)
) STRICT;

CREATE TRIGGER holds_created_open
BEFORE INSERT ON holds
WHEN NEW.cleared_at IS NOT NULL OR NEW.cleared_by_decision_id IS NOT NULL OR NEW.cleared_by_operation_id IS NOT NULL
  OR NEW.cleared_by_reconciliation_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'a hold is created open; clearing is a separate update (A2: no terminal insertion)');
END;

-- Task 1c (L-4; design review §6: "ambiguous outcomes create a visible
-- diagnostic/reconciliation state with an owner and deadline"): entering
-- outcome_unknown opens a router-authority hold whose subject is that
-- episode, 'invocation:<invocation id>#unknown:<episode>'. The episode's
-- reconciliation record clears it, and clears nothing else: a record of
-- another invocation, another episode or another topic, or a hold another
-- authority must clear.
CREATE TRIGGER holds_reconciliation_clears_its_episode
BEFORE UPDATE OF cleared_by_reconciliation_id ON holds
WHEN NEW.cleared_by_reconciliation_id IS NOT NULL
  AND NEW.cleared_by_reconciliation_id IS NOT OLD.cleared_by_reconciliation_id
  AND NOT (NEW.required_authority = 'router' AND EXISTS (
    SELECT 1 FROM invocation_reconciliations r JOIN invocations i ON i.invocation_id = r.invocation_id
    WHERE r.reconciliation_id = NEW.cleared_by_reconciliation_id
      AND i.topic_id IS NEW.topic_id
      AND NEW.subject_ref = 'invocation:' || r.invocation_id || '#unknown:' || r.unknown_episode))
BEGIN
  SELECT RAISE(ABORT, 'a reconciliation record clears only the router hold of its own outcome_unknown episode (L-4)');
END;

-- A2: a clearing decision is an approved hold_clearance about THIS hold (same
-- topic, subject = this hold id); a decision about anything else clears
-- nothing.
CREATE TRIGGER holds_clearance_bound_to_hold
BEFORE UPDATE OF cleared_by_decision_id ON holds
WHEN NEW.cleared_by_decision_id IS NOT NULL
  AND NEW.cleared_by_decision_id IS NOT OLD.cleared_by_decision_id
  AND NOT EXISTS (
    SELECT 1 FROM operator_decisions d
    WHERE d.decision_id = NEW.cleared_by_decision_id
      AND d.kind = 'hold_clearance' AND d.disposition = 'approved'
      AND d.topic_id IS NEW.topic_id
      AND d.subject_ref = NEW.hold_id)
BEGIN
  SELECT RAISE(ABORT, 'a hold clears only through an approved hold_clearance decision about this hold (A2)');
END;

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
-- completeness (Astra 0a review A11; INVARIANTS RG-4): a result set that was
-- observed is 'complete' or 'partial' (e.g. pagination failed midway: the
-- records seen are real and kept — retrieval events may be captured for them
-- — but result_count is then only a lower bound and the error class says why);
-- a degraded search observed no result set ('unobserved'). A partial
-- observation never establishes exhausted coverage, negative evidence or
-- saturation (accounting reads completeness), and searched_empty is only
-- ever complete.
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
  completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'partial', 'unobserved')),
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
  CHECK ((coverage_state IN ('searched_ok', 'searched_empty', 'metadata_only')) = (completeness != 'unobserved')),
  CHECK (coverage_state != 'searched_empty' OR completeness = 'complete'),
  CHECK (completeness != 'partial' OR error_class IS NOT NULL),
  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR completeness = 'partial' OR error_class IS NULL),
  CHECK (error_class IS NOT 'secrets_backend_failing' OR capability_fact_id IS NOT NULL)
) STRICT;

CREATE TRIGGER search_observations_invocation_topic
BEFORE INSERT ON search_observations
WHEN (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'an observation is recorded under an invocation of its own topic (A10)');
END;

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

-- A10: a provider-written assessment is exactly the committed action of a
-- screening receipt of this invocation, about this work, recorded by that
-- receipt's commit (a commit_operation_id exists only on a committed action,
-- and a receipt's topic is its invocation's — both CHECKed elsewhere); the
-- recording operation and the invocation are of this topic; a reversal
-- supersedes an assessment of the same topic and work.
CREATE TRIGGER screening_assessments_bound
BEFORE INSERT ON screening_assessments
WHEN (NEW.actor_kind = 'decision_provider' AND NOT EXISTS (
        SELECT 1 FROM decision_receipts r
        WHERE r.decision_receipt_id = NEW.decision_receipt_id
          AND r.decision_class = 'screening' AND r.invocation_id IS NEW.invocation_id
          AND r.commit_operation_id = NEW.recorded_by_operation_id
          AND r.subject_kind = 'work' AND r.subject_ref = NEW.work_id))
  OR (SELECT topic_id FROM operation_receipts WHERE operation_id = NEW.recorded_by_operation_id) IS NOT NEW.topic_id
  OR (NEW.invocation_id IS NOT NULL AND (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id)
  OR (NEW.supersedes_assessment_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM screening_assessments o
        WHERE o.assessment_id = NEW.supersedes_assessment_id AND o.topic_id = NEW.topic_id AND o.work_id = NEW.work_id))
BEGIN
  SELECT RAISE(ABORT, 'screening assessment bindings: receipt class/topic/invocation/action/commit/subject, operation and invocation topic, superseded assessment (A10)');
END;
-- C-12 (Astra re-review RA3): a screening assessment is a scientific
-- disposition, so it exists only under the approved protocol it names. It is
-- recorded by a commit of CONTRACT-admitted work pinned to exactly that
-- contract revision (admission required the revision to be approved; a
-- pre-contract commit — however well-formed — records no disposition), its
-- assessing invocation (when named) carries the same pin, and its framing and
-- eligibility-protocol versions are that revision's own. (Only contract/1
-- work carries a contract-revision pin: invocations CHECK, and a receipt
-- carries exactly its invocation's pins.) Scoping
-- observations (search_observations, retrieval_events, works) stay open to
-- pre-contract work.
CREATE TRIGGER screening_assessments_under_approved_protocol
BEFORE INSERT ON screening_assessments
WHEN NOT EXISTS (
       SELECT 1 FROM operation_receipts o
       WHERE o.operation_id = NEW.recorded_by_operation_id AND o.contract_revision = NEW.contract_revision)
  OR (NEW.invocation_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM invocations i
       WHERE i.invocation_id = NEW.invocation_id AND i.contract_revision = NEW.contract_revision))
  OR NOT EXISTS (
       SELECT 1 FROM contract_revisions c
       WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision
         AND c.framing_version = NEW.framing_version
         AND json_extract(c.document, '$.eligibility_protocol.protocol_version') IS NEW.eligibility_protocol_version)
BEGIN
  SELECT RAISE(ABORT, 'a screening assessment is recorded by contract-admitted work under the approved protocol revision it names, with that revision''s framing and eligibility-protocol versions (C-12, RA3)');
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
-- S8 item 5 (unapproved work is never silently promoted), §5 (hybrid
-- verification: inline for load-bearing claims); design review §9;
-- adjudication (b)7, (d)3; INVARIANTS E-3 (unit 4: accepted claims), V-2,
-- V-4, V-10, C-12.
-- Claims start provisional. A load-bearing claim becomes accepted support
-- only with a supporting verification receipt at or above its required tier;
-- every claim becomes accepted support only if contract-admitted work of its
-- topic produced that revision (V-10).
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

-- Ruling R2.5: draft claim-status transitions (owner: the router at commit;
-- accepted_support additionally needs its verification receipt and
-- contract-admitted production, below).
-- provisional is capture; quarantined returns to provisional only by
-- re-capture; rejected can only be superseded; superseded is terminal.
CREATE TRIGGER claims_status_transitions
BEFORE UPDATE OF status ON claims
WHEN NEW.status IS NOT OLD.status AND NOT (
     (OLD.status = 'provisional' AND NEW.status IN ('accepted_support', 'contested', 'rejected', 'quarantined', 'superseded'))
  OR (OLD.status = 'accepted_support' AND NEW.status IN ('contested', 'quarantined', 'superseded'))
  OR (OLD.status = 'contested' AND NEW.status IN ('accepted_support', 'rejected', 'quarantined', 'superseded'))
  OR (OLD.status = 'quarantined' AND NEW.status IN ('provisional', 'rejected', 'superseded'))
  OR (OLD.status = 'rejected' AND NEW.status = 'superseded'))
BEGIN
  SELECT RAISE(ABORT, 'claim status transition not allowed (draft vocabulary, ruling R2.5)');
END;

-- V-4 / V-8 (Astra re-review RA5): promotion is decided from the claim's
-- OWN stored designation, not from what a receipt says about itself. A
-- load-bearing claim becomes accepted support only through a receipt
-- requested for load-bearing use — a sampling receipt never qualifies,
-- however it came out — at the claim's own required tier, obtained at or
-- above it, with all four substantive checks performed. The checks are
-- re-read from the immutable receipt JSON here, at the consuming boundary,
-- so neither a sampling label nor an adjudication record can waive the
-- unperformed-check prohibition. (The tier and checks conjuncts are also
-- enforced when a load-bearing receipt is written — a second layer here.)
CREATE TRIGGER claims_accepted_support_needs_receipt
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (
  SELECT 1 FROM verification_receipts v
  WHERE v.claim_id = NEW.claim_id AND v.claim_revision = NEW.revision AND v.verdict = 'supports'
    AND v.use = 'load_bearing'
    AND v.required_access_tier = NEW.required_access_tier
    AND (CASE v.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
     >= (CASE NEW.required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
    AND coalesce(json_extract(v.receipt, '$.checks.numeric_units'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
    AND coalesce(json_extract(v.receipt, '$.checks.denominators'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
    AND coalesce(json_extract(v.receipt, '$.checks.negation'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
    AND coalesce(json_extract(v.receipt, '$.checks.qualifications'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing'))
BEGIN
  SELECT RAISE(ABORT, 'a load-bearing claim needs a supporting load-bearing-use verification receipt at its own required tier with every check performed (V-2, V-4, V-8)');
END;

-- V-10 (task 1a; Astra 0a-repair-2 ruling 5, settled design): accepted
-- support is a globally reusable evidence status, so every promotion to it —
-- from provisional or contested, load-bearing or not — needs the claim
-- revision to have been produced under an approved contract revision's
-- admission context: its producing invocation is contract-admitted work of
-- the claim's own topic. (A contract-revision pin exists only under
-- contract/1, and admission checked that it was approved — a delegate
-- inherits its parent's checked pins — so the pin is not re-read here.)
-- Pre-contract (scoping) output is adopted by a new claim revision whose
-- producer is the contract-admitted work that adopts it (ruling 4 on RA3):
-- that invocation, with its write-once pins and its commit receipt, is the
-- audited record of the adoption. The old revision keeps its lineage and
-- never becomes accepted support itself. Independent of
-- claims_accepted_support_needs_receipt: a receipt does not establish
-- protocol admissibility, admission does not establish support, and where
-- both apply both must hold. The protocol-consuming rows keep their own
-- checks (screening assessments, claim-source links, dossiers).
CREATE TRIGGER claims_accepted_support_needs_contract_admission
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support' AND NOT EXISTS (
  SELECT 1 FROM invocations p
  WHERE p.invocation_id = NEW.producer_invocation_id
    AND p.admission_context = 'contract/1'
    AND p.topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'accepted support needs contract-admitted production: the claim revision''s producer must be contract-admitted work of its topic; pre-contract output is adopted by a new revision (V-10, C-12)');
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

-- C-12 (RA3): a claim-source-obligation link ties evidence to the approved
-- protocol, so it is about a claim of its own topic whose producing work was
-- CONTRACT-admitted under exactly the contract revision whose obligation it
-- names (a claim captured by pre-contract scoping may exist, provisional,
-- but links to no obligation).
CREATE TRIGGER claim_source_links_under_approved_protocol
BEFORE INSERT ON claim_source_links
WHEN NOT EXISTS (
  SELECT 1 FROM claims c JOIN invocations p ON p.invocation_id = c.producer_invocation_id
  WHERE c.claim_id = NEW.claim_id AND c.revision = NEW.claim_revision
    AND c.topic_id = NEW.topic_id
    AND p.contract_revision = NEW.contract_revision)  -- a contract-revision pin exists only under contract/1
BEGIN
  SELECT RAISE(ABORT, 'a claim-source link is about a claim of its topic produced by contract-admitted work under the protocol revision whose obligation it names (C-12, RA3)');
END;

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
-- Support integrity (Astra 0a review A6): 'supports' needs a non-mismatched
-- exact quote and every numeric/denominator/negation/qualification check
-- successful (checked_ok or not_applicable) and no tier-0 alarm — or an
-- explicit adjudicated resolution. A truthful unsuccessful verdict
-- (cannot_assess_at_required_tier, does_not_support) may carry not_checked /
-- unavailable checks; load-bearing *support* verdicts may not. The check
-- statuses and adjudication are read directly from the immutable receipt
-- JSON, and every normalized column must equal its JSON field (A10), so the
-- row cannot contradict the receipt.
-- Extraction (A6/B6; adjudication (b)5): the prohibition is on the
-- producer's selected summary or unvalidated extraction, not on bytes the
-- producer legitimately acquired: verifier_extraction is the verifier's own;
-- validated_extraction (anyone's) cites its validation; canonical_bytes are
-- authenticated acquired bytes — a gateway-call reference and a staged
-- artifact with exactly the obtained hash — whoever acquired them.
-- The verifier must be a separate verification-kind invocation of the same
-- topic checking the claim's actual producer. A verification invocation never
-- has a controlling parent (invocations CHECK, ruling R2.2), so a producer
-- cannot launch/control it; being *requested by* the producer is allowed.
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
  quote_check_id TEXT REFERENCES quote_checks (check_id),
  verdict TEXT NOT NULL CHECK (verdict IN ('supports', 'partially_supports', 'does_not_support', 'cannot_assess_at_required_tier')),
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  verified_at TEXT NOT NULL,
  FOREIGN KEY (claim_id, claim_revision) REFERENCES claims (claim_id, revision),
  CHECK (producer_invocation_id != verifier_invocation_id),
  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),
  CHECK (extraction_method != 'validated_extraction' OR extraction_validation_ref IS NOT NULL),
  CHECK (extraction_method != 'canonical_bytes' OR json_extract(acquisition, '$.gateway_call_ref') IS NOT NULL),
  CHECK ((coalesce(json_extract(receipt, '$.checks.exact_quote.status'), 'missing') IN ('matched', 'mismatch')) = (quote_check_id IS NOT NULL)),
  CHECK (verdict != 'supports' OR coalesce(json_extract(receipt, '$.checks.exact_quote.status'), 'missing') IN ('matched', 'not_applicable')),
  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') IS 'object' OR (
         coalesce(json_extract(receipt, '$.checks.numeric_units'), 'missing') IN ('checked_ok', 'not_applicable')
     AND coalesce(json_extract(receipt, '$.checks.denominators'), 'missing') IN ('checked_ok', 'not_applicable')
     AND coalesce(json_extract(receipt, '$.checks.negation'), 'missing') IN ('checked_ok', 'not_applicable')
     AND coalesce(json_extract(receipt, '$.checks.qualifications'), 'missing') IN ('checked_ok', 'not_applicable')
     AND json_extract(receipt, '$.checks.tier0.signal') IS NOT 'alarm')),
  CHECK (use != 'load_bearing' OR verdict NOT IN ('supports', 'partially_supports') OR (
         coalesce(json_extract(receipt, '$.checks.numeric_units'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
     AND coalesce(json_extract(receipt, '$.checks.denominators'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
     AND coalesce(json_extract(receipt, '$.checks.negation'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
     AND coalesce(json_extract(receipt, '$.checks.qualifications'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing'))),
  CHECK (json_extract(receipt, '$.verification_receipt_id') IS verification_receipt_id
     AND json_extract(receipt, '$.topic_id') IS topic_id
     AND json_extract(receipt, '$.claim.claim_id') IS claim_id
     AND json_extract(receipt, '$.claim.claim_revision') IS claim_revision
     AND json_extract(receipt, '$.source.work_id') IS work_id
     AND json_extract(receipt, '$.source.source_version') IS source_version
     AND json_extract(receipt, '$.cited_spans') IS json(cited_spans)
     AND json_extract(receipt, '$.obtained_content_hash') IS obtained_content_hash
     AND json_extract(receipt, '$.access_tier') IS access_tier
     AND json_extract(receipt, '$.requested_for.use') IS use
     AND json_extract(receipt, '$.requested_for.required_access_tier') IS required_access_tier
     AND json_extract(receipt, '$.acquisition') IS json(acquisition)
     AND json_extract(receipt, '$.extraction.method') IS extraction_method
     AND json_extract(receipt, '$.extraction.produced_by_invocation_id') IS extraction_invocation_id
     AND json_extract(receipt, '$.extraction.validation_ref') IS extraction_validation_ref
     AND json_extract(receipt, '$.producer_invocation_id') IS producer_invocation_id
     AND json_extract(receipt, '$.verifier_invocation_id') IS verifier_invocation_id
     AND json_extract(receipt, '$.quote_check_id') IS quote_check_id
     AND json_extract(receipt, '$.verdict') IS verdict),
  CHECK (verdict != 'supports'
      OR (CASE access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
      >= (CASE required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END))
) STRICT;

CREATE TRIGGER verification_receipts_role_separation
BEFORE INSERT ON verification_receipts
WHEN (SELECT kind FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT 'verification'
  OR (SELECT topic_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT NEW.topic_id
  OR (SELECT producer_invocation_id FROM claims WHERE claim_id = NEW.claim_id AND revision = NEW.claim_revision) IS NOT NEW.producer_invocation_id
  OR (SELECT topic_id FROM claims WHERE claim_id = NEW.claim_id AND revision = NEW.claim_revision) IS NOT NEW.topic_id
BEGIN
  SELECT RAISE(ABORT, 'verification must come from a separate verification invocation of the same topic, independent of the claim producer (RG-5)');
END;

-- V-8 (RA5): a receipt requested for load-bearing use states its claim's own
-- designation — the claim revision is load-bearing and the required tier is
-- the claim's stored required tier — so a receipt cannot re-describe the
-- subject it certifies. A sampled receipt may be of any claim at any tier
-- (sampling audits are legitimate); it just never qualifies a load-bearing
-- claim for accepted support (claims_accepted_support_needs_receipt).
CREATE TRIGGER verification_receipts_use_matches_claim
BEFORE INSERT ON verification_receipts
WHEN NEW.use = 'load_bearing' AND NOT EXISTS (
  SELECT 1 FROM claims c
  WHERE c.claim_id = NEW.claim_id AND c.revision = NEW.claim_revision
    AND c.load_bearing = 1
    AND c.required_access_tier = NEW.required_access_tier)
BEGIN
  SELECT RAISE(ABORT, 'a load-bearing-use receipt must be about a load-bearing claim at that claim''s own required tier (V-8, RA5)');
END;

-- A6/A10: the receipt names the verifier's own capability; canonical bytes
-- are a staged artifact with exactly the obtained hash; the quote check it
-- binds is of this claim revision, against the receipt's source artifact,
-- with the receipt's match status — and a supporting receipt cannot rest on
-- a quarantined quote unless the quarantine is an NLI alarm (never a byte
-- mismatch) resolved by explicit adjudication.
CREATE TRIGGER verification_receipts_bindings
BEFORE INSERT ON verification_receipts
WHEN (SELECT capability_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT json_extract(NEW.receipt, '$.verifier_capability_id')
  OR (NEW.extraction_method = 'canonical_bytes' AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.content_hash = NEW.obtained_content_hash))
  OR (NEW.quote_check_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM quote_checks q
        WHERE q.check_id = NEW.quote_check_id
          AND q.claim_id = NEW.claim_id AND q.claim_revision = NEW.claim_revision
          AND q.source_artifact_hash IS json_extract(NEW.receipt, '$.checks.exact_quote.source_artifact_hash')
          AND q.exact_match IS json_extract(NEW.receipt, '$.checks.exact_quote.status')
          AND (NEW.verdict != 'supports' OR q.quote_quarantined = 0
               OR (q.exact_match = 'matched' AND q.nli_signal = 'alarm' AND json_type(NEW.receipt, '$.adjudication') IS 'object'))))
BEGIN
  SELECT RAISE(ABORT, 'verification receipt bindings: verifier capability, authenticated canonical bytes, and an unquarantined quote check of this claim (A6, A10)');
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
-- A7: the primitive and action policy that receipts must match are
-- normalized and bound to the document; the provider fixes the primitive
-- family (Jev: noul/choice/score; fallback: label); options are an object
-- keyed by option id (so ids are unique by construction), a Noul has exactly
-- two; screening names its eligibility protocol and method_selection its
-- contract (other classes' protocol requirements are recorded as draft in
-- gen2/store/README.md).
CREATE TABLE decision_specs (
  spec_hash TEXT PRIMARY KEY CHECK (spec_hash GLOB 'sha256:*' AND length(spec_hash) = 71),
  spec_id TEXT NOT NULL UNIQUE CHECK (spec_id GLOB 'dspec_*'),
  decision_class TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('jev', 'llm_fallback')),
  primitive TEXT NOT NULL CHECK (primitive IN ('noul', 'choice', 'score', 'label')),
  policy_id TEXT NOT NULL,
  policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
  protocol_topic_id TEXT,
  document TEXT NOT NULL CHECK (json_valid(document)),
  created_at TEXT NOT NULL,
  CHECK ((provider = 'jev' AND primitive IN ('noul', 'choice', 'score')) OR (provider = 'llm_fallback' AND primitive = 'label')),
  CHECK (json_type(document, '$.options') IS 'object'),
  CHECK (decision_class != 'screening' OR json_type(document, '$.protocol.eligibility_protocol_version') IS 'integer'),
  CHECK (decision_class != 'method_selection' OR json_type(document, '$.protocol') IS 'object'),
  CHECK (json_extract(document, '$.spec_id') IS spec_id
     AND json_extract(document, '$.provider') IS provider
     AND json_extract(document, '$.decision_class') IS decision_class
     AND json_extract(document, '$.primitive') IS primitive
     AND json_extract(document, '$.action_policy.policy_id') IS policy_id
     AND json_extract(document, '$.action_policy.version') IS policy_version
     AND json_extract(document, '$.protocol.topic_id') IS protocol_topic_id)
) STRICT;

CREATE TRIGGER decision_specs_option_count
BEFORE INSERT ON decision_specs
WHEN (SELECT count(*) FROM json_each(NEW.document, '$.options')) < 2
  OR (NEW.primitive = 'noul' AND (SELECT count(*) FROM json_each(NEW.document, '$.options')) != 2)
BEGIN
  SELECT RAISE(ABORT, 'a spec offers at least two options; a Noul exactly two (A7)');
END;

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
-- A7: the action fixes the outcome shape (shadow and escalate have no
-- commit/proposal effect; each effect field belongs to exactly its action);
-- raw response bytes are retained as an artifact whenever a response exists
-- (answered or abstained), and the digest is that artifact's hash; the
-- receipt names the subject decided on (A10: screening binds it); every
-- normalized column equals its receipt-JSON field.
CREATE TABLE decision_receipts (
  decision_receipt_id TEXT PRIMARY KEY CHECK (decision_receipt_id GLOB 'dec_*'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  spec_hash TEXT NOT NULL REFERENCES decision_specs (spec_hash),
  decision_class TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('jev', 'llm_fallback')),
  input_status TEXT NOT NULL CHECK (input_status IN ('complete', 'oversized', 'stale', 'truncated', 'disallowed')),
  response_status TEXT NOT NULL CHECK (response_status IN ('answered', 'abstained', 'rejected_input', 'error', 'timeout')),
  raw_response_digest TEXT REFERENCES artifacts (content_hash),
  answer TEXT CHECK (answer IS NULL OR json_valid(answer)),
  subject_kind TEXT NOT NULL CHECK (subject_kind IN ('work', 'claim', 'obligation', 'facet', 'contract_revision', 'topic', 'source', 'checkpoint')),
  subject_ref TEXT NOT NULL CHECK (length(subject_ref) > 0),
  policy_id TEXT NOT NULL,
  policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
  authority_level TEXT NOT NULL CHECK (authority_level IN ('shadow', 'advisory', 'qualified')),
  qualification_ref TEXT,
  action TEXT NOT NULL CHECK (action IN ('commit_reversible_action', 'attach_proposal', 'escalate', 'abstain_hold', 'shadow_log_only')),
  commit_operation_id TEXT REFERENCES operation_receipts (operation_id) DEFERRABLE INITIALLY DEFERRED,
  hold_id TEXT REFERENCES holds (hold_id) DEFERRABLE INITIALLY DEFERRED,
  proposal_ref TEXT,
  blind_sample INTEGER NOT NULL CHECK (blind_sample IN (0, 1)),
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  decided_at TEXT NOT NULL,
  CHECK (qualification_ref IS NOT NULL OR authority_level IN ('shadow', 'advisory')),
  CHECK (action != 'commit_reversible_action' OR (authority_level = 'qualified' AND commit_operation_id IS NOT NULL)),
  CHECK (authority_level != 'shadow' OR action = 'shadow_log_only'),
  CHECK (input_status = 'complete' OR response_status = 'rejected_input'),
  CHECK (response_status != 'answered' OR answer IS NOT NULL),
  CHECK (response_status NOT IN ('answered', 'abstained') OR raw_response_digest IS NOT NULL),
  CHECK (response_status = 'answered' OR answer IS NULL),
  CHECK (response_status = 'answered' OR action IN ('escalate', 'abstain_hold', 'shadow_log_only')),
  CHECK ((action = 'commit_reversible_action') = (commit_operation_id IS NOT NULL)),
  CHECK ((action = 'attach_proposal') = (proposal_ref IS NOT NULL)),
  CHECK (action != 'abstain_hold' OR hold_id IS NOT NULL),
  CHECK (action NOT IN ('shadow_log_only', 'commit_reversible_action', 'attach_proposal') OR hold_id IS NULL),
  CHECK (json_extract(receipt, '$.decision_receipt_id') IS decision_receipt_id
     AND json_extract(receipt, '$.invocation_id') IS invocation_id
     AND json_extract(receipt, '$.topic_id') IS topic_id
     AND json_extract(receipt, '$.spec.spec_hash') IS spec_hash
     AND json_extract(receipt, '$.decision_class') IS decision_class
     AND json_extract(receipt, '$.provider') IS provider
     AND json_extract(receipt, '$.subject.kind') IS subject_kind
     AND json_extract(receipt, '$.subject.ref') IS subject_ref
     AND json_extract(receipt, '$.input_manifest.input_status') IS input_status
     AND json_extract(receipt, '$.provider_response.status') IS response_status
     AND json_extract(receipt, '$.provider_response.raw_response_digest') IS raw_response_digest
     AND json_extract(receipt, '$.provider_response.raw_response_artifact.content_hash') IS raw_response_digest
     AND json_extract(receipt, '$.provider_response.answer') IS json(answer)
     AND json_extract(receipt, '$.policy.policy_id') IS policy_id
     AND json_extract(receipt, '$.policy.version') IS policy_version
     AND json_extract(receipt, '$.authorization.authority_level') IS authority_level
     AND json_extract(receipt, '$.authorization.qualification_ref') IS qualification_ref
     AND json_extract(receipt, '$.action') IS action
     AND json_extract(receipt, '$.outcome.commit_operation_id') IS commit_operation_id
     AND json_extract(receipt, '$.outcome.proposal_ref') IS proposal_ref
     AND json_extract(receipt, '$.outcome.hold_id') IS hold_id
     AND json_extract(receipt, '$.blind_sample.selected') IS blind_sample
     AND json_extract(receipt, '$.decided_at') IS decided_at),
  -- C-13 / Astra 0a ruling R1 (frozen in 0b): the receipt records the
  -- canonicalization contract of its logical hashes (spec_hash); it carries
  -- no request fingerprint, so it names no fingerprint contract.
  CONSTRAINT decision_receipts_hash_contract_frozen CHECK (
        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')
    AND json_type(receipt, '$.hash_contract.fingerprint') IS NULL),
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

-- A7: a receipt matches its spec in provider, class, answer primitive and
-- action policy; a selected option and every distribution key are options of
-- the spec; a spec bound to a topic's protocol is used only for that topic;
-- the invocation is of the receipt's topic. RA6: the spec id the receipt
-- JSON names is the id of the spec its hash selects.
CREATE TRIGGER decision_receipts_match_spec
BEFORE INSERT ON decision_receipts
WHEN (SELECT spec_id FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT json_extract(NEW.receipt, '$.spec.spec_id')
  OR (SELECT provider FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.provider
  OR (SELECT decision_class FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.decision_class
  OR (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id
  OR (NEW.answer IS NOT NULL AND (SELECT primitive FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT json_extract(NEW.answer, '$.primitive'))
  OR (SELECT policy_id FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.policy_id
  OR (SELECT policy_version FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.policy_version
  OR coalesce((SELECT protocol_topic_id FROM decision_specs WHERE spec_hash = NEW.spec_hash), NEW.topic_id) IS NOT NEW.topic_id
  OR (json_extract(NEW.answer, '$.selected_option_id') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM decision_specs sp, json_each(sp.document, '$.options') o
        WHERE sp.spec_hash = NEW.spec_hash AND o.key = json_extract(NEW.answer, '$.selected_option_id')))
  OR EXISTS (
        SELECT 1 FROM json_each(NEW.answer, '$.distribution') d
        WHERE NOT EXISTS (SELECT 1 FROM decision_specs sp, json_each(sp.document, '$.options') o WHERE sp.spec_hash = NEW.spec_hash AND o.key = d.key))
BEGIN
  SELECT RAISE(ABORT, 'decision receipt must match its spec: spec id, provider, class, primitive, action policy, options, protocol topic; invocation topic must match (A7, RA6)');
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
-- Export: the one outbound path (operator ruling 2026-09-26)
-- ===========================================================================
-- External export is one standard API that any database connects to
-- (docs/gen2/EXPORT-API.md). No database product is named here: connectors
-- are operator-named and closed by type, and nothing below is read back as
-- research — engine readers read the record above.

-- trace: flow S8 items 1, 2 and 5 as amended by operator ruling 2026-09-26
-- (the router commits the approved revision and an outbox event whose
-- manifest is the export manifest, atomically; corrections, checkpoint
-- publications and options re-exports are new events); design review §9;
-- schema export-manifest.schema.json; BOUNDARIES.md Router ("export outbox
-- commits with immutable export manifests"), Exporter; INVARIANTS P-1, P-2,
-- P-5.
-- One row per export manifest. Ordering pairs (generation, options_revision)
-- strictly increase per topic; one generation is one approved revision;
-- unapproved work is never exported.
CREATE TABLE outbox_events (
  outbox_event_id TEXT PRIMARY KEY CHECK (outbox_event_id GLOB 'obx_*'),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  manifest_id TEXT NOT NULL UNIQUE CHECK (manifest_id GLOB 'man_*'),
  manifest_hash TEXT NOT NULL UNIQUE CHECK (manifest_hash GLOB 'sha256:*'),
  artifact_kind TEXT NOT NULL CHECK (artifact_kind IN ('completion_publication', 'evidence_correction', 'checkpoint_publication')),
  generation INTEGER NOT NULL CHECK (generation >= 1),
  options_revision INTEGER NOT NULL CHECK (options_revision >= 1),
  supersedes_generation INTEGER,
  supersedes_options_revision INTEGER,
  source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
  source_content_hash TEXT NOT NULL CHECK (source_content_hash GLOB 'sha256:*' AND length(source_content_hash) = 71),
  approval_decision_id TEXT NOT NULL REFERENCES operator_decisions (decision_id),
  bundle_content_hash TEXT NOT NULL CHECK (bundle_content_hash GLOB 'sha256:*' AND length(bundle_content_hash) = 71),
  expected_connectors TEXT NOT NULL CHECK (json_valid(expected_connectors) AND json_type(expected_connectors) = 'object' AND json(expected_connectors) != '{}'),
  manifest TEXT NOT NULL CHECK (json_valid(manifest)),
  committed_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  UNIQUE (topic_id, generation, options_revision),
  CHECK ((supersedes_generation IS NULL) = (supersedes_options_revision IS NULL)),
  CHECK (supersedes_generation IS NULL
     OR (supersedes_generation >= 1 AND supersedes_options_revision >= 1
         AND (supersedes_generation < generation
              OR (supersedes_generation = generation AND supersedes_options_revision < options_revision)))),
  CHECK (json_extract(manifest, '$.manifest_id') IS manifest_id
     AND json_extract(manifest, '$.generation') IS generation
     AND json_extract(manifest, '$.options_revision') IS options_revision
     AND json_extract(manifest, '$.topic_id') IS topic_id
     AND json_extract(manifest, '$.artifact_kind') IS artifact_kind
     AND json_extract(manifest, '$.source.revision') IS source_revision
     AND json_extract(manifest, '$.source.content_hash') IS source_content_hash
     AND json_extract(manifest, '$.approval.operator_decision_id') IS approval_decision_id
     AND json_extract(manifest, '$.approval.approved_revision') IS source_revision
     AND json_extract(manifest, '$.bundle.content_hash') IS bundle_content_hash
     AND json_extract(manifest, '$.supersedes.generation') IS supersedes_generation
     AND json_extract(manifest, '$.supersedes.options_revision') IS supersedes_options_revision
     AND json_extract(manifest, '$.expected_connectors') IS json(expected_connectors))
) STRICT;

-- The ordering pair: a manifest's (generation, options_revision) exceeds
-- every earlier one of its topic, so an old retry cannot be committed as
-- newer material.
CREATE TRIGGER outbox_events_pair_increases
BEFORE INSERT ON outbox_events
WHEN EXISTS (
  SELECT 1 FROM outbox_events e
  WHERE e.topic_id = NEW.topic_id
    AND (e.generation > NEW.generation
         OR (e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))
BEGIN
  SELECT RAISE(ABORT, 'export ordering pairs (generation, options_revision) strictly increase per topic (P-2)');
END;
-- One generation is one approved revision: a re-export under a later options
-- revision keeps its generation's source, approval and artifact kind.
CREATE TRIGGER outbox_events_generation_is_one_approved_revision
BEFORE INSERT ON outbox_events
WHEN EXISTS (
  SELECT 1 FROM outbox_events e
  WHERE e.topic_id = NEW.topic_id AND e.generation = NEW.generation
    AND (e.source_revision IS NOT NEW.source_revision
         OR e.source_content_hash IS NOT NEW.source_content_hash
         OR e.approval_decision_id IS NOT NEW.approval_decision_id
         OR e.artifact_kind IS NOT NEW.artifact_kind))
BEGIN
  SELECT RAISE(ABORT, 'one generation is one approved revision: a re-export keeps its source, approval and kind (P-2, P-5)');
END;
-- A2: the approval is an approved publication_approval of this topic whose
-- subject is exactly the exported source revision and content hash.
CREATE TRIGGER outbox_events_only_approved
BEFORE INSERT ON outbox_events
WHEN NOT EXISTS (
  SELECT 1 FROM operator_decisions d
  WHERE d.decision_id = NEW.approval_decision_id
    AND d.kind = 'publication_approval' AND d.disposition = 'approved'
    AND d.topic_id = NEW.topic_id
    AND d.subject_revision = NEW.source_revision
    AND d.subject_hash = NEW.source_content_hash)
BEGIN
  SELECT RAISE(ABORT, 'unapproved work is never exported: approval must be of this exact source revision and hash (P-5, A2)');
END;
-- Connector types are a closed, reviewed vocabulary: every connector a
-- manifest names is an object whose type is declared (a store kind written
-- into config is not a type; P-2).
CREATE TRIGGER outbox_events_connectors_declared
BEFORE INSERT ON outbox_events
WHEN EXISTS (
  SELECT 1 FROM json_each(NEW.expected_connectors) j
  WHERE coalesce(CASE WHEN j.type = 'object' THEN json_extract(j.value, '$.connector_type') END, '')
        NOT IN ('sql', 'jsonl_file', 'webhook', 'extension'))
BEGIN
  SELECT RAISE(ABORT, 'an export names only connectors of a declared type (P-2)');
END;
CREATE TRIGGER outbox_events_immutable_u BEFORE UPDATE ON outbox_events
BEGIN
  SELECT RAISE(ABORT, 'outbox events and their manifests are immutable (P-1)');
END;
CREATE TRIGGER outbox_events_immutable_d BEFORE DELETE ON outbox_events
BEGIN
  SELECT RAISE(ABORT, 'outbox events are never deleted');
END;

-- trace: flow S8 item 2 as amended by operator ruling 2026-09-26 (per-
-- connector receipts; supersession/tombstones acknowledged per connector);
-- BOUNDARIES.md Exporter; schema export-delivery-receipt.schema.json;
-- adjudication (a)G-A1 (mutable delivery receipts stored separately);
-- INVARIANTS P-2, P-4, P-7, H-2, RG-U; EXPORT-API.md §9 item 3; Astra 1b
-- review A2.
-- Exporter-owned records, written through the router's ack_delivery. One
-- row per attempt; a retry or a reconciliation is a new attempt, never an
-- edit. The status rules are the receipt schema's. The receipt document is
-- stored whole (JCS), and every column is a projection bound to it, so no
-- part of what the connector reported — the written count in each of its
-- three states, the hold, the invocation — is lost, and a column cannot say
-- anything its document does not.
CREATE TABLE export_delivery_receipts (
  export_receipt_id TEXT PRIMARY KEY CHECK (export_receipt_id GLOB 'exr_*'),
  manifest_id TEXT NOT NULL REFERENCES outbox_events (manifest_id),
  connector_id TEXT NOT NULL CHECK (connector_id GLOB '[a-z]*' AND connector_id NOT GLOB '*[^a-z0-9-]*' AND connector_id NOT GLOB '*-' AND length(connector_id) <= 64),
  connector_type TEXT NOT NULL CHECK (connector_type IN ('sql', 'jsonl_file', 'webhook', 'extension')),
  attempt INTEGER NOT NULL CHECK (attempt >= 1),
  status TEXT NOT NULL CHECK (status IN ('delivered', 'failed', 'skipped_superseded', 'outcome_unknown')),
  tombstones_acknowledged INTEGER NOT NULL CHECK (tombstones_acknowledged IN (0, 1)),
  reconciliation_required INTEGER NOT NULL CHECK (reconciliation_required IN (0, 1)),
  error_class TEXT CHECK (error_class IN ('unreachable', 'auth_failed', 'refused', 'schema_mismatch', 'quota', 'timeout', 'conflict', 'partial_write')),
  unknown_cause TEXT CHECK (unknown_cause IN ('terminated_after_send', 'no_response_after_send', 'unreadable_response', 'unauthoritative_response')),
  capability_fact_id TEXT REFERENCES capability_facts (fact_id),
  written_status TEXT NOT NULL CHECK (written_status IN ('observed', 'partial', 'unknown')),
  written_value INTEGER CHECK (written_value >= 0),
  hold_id TEXT REFERENCES holds (hold_id),
  attempted_at TEXT NOT NULL,
  acked_at TEXT,
  receipt TEXT NOT NULL CHECK (json_valid(receipt)),
  UNIQUE (manifest_id, connector_id, attempt),
  CHECK (json_extract(receipt, '$.receipt_version') IS 'export-delivery-receipt/2'
     AND json_extract(receipt, '$.export_receipt_id') IS export_receipt_id
     AND json_extract(receipt, '$.manifest_id') IS manifest_id
     AND json_extract(receipt, '$.connector.connector_id') IS connector_id
     AND json_extract(receipt, '$.connector.connector_type') IS connector_type
     AND json_extract(receipt, '$.attempt') IS attempt
     AND json_extract(receipt, '$.status') IS status
     AND json_extract(receipt, '$.tombstones_acknowledged') IS tombstones_acknowledged
     AND json_extract(receipt, '$.reconciliation_required') IS reconciliation_required
     AND json_extract(receipt, '$.error_class') IS error_class
     AND json_extract(receipt, '$.unknown_cause') IS unknown_cause
     AND json_extract(receipt, '$.capability_fact_id') IS capability_fact_id
     AND json_extract(receipt, '$.written.status') IS written_status
     AND json_extract(receipt, '$.written.value') IS written_value
     AND json_extract(receipt, '$.hold_id') IS hold_id
     AND json_extract(receipt, '$.attempted_at') IS attempted_at
     AND json_extract(receipt, '$.acked_at') IS acked_at),
  -- The written count (observed_count; RG-U): unknown has no value and is
  -- never zero. A delivery observed what it wrote; a skipped delivery and a
  -- failure that applied nothing observed zero; a partial write reports a
  -- partial lower bound; an unknown outcome claims no observed count.
  CHECK ((written_value IS NULL) = (written_status = 'unknown')),
  CHECK (status NOT IN ('delivered', 'skipped_superseded') OR written_status = 'observed'),
  CHECK (status != 'skipped_superseded' OR written_value = 0),
  CHECK (status != 'failed' OR error_class IS NOT 'partial_write' OR written_status = 'partial'),
  CHECK (status != 'failed' OR error_class IS 'partial_write' OR (written_status = 'observed' AND written_value = 0)),
  CHECK (status != 'outcome_unknown' OR written_status IN ('unknown', 'partial')),
  CHECK (status != 'failed' OR error_class IS NOT NULL),
  CHECK (error_class IS NULL OR status = 'failed'),
  CHECK (status != 'delivered' OR (acked_at IS NOT NULL AND tombstones_acknowledged = 1)),
  CHECK (acked_at IS NULL OR status = 'delivered'),
  CHECK (tombstones_acknowledged = 0 OR status = 'delivered'),
  CHECK ((unknown_cause IS NOT NULL) = (status = 'outcome_unknown')),
  CHECK (reconciliation_required = (status = 'outcome_unknown')),
  CHECK (status NOT IN ('failed', 'outcome_unknown') OR capability_fact_id IS NOT NULL),
  CHECK (status != 'delivered' OR capability_fact_id IS NULL)
) STRICT;

-- D48: membership, not vocabulary — a receipt is for a connector the
-- manifest names, with the type the manifest declared for it.
CREATE TRIGGER export_delivery_receipts_expected_connector
BEFORE INSERT ON export_delivery_receipts
WHEN NOT EXISTS (
  SELECT 1 FROM outbox_events e, json_each(e.expected_connectors) j
  WHERE e.manifest_id = NEW.manifest_id AND j.key = NEW.connector_id
    AND json_extract(j.value, '$.connector_type') IS NEW.connector_type)
BEGIN
  SELECT RAISE(ABORT, 'delivery receipt for a connector the manifest does not name');
END;
-- A receipt is about its manifest's material: the topic and ordering pair it
-- reports are the manifest's (P-2), and a hold it names owns this topic's
-- delivery (H-3).
CREATE TRIGGER export_delivery_receipts_describe_their_manifest
BEFORE INSERT ON export_delivery_receipts
WHEN NOT EXISTS (
  SELECT 1 FROM outbox_events e
  WHERE e.manifest_id = NEW.manifest_id
    AND e.topic_id IS json_extract(NEW.receipt, '$.topic_id')
    AND e.generation IS json_extract(NEW.receipt, '$.generation')
    AND e.options_revision IS json_extract(NEW.receipt, '$.options_revision')
    AND (NEW.hold_id IS NULL OR EXISTS (SELECT 1 FROM holds h WHERE h.hold_id = NEW.hold_id AND h.topic_id = e.topic_id)))
BEGIN
  SELECT RAISE(ABORT, 'a delivery receipt describes its manifest: its topic and ordering pair, and any hold it names, are the manifest''s topic''s (P-2)');
END;
CREATE TRIGGER export_delivery_receipts_immutable_u BEFORE UPDATE ON export_delivery_receipts
BEGIN
  SELECT RAISE(ABORT, 'delivery receipts are immutable; a retry or a reconciliation is a new attempt');
END;
CREATE TRIGGER export_delivery_receipts_no_delete BEFORE DELETE ON export_delivery_receipts
BEGIN
  SELECT RAISE(ABORT, 'delivery receipts are never deleted (C-11)');
END;

-- trace: flow S8 item 2 as amended by operator ruling 2026-09-26 ("old
-- retries cannot overwrite newer generations", by the ordering pair);
-- BOUNDARIES.md Exporter (must never overwrite newer material with an old
-- retry); INVARIANTS P-2.
-- The engine's per-connector high-water mark: the highest pair a connector
-- has a delivered receipt for. It never decreases. It is the engine's own
-- bookkeeping, not a reading of the connector's store; the connector's
-- retained evidence is the correctness boundary (EXPORT-API.md §4).
CREATE TABLE connector_watermarks (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  connector_id TEXT NOT NULL CHECK (connector_id GLOB '[a-z]*' AND connector_id NOT GLOB '*[^a-z0-9-]*' AND connector_id NOT GLOB '*-' AND length(connector_id) <= 64),
  generation INTEGER NOT NULL CHECK (generation >= 1),
  options_revision INTEGER NOT NULL CHECK (options_revision >= 1),
  delivered_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, connector_id)
) STRICT;

CREATE TRIGGER connector_watermarks_never_regress
BEFORE UPDATE ON connector_watermarks
WHEN NEW.generation < OLD.generation
  OR (NEW.generation = OLD.generation AND NEW.options_revision < OLD.options_revision)
  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.connector_id IS NOT OLD.connector_id
BEGIN
  SELECT RAISE(ABORT, 'an old retry never overwrites newer material: a connector watermark never regresses (P-2)');
END;
CREATE TRIGGER connector_watermarks_no_delete BEFORE DELETE ON connector_watermarks
BEGIN
  SELECT RAISE(ABORT, 'a connector watermark is never deleted: delete-and-reinsert would regress it (P-2, C-11)');
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
