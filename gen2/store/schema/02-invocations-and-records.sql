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
  config_bundle_hash TEXT NOT NULL REFERENCES config_bundles (bundle_hash),
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
-- digest; terminal resolutions confirm descendant handling. `request` keeps
-- the reconciliation's complete normalized factual request (resolution,
-- method, evidence, result digest, failure class, process identity) so a
-- replay is compared with every fact it asserted, not only those with
-- columns (Astra 1c review A8); its first four agree with the columns.
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
  request TEXT NOT NULL CHECK (json_valid(request) AND json_type(request) = 'object'),
  UNIQUE (invocation_id, unknown_episode),
  CHECK (json_extract(request, '$.resolution') IS resolution AND json_extract(request, '$.method') IS method
         AND json_extract(request, '$.evidence_ref') IS evidence_ref AND json_extract(request, '$.result_payload_digest') IS result_payload_digest),
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

-- trace: INVARIANTS L-1 (transition audit); flow §4.1. `facts`: the normalized
-- facts of the lifecycle request a transition recorded (record_transition),
-- among them an outcome_unknown entry's episode and cause, so a replay is
-- compared with all of them (Astra 1c review A8); none for the router's own.
CREATE TABLE invocation_transitions (
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  seq INTEGER NOT NULL CHECK (seq >= 1),
  from_state TEXT,
  to_state TEXT NOT NULL,
  at TEXT NOT NULL,
  cause TEXT NOT NULL,
  facts TEXT CHECK (facts IS NULL OR (json_valid(facts) AND json_type(facts) = 'object')),
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
--   source_proposal    proposal id / - / proposal content hash (task 2a)
--   contract_revision  topic id / contract revision / contract content_hash
--   dossier            topic id / dossier revision / dossier content_hash
--   topic              topic id / queue state_revision decided against / -
--   hold               hold id / - / -
--   publication_source source ref / source revision / source content hash
--   decision_receipt   decision receipt id / - / -
-- The kind -> subject-kind mapping is a CHECK, so consuming gates test the
-- decision kind (which fixes the subject kind). Subjects stored here are
-- checked to exist with that exact hash when the decision is recorded
-- (intake briefs since 0b: topic, brief id, version and hash; scoping reports
-- and source proposals since task 2a); publication-source subjects are not
-- store rows yet, so only their shape is checked. Consuming gates then re-check kind, disposition,
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
    'hold_clearance', 'publication_approval', 'blind_initial_disposition', 'advised_feedback', 'source_approval')),
  disposition TEXT NOT NULL CHECK (disposition IN ('approved', 'rejected', 'deferred', 'recorded')),
  subject_kind TEXT NOT NULL CHECK (subject_kind IN (
    'intake_brief', 'scoping_report', 'contract_revision', 'dossier', 'topic', 'hold',
    'publication_source', 'decision_receipt', 'source_proposal')),
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
      OR (kind IN ('blind_initial_disposition', 'advised_feedback') AND subject_kind = 'decision_receipt')
      OR (kind = 'source_approval' AND subject_kind = 'source_proposal')),
  CHECK (subject_kind NOT IN ('intake_brief', 'scoping_report', 'contract_revision', 'dossier', 'publication_source')
      OR (subject_revision IS NOT NULL AND subject_hash IS NOT NULL)),
  CHECK (subject_kind NOT IN ('contract_revision', 'dossier', 'topic') OR subject_ref IS topic_id),
  CHECK (subject_kind != 'topic' OR subject_revision IS NOT NULL),
  CHECK (subject_kind != 'source_proposal' OR (subject_revision IS NULL AND subject_hash IS NOT NULL)),
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
  OR (NEW.subject_kind = 'scoping_report' AND NOT EXISTS (
        SELECT 1 FROM scoping_reports s
        WHERE s.topic_id = NEW.topic_id AND s.report_id = NEW.subject_ref AND s.version = NEW.subject_revision AND s.content_hash = NEW.subject_hash))
  OR (NEW.subject_kind = 'source_proposal' AND NOT EXISTS (
        SELECT 1 FROM source_proposals p WHERE p.proposal_id = NEW.subject_ref AND p.topic_id = NEW.topic_id AND p.content_hash = NEW.subject_hash))
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
-- opened_after_generation (task 2a-repair F2): the topic's latest lease
-- generation when the episode opened (0: none yet), so work admitted after it
-- holds a greater one — commit order, where wall time can repeat or step back.
-- A checkpoint closes only an episode opened before its admission (router).
CREATE TABLE review_episodes (
  episode_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  kind TEXT NOT NULL CHECK (kind IN ('fixed_cadence', 'obligations_scope', 'method_fit', 'facet_audit', 'calibration', 'state_integrity_audit')),
  opened_at TEXT NOT NULL,
  opened_after_generation INTEGER NOT NULL DEFAULT 0 CHECK (opened_after_generation >= 0),
  opened_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  closed_at TEXT,
  closed_by_operation_id TEXT REFERENCES operation_receipts (operation_id),
  CHECK ((closed_at IS NULL) = (closed_by_operation_id IS NULL))
) STRICT;

CREATE TRIGGER review_episodes_close_once
BEFORE UPDATE ON review_episodes
WHEN OLD.closed_at IS NOT NULL
  OR NEW.episode_id IS NOT OLD.episode_id OR NEW.topic_id IS NOT OLD.topic_id
  OR NEW.kind IS NOT OLD.kind OR NEW.opened_at IS NOT OLD.opened_at OR NEW.opened_after_generation IS NOT OLD.opened_after_generation
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
-- One exception (task 2b-repair-3 R2): a gateway snapshot that reaches the
-- router after a newer revision of its episode is inserted directly behind
-- the capability's current fact, as its predecessor. Such a fact is no one's
-- successor, then or later (a successor must be current), so it is never in
-- a cycle, and the current fact stays the newest. `revision` is the
-- gateway's order of its episode's snapshots; null for any other fact.
CREATE TABLE capability_facts (
  fact_id TEXT PRIMARY KEY,
  capability TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('healthy', 'degraded', 'failing', 'unknown')),
  detail TEXT NOT NULL,
  since TEXT NOT NULL,
  last_success_at TEXT,
  affected_lanes TEXT NOT NULL CHECK (json_valid(affected_lanes) AND json_type(affected_lanes) = 'array'),
  revision INTEGER CHECK (revision >= 1),
  observed_by_invocation_id TEXT REFERENCES invocations (invocation_id),
  superseded_by_fact_id TEXT REFERENCES capability_facts (fact_id) DEFERRABLE INITIALLY DEFERRED,
  recorded_at TEXT NOT NULL,
  CHECK (superseded_by_fact_id IS NOT fact_id)
) STRICT;

CREATE UNIQUE INDEX capability_facts_one_current_per_capability
  ON capability_facts (capability) WHERE superseded_by_fact_id IS NULL;

CREATE TRIGGER capability_facts_insert_current_same_capability
BEFORE INSERT ON capability_facts
WHEN (NEW.superseded_by_fact_id IS NOT NULL AND (
       NOT EXISTS (SELECT 1 FROM capability_facts c WHERE c.fact_id = NEW.superseded_by_fact_id
                   AND c.capability IS NEW.capability AND c.superseded_by_fact_id IS NULL)
       OR EXISTS (SELECT 1 FROM capability_facts o WHERE o.superseded_by_fact_id = NEW.fact_id)))
  OR EXISTS (SELECT 1 FROM capability_facts o WHERE o.superseded_by_fact_id = NEW.fact_id AND o.capability IS NOT NEW.capability)
BEGIN
  SELECT RAISE(ABORT, 'a capability fact is inserted current, and only as the successor of a fact of the same capability, or directly behind its capability''s current fact (A9)');
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
  OR NEW.last_success_at IS NOT OLD.last_success_at OR NEW.affected_lanes IS NOT OLD.affected_lanes OR NEW.revision IS NOT OLD.revision
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

-- Task 1c-repair (Astra 1c review A7): the converse. The router hold of an
-- outcome_unknown episode clears only through a reconciliation record (the
-- trigger above binds it to that episode's own): an operator decision or an
-- operation clears nothing here, whatever API writes the clearing. Other
-- holds keep their decision and operation clearing.
CREATE TRIGGER holds_episode_cleared_only_by_reconciliation
BEFORE UPDATE OF cleared_at ON holds
WHEN NEW.cleared_at IS NOT NULL AND OLD.cleared_at IS NULL
  AND OLD.required_authority = 'router' AND OLD.subject_ref GLOB 'invocation:*#unknown:*'
  AND NEW.cleared_by_reconciliation_id IS NULL
BEGIN
  SELECT RAISE(ABORT, 'an outcome_unknown episode hold clears only through its reconciliation record (L-4)');
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

