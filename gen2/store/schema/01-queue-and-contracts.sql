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

-- trace: flow S2 (the Scoping Report in PRISMA-ScR item shape: territory map,
-- tradition census, candidate facets, gap-map skeleton, deliberately-out
-- list, discovery mechanisms and coverage facts per lane; hand-off: the
-- operator's scope approval), §6.2 (the gap-map skeleton is matrix v0);
-- design review §4 (exploratory discovery before binding protocol approval);
-- BOUNDARIES.md Router, Operator; schema scoping-report.schema.json;
-- INVARIANTS C-12, G-4, G-13.
-- Task 2a. One row per committed report version. Pre-contract research work
-- of the topic commits it through commit_outcome, and the router moves the
-- topic scoping -> awaiting_scope_approval in the same transaction; a scope
-- approval names exactly one stored version and hash
-- (operator_decisions_subject_exists). The report names the confirmed brief
-- it scoped, which must be its committing work's admission pin. Content,
-- lineage and provenance are immutable: a rework is a new version.
CREATE TABLE scoping_reports (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  report_id TEXT NOT NULL CHECK (length(report_id) BETWEEN 1 AND 64 AND report_id GLOB '[A-Za-z]*' AND report_id NOT GLOB '*[^A-Za-z0-9._-]*'),
  version INTEGER NOT NULL CHECK (version >= 1),
  parent_version INTEGER,
  content_hash TEXT NOT NULL UNIQUE CHECK (content_hash GLOB 'sha256:*' AND length(content_hash) = 71),
  document TEXT NOT NULL CHECK (json_valid(document)),
  brief_id TEXT NOT NULL,
  brief_version INTEGER NOT NULL,
  brief_hash TEXT NOT NULL,
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  committed_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, report_id, version),
  FOREIGN KEY (topic_id, report_id, parent_version) REFERENCES scoping_reports (topic_id, report_id, version),
  FOREIGN KEY (topic_id, brief_id, brief_version) REFERENCES intake_briefs (topic_id, brief_id, version),
  CONSTRAINT scoping_report_parent_is_earlier CHECK (parent_version IS NULL OR parent_version < version),
  CHECK (json_extract(document, '$.topic_id') IS topic_id
     AND json_extract(document, '$.report_id') IS report_id
     AND json_extract(document, '$.version') IS version
     AND json_extract(document, '$.parent_version') IS parent_version
     AND json_extract(document, '$.content_hash') IS content_hash
     AND json_extract(document, '$.brief.brief_id') IS brief_id
     AND json_extract(document, '$.brief.version') IS brief_version
     AND json_extract(document, '$.brief.content_hash') IS brief_hash)
) STRICT;

-- C-12: a scoping report is pre-contract work's. It is committed by the
-- operation of the invocation it names, of its topic, admitted under
-- pre-contract/1 and pinned to exactly the brief version and hash the report
-- names.
CREATE TRIGGER scoping_reports_by_pre_contract_work
BEFORE INSERT ON scoping_reports
WHEN NOT EXISTS (
  SELECT 1 FROM operation_receipts r JOIN invocations i ON i.invocation_id = r.invocation_id
  WHERE r.operation_id = NEW.committed_by_operation_id AND r.invocation_id = NEW.invocation_id
    AND i.topic_id = NEW.topic_id AND i.admission_context = 'pre-contract/1'
    AND i.brief_ref IS NEW.brief_id AND i.brief_version IS NEW.brief_version AND i.brief_hash IS NEW.brief_hash)
BEGIN
  SELECT RAISE(ABORT, 'a scoping report is committed by pre-contract work of its topic pinned to exactly the brief it names (C-12)');
END;

CREATE TRIGGER scoping_reports_immutable_u BEFORE UPDATE ON scoping_reports
BEGIN
  SELECT RAISE(ABORT, 'scoping reports are immutable; a rework is a new version');
END;
CREATE TRIGGER scoping_reports_no_delete BEFORE DELETE ON scoping_reports
BEGIN
  SELECT RAISE(ABORT, 'scoping reports are never deleted (C-11)');
END;

-- trace: docs/gen2/SOURCE-GOVERNANCE.md steps 1-2 (an agent's typed proposal
-- through commit_outcome, retained, authorizing nothing; the operator's
-- approve/reject/defer about exactly that proposal); flow §2 (a new option is
-- generation, a proposal to the operator); design review §6 (a new adapter is
-- an image release; agents introduce no executables); schema
-- source-proposal.schema.json; BOUNDARIES.md Operator, Primary agent,
-- Secondary/delegate agents, Gateway; INVARIANTS G-13, B-2.
-- Task 2a. The retained proposal. Nothing here writes the gateway's registry,
-- enables a lane or holds a credential: the document has no field for any of
-- them, and no table of this store is the registry. content_hash is the JCS
-- hash of the whole document (it carries none of its own), computed by the
-- router; a source_approval decision names it.
CREATE TABLE source_proposals (
  proposal_id TEXT PRIMARY KEY CHECK (proposal_id GLOB 'srcp_*'),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  content_hash TEXT NOT NULL UNIQUE CHECK (content_hash GLOB 'sha256:*' AND length(content_hash) = 71),
  document TEXT NOT NULL CHECK (json_valid(document)),
  proposed_by_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  committed_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  supersedes_proposal_id TEXT REFERENCES source_proposals (proposal_id),
  created_at TEXT NOT NULL,
  CHECK (supersedes_proposal_id IS NOT proposal_id),
  CHECK (json_extract(document, '$.proposal_id') IS proposal_id
     AND json_extract(document, '$.topic_id') IS topic_id
     AND json_extract(document, '$.proposed_by.invocation_id') IS proposed_by_invocation_id
     AND json_extract(document, '$.supersedes_proposal_id') IS supersedes_proposal_id)
) STRICT;

-- The proposer is the committing invocation, of the proposal's topic and of
-- the kind the document says (authority from the capability, never from a
-- document field).
CREATE TRIGGER source_proposals_by_their_proposer
BEFORE INSERT ON source_proposals
WHEN NOT EXISTS (
  SELECT 1 FROM operation_receipts r JOIN invocations i ON i.invocation_id = r.invocation_id
  WHERE r.operation_id = NEW.committed_by_operation_id AND r.invocation_id = NEW.proposed_by_invocation_id
    AND i.topic_id = NEW.topic_id AND i.kind IS json_extract(NEW.document, '$.proposed_by.invocation_kind'))
BEGIN
  SELECT RAISE(ABORT, 'a source proposal is committed by the invocation that proposes it, of its topic and kind (G-13)');
END;

CREATE TRIGGER source_proposals_immutable_u BEFORE UPDATE ON source_proposals
BEGIN
  SELECT RAISE(ABORT, 'source proposals are immutable; a re-proposal is a new proposal naming the one it supersedes');
END;
CREATE TRIGGER source_proposals_no_delete BEFORE DELETE ON source_proposals
BEGIN
  SELECT RAISE(ABORT, 'source proposals are never deleted; a rejection is a decision, not a deletion');
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

