-- ===========================================================================
-- Engine configuration and registries (task 1d)
-- ===========================================================================

-- trace: design review §4 (retry ceilings, timeouts, cadence and budgets
-- belong to the engine's mounted policy bundle, owned apart from the
-- scientific protocol), §6 ("mounted, validated and activated as versioned
-- bundles. In-flight work retains its pinned bundle"); DEPLOYMENT-CONTRACT.md
-- §2 (versioned bundles, pinned in flight; an invalid bundle is refused with
-- a dated capability fact and the previous one stays active); BOUNDARIES.md
-- Router; schema config-bundle.schema.json; INVARIANTS G-10, RG-9, C-12.
-- One row per activated bundle (config-bundle/1), identified by the JCS hash
-- of its document, which the router computes (hash truth is the router's).
-- Exactly one is active. A new bundle is recorded active with a version
-- above every recorded one, after the router supersedes the active one in
-- the same transaction; a superseded bundle is never reactivated (a
-- rollback is a new, higher version). Nothing else changes and nothing is
-- deleted: every invocation pins the bundle it was admitted under
-- (invocations.config_bundle_hash REFERENCES this table), so a pin always
-- resolves to the policy it was admitted under, across restarts (RG-9).
CREATE TABLE config_bundles (
  bundle_hash TEXT PRIMARY KEY CHECK (bundle_hash GLOB 'sha256:*' AND length(bundle_hash) = 71),
  version INTEGER NOT NULL UNIQUE CHECK (version >= 1),
  document TEXT NOT NULL CHECK (json_valid(document)),
  status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
  activated_at TEXT NOT NULL,
  CHECK (json_extract(document, '$.bundle_version') IS 'config-bundle/1' AND json_extract(document, '$.version') IS version)
) STRICT;

CREATE UNIQUE INDEX config_bundles_one_active ON config_bundles (status) WHERE status = 'active';

CREATE TRIGGER config_bundles_recorded_active_and_newest
BEFORE INSERT ON config_bundles
WHEN NEW.status IS NOT 'active' OR EXISTS (SELECT 1 FROM config_bundles b WHERE b.version >= NEW.version)
BEGIN
  SELECT RAISE(ABORT, 'a config bundle is recorded active, with a version above every recorded one (RG-9)');
END;

-- D-4: a bundle carries no other content under a question version already
-- registered (the router refuses it first as question_altered).
CREATE TRIGGER config_bundles_questions_unaltered
BEFORE INSERT ON config_bundles
WHEN EXISTS (
  SELECT 1 FROM json_each(NEW.document, '$.questions') e JOIN questions q
    ON q.question_id IS json_extract(e.value, '$.question_id') AND q.version IS json_extract(e.value, '$.version')
  WHERE q.content_hash IS NOT json_extract(e.value, '$.content_hash'))
BEGIN
  SELECT RAISE(ABORT, 'a bundle carries a registered question version only under its registered content; a rewording is a new version (D-4)');
END;

CREATE TRIGGER config_bundles_immutable
BEFORE UPDATE ON config_bundles
WHEN NEW.bundle_hash IS NOT OLD.bundle_hash OR NEW.version IS NOT OLD.version OR NEW.document IS NOT OLD.document
  OR NEW.activated_at IS NOT OLD.activated_at OR (OLD.status = 'superseded' AND NEW.status IS NOT 'superseded')
BEGIN
  SELECT RAISE(ABORT, 'a config bundle never changes: the active one is superseded, and a superseded one is never reactivated (RG-9)');
END;

CREATE TRIGGER config_bundles_no_delete BEFORE DELETE ON config_bundles
BEGIN
  SELECT RAISE(ABORT, 'config bundles are never deleted: in-flight and historical work pins them (RG-9)');
END;

-- trace: flow §5 (a versioned question registry, mounted: a rewording is a
-- new version and a visible calibration event), §2 (every automated
-- decision runs under a DecisionSpec pinning its question version), §3
-- step 1; DEPLOYMENT-CONTRACT.md §2; schema
-- decision-spec.schema.json#/properties/question and
-- config-bundle.schema.json#/properties/questions; INVARIANTS D-1, D-4, §13
-- (question registry: loading, pinning and restart retention in Phase 1).
-- One row per question version, recorded when the first bundle carrying it
-- is activated, and equal to that bundle's entry. A (question id, version)
-- has one content forever: another content under a recorded version is a
-- different content hash, which the primary key and the immutability below
-- refuse (the router refuses such a bundle first). A DecisionSpec is stored
-- only with a question recorded here under exactly its version and hash
-- (decision_specs_question_registered): an unknown or altered question pins
-- nothing.
CREATE TABLE questions (
  question_id TEXT NOT NULL CHECK (length(question_id) BETWEEN 1 AND 64),
  version INTEGER NOT NULL CHECK (version >= 1),
  content_hash TEXT NOT NULL UNIQUE CHECK (content_hash GLOB 'sha256:*' AND length(content_hash) = 71),
  document TEXT NOT NULL CHECK (json_valid(document)),
  registered_by_bundle_hash TEXT NOT NULL REFERENCES config_bundles (bundle_hash),
  registered_at TEXT NOT NULL,
  PRIMARY KEY (question_id, version),
  CHECK (json_extract(document, '$.question_id') IS question_id AND json_extract(document, '$.version') IS version
     AND json_extract(document, '$.content_hash') IS content_hash)
) STRICT;

CREATE TRIGGER questions_carried_by_their_bundle
BEFORE INSERT ON questions
WHEN NOT EXISTS (
  SELECT 1 FROM config_bundles b, json_each(b.document, '$.questions') q
  WHERE b.bundle_hash = NEW.registered_by_bundle_hash AND q.value IS json(NEW.document))
BEGIN
  SELECT RAISE(ABORT, 'a question version is recorded as the entry of the bundle that registers it (D-1)');
END;

CREATE TRIGGER questions_immutable_u BEFORE UPDATE ON questions
BEGIN
  SELECT RAISE(ABORT, 'a question version is immutable; a rewording is a new version (flow §5, D-4)');
END;
CREATE TRIGGER questions_no_delete BEFORE DELETE ON questions
BEGIN
  SELECT RAISE(ABORT, 'question versions are never deleted: specs and decisions pin them (D-1)');
END;

-- D-1 (task 1d): a DecisionSpec pins a question version the registry holds,
-- under exactly its content hash.
CREATE TRIGGER decision_specs_question_registered
BEFORE INSERT ON decision_specs
WHEN NOT EXISTS (
  SELECT 1 FROM questions q
  WHERE q.question_id IS json_extract(NEW.document, '$.question.question_id')
    AND q.version IS json_extract(NEW.document, '$.question.version')
    AND q.content_hash IS json_extract(NEW.document, '$.question.content_hash'))
BEGIN
  SELECT RAISE(ABORT, 'a DecisionSpec pins a question version recorded in the registry under exactly its hash; an unknown or altered question pins nothing (D-1, D-4)');
END;

-- trace: flow §2 (qualification is per provider and per class, for one
-- DecisionSpec; any behavior-affecting change retires it; each class starts
-- advisory), §3 step 6 (the replay audit re-derives each class's authority
-- from the qualification records; revoked qualifications must end in
-- rejection or a visible control incident); BOUNDARIES.md Decision layer,
-- Router (never soften or reinterpret a qualification); INVARIANTS D-4,
-- D-5, D-11, §13 (fake qualification and revocation records exercise the
-- authority fences in Phase 1; immutable evaluations and population
-- provenance are Phase 3).
-- One row per qualification of exactly one (provider, decision class,
-- DecisionSpec), equal to its spec's. evaluation_ref names the declared
-- evaluation it rests on; every Phase 1 record is a fake whose
-- evaluation_ref names no real evaluation, which this table cannot tell and
-- does not claim to. A record is created live; revocation is recorded once
-- and is final; nothing else changes. A decision receipt acts at qualified
-- authority only under a record here, live when the receipt is committed,
-- of its own provider, class and spec (decision_receipts_qualification_live):
-- a non-null qualification_ref naming anything else is not qualification.
CREATE TABLE qualifications (
  qualification_id TEXT PRIMARY KEY CHECK (qualification_id GLOB 'qual_*'),
  provider TEXT NOT NULL CHECK (provider IN ('jev', 'llm_fallback')),
  decision_class TEXT NOT NULL,
  spec_hash TEXT NOT NULL REFERENCES decision_specs (spec_hash),
  evaluation_ref TEXT NOT NULL CHECK (length(evaluation_ref) > 0),
  granted_by TEXT NOT NULL CHECK (length(granted_by) > 0),
  granted_at TEXT NOT NULL,
  revoked_by TEXT,
  revoked_at TEXT,
  revoke_reason TEXT,
  CHECK ((revoked_by IS NULL) = (revoked_at IS NULL) AND (revoked_at IS NULL) = (revoke_reason IS NULL))
) STRICT;

CREATE TRIGGER qualifications_created_live_for_their_spec
BEFORE INSERT ON qualifications
WHEN NEW.revoked_at IS NOT NULL OR NOT EXISTS (
  SELECT 1 FROM decision_specs s WHERE s.spec_hash = NEW.spec_hash AND s.provider = NEW.provider AND s.decision_class = NEW.decision_class)
BEGIN
  SELECT RAISE(ABORT, 'a qualification is recorded live, for exactly its spec''s provider and decision class (D-4)');
END;

CREATE TRIGGER qualifications_revoked_once
BEFORE UPDATE ON qualifications
WHEN OLD.revoked_at IS NOT NULL
  OR NEW.qualification_id IS NOT OLD.qualification_id OR NEW.provider IS NOT OLD.provider OR NEW.decision_class IS NOT OLD.decision_class
  OR NEW.spec_hash IS NOT OLD.spec_hash OR NEW.evaluation_ref IS NOT OLD.evaluation_ref OR NEW.granted_by IS NOT OLD.granted_by
  OR NEW.granted_at IS NOT OLD.granted_at
BEGIN
  SELECT RAISE(ABORT, 'a qualification changes only by its revocation, once and finally (D-4)');
END;
CREATE TRIGGER qualifications_no_delete BEFORE DELETE ON qualifications
BEGIN
  SELECT RAISE(ABORT, 'qualifications are never deleted: the replay audit re-derives authority from them (D-10)');
END;

-- D-5, D-11 (task 1d): qualified authority rests on a live qualification of
-- exactly this spec, whatever string the receipt names. (The spec fixes the
-- provider and class: a record's are its spec's, qualifications_created_live_
-- for_their_spec, and so are a receipt's, decision_receipts_match_spec.)
CREATE TRIGGER decision_receipts_qualification_live
BEFORE INSERT ON decision_receipts
WHEN NEW.authority_level = 'qualified' AND NOT EXISTS (
  SELECT 1 FROM qualifications q
  WHERE q.qualification_id = NEW.qualification_ref AND q.spec_hash = NEW.spec_hash AND q.revoked_at IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'qualified authority needs a live qualification of this provider, class and spec; a reference naming anything else is not qualification (D-5, D-11)');
END;

-- trace: flow S6 (a protected exploration budget the productive branch
-- cannot consume), §6.4 (auto-promotion only inside an existing facet whose
-- operator-confirmed rating is at or above the declared threshold, bound to
-- the exact approved contract revision and the remaining auto-budget
-- reservation; suspended during a reframe migration); design review §5
-- ("Already admitted work may finish within its existing deadline and
-- reservation"); BOUNDARIES.md Router (scheduling); INVARIANTS G-5, G-10,
-- §13 (reservations are Phase 1; the promotion mechanism is Phase 3).
-- A reservation holds `units` admissions for one purpose of one topic,
-- bound to the approved contract revision it was opened under and sized by
-- the active bundle's policy (the size and threshold are that bundle's
-- values). One open reservation per (topic, purpose). It closes once — when
-- an amendment supersedes its revision (G-1 impact), or explicitly — and a
-- closed reservation admits nothing more.
CREATE TABLE reservations (
  reservation_id TEXT PRIMARY KEY CHECK (reservation_id GLOB 'rsv_*'),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  purpose TEXT NOT NULL CHECK (purpose IN ('protected_exploration', 'auto_promotion')),
  contract_revision INTEGER NOT NULL,
  units INTEGER NOT NULL CHECK (units >= 1),
  min_band TEXT CHECK (min_band IN ('critical', 'important', 'limited')),
  bundle_hash TEXT NOT NULL REFERENCES config_bundles (bundle_hash),
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  close_reason TEXT,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK ((purpose = 'auto_promotion') = (min_band IS NOT NULL)),
  CHECK ((closed_at IS NULL) = (close_reason IS NULL))
) STRICT;

CREATE UNIQUE INDEX reservations_one_open_per_purpose ON reservations (topic_id, purpose) WHERE closed_at IS NULL;

CREATE TRIGGER reservations_opened_under_the_approved_revision
BEFORE INSERT ON reservations
WHEN NEW.closed_at IS NOT NULL
  OR NOT EXISTS (SELECT 1 FROM contract_revisions c WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.contract_revision AND c.status = 'approved')
  OR NOT EXISTS (
    SELECT 1 FROM config_bundles b
    WHERE b.bundle_hash = NEW.bundle_hash
      AND json_extract(b.document, '$.policy.router.reservations.' || NEW.purpose || '.units') IS NEW.units
      AND json_extract(b.document, '$.policy.router.reservations.' || NEW.purpose || '.min_band') IS NEW.min_band)
BEGIN
  SELECT RAISE(ABORT, 'a reservation is opened under its topic''s approved contract revision, sized as its bundle declares (G-5, G-10)');
END;

CREATE TRIGGER reservations_close_once
BEFORE UPDATE ON reservations
WHEN OLD.closed_at IS NOT NULL
  OR NEW.reservation_id IS NOT OLD.reservation_id OR NEW.topic_id IS NOT OLD.topic_id OR NEW.purpose IS NOT OLD.purpose
  OR NEW.contract_revision IS NOT OLD.contract_revision OR NEW.units IS NOT OLD.units OR NEW.min_band IS NOT OLD.min_band
  OR NEW.bundle_hash IS NOT OLD.bundle_hash OR NEW.opened_at IS NOT OLD.opened_at
BEGIN
  SELECT RAISE(ABORT, 'a reservation changes only by closing, once (G-5)');
END;
CREATE TRIGGER reservations_no_delete BEFORE DELETE ON reservations
BEGIN
  SELECT RAISE(ABORT, 'reservations are never deleted');
END;

-- trace: as reservations. One row per admission drawn on a reservation:
-- the non-delegate invocation admitted under it (a delegate runs under its
-- parent's draw). The checks G-5 names: within the reservation (fewer draws
-- than its units), revision-bound (the reservation is open, its revision is
-- still the topic's approved one and is exactly the revision the invocation
-- was admitted under), and, for auto-promotion, inside an existing facet of
-- that revision whose operator-confirmed band is at or above the declared
-- threshold — a Jev score is never the rating (G-2).
CREATE TABLE reservation_draws (
  invocation_id TEXT PRIMARY KEY REFERENCES invocations (invocation_id),
  reservation_id TEXT NOT NULL REFERENCES reservations (reservation_id),
  facet_id TEXT,
  drawn_at TEXT NOT NULL
) STRICT;

CREATE TRIGGER reservation_draws_within_and_revision_bound
BEFORE INSERT ON reservation_draws
WHEN NOT EXISTS (
  SELECT 1 FROM reservations r
  JOIN invocations i ON i.invocation_id = NEW.invocation_id
  JOIN contract_revisions c ON c.topic_id = r.topic_id AND c.revision = r.contract_revision
  WHERE r.reservation_id = NEW.reservation_id AND r.closed_at IS NULL AND c.status = 'approved'
    AND i.topic_id = r.topic_id AND i.kind != 'delegate' AND i.contract_revision IS r.contract_revision
    AND (SELECT count(*) FROM reservation_draws d WHERE d.reservation_id = r.reservation_id) < r.units
    AND (r.purpose = 'auto_promotion') = (NEW.facet_id IS NOT NULL)
    AND (NEW.facet_id IS NULL OR EXISTS (
          SELECT 1 FROM facets f
          WHERE f.topic_id = r.topic_id AND f.contract_revision = r.contract_revision AND f.facet_id = NEW.facet_id
            AND CASE f.operator_importance_band WHEN 'critical' THEN 3 WHEN 'important' THEN 2 WHEN 'limited' THEN 1 ELSE 0 END
             >= CASE r.min_band WHEN 'critical' THEN 3 WHEN 'important' THEN 2 WHEN 'limited' THEN 1 END)))
BEGIN
  SELECT RAISE(ABORT, 'a draw is within its open reservation, bound to the approved revision its invocation was admitted under, and an auto-promotion draw names a facet rated at or above the threshold (G-5)');
END;

CREATE TRIGGER reservation_draws_immutable_u BEFORE UPDATE ON reservation_draws
BEGIN
  SELECT RAISE(ABORT, 'a reservation draw is a record: it never changes');
END;
CREATE TRIGGER reservation_draws_no_delete BEFORE DELETE ON reservation_draws
BEGIN
  SELECT RAISE(ABORT, 'reservation draws are never deleted: they are the reservation''s consumption');
END;

-- trace: design review §6 ("Every retry path consumes a declared
-- attempt/time budget"; "Known transient faults retry within budget;
-- suspected semantic faults are diagnosed or revised, not blindly
-- retried"), §10 gate 3 (exhausted retries end in a bounded, visible
-- state); BOUNDARIES.md Router (scheduling), Station supervisor;
-- INVARIANTS L-6, RG-3; the 1c deferral (Astra 1c review, rulings on
-- questions 2 and 4: scheduling and retry of failed and cancelled work).
-- One row per re-queue: the non-delegate invocation that ended failed or
-- cancelled, the attempt its retry will be (one more than its own), who
-- asked and why. The retry is the next admission of that lane and names it
-- (retry_invocation_id: set once, to an invocation of the same topic and
-- kind). The budget and the retryable classes are the ended invocation's
-- pinned bundle's; the router checks them (they are policy, not shape).
CREATE TABLE retries (
  invocation_id TEXT PRIMARY KEY REFERENCES invocations (invocation_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  attempt INTEGER NOT NULL CHECK (attempt >= 2),
  requested_by TEXT NOT NULL CHECK (requested_by IN ('operator', 'policy')),
  reason TEXT NOT NULL CHECK (length(reason) > 0),
  requested_at TEXT NOT NULL,
  retry_invocation_id TEXT UNIQUE REFERENCES invocations (invocation_id)
) STRICT;

CREATE TRIGGER retries_of_ended_work_counted
BEFORE INSERT ON retries
WHEN NEW.retry_invocation_id IS NOT NULL
  OR NOT EXISTS (SELECT 1 FROM invocations i WHERE i.invocation_id = NEW.invocation_id AND i.topic_id = NEW.topic_id
                   AND i.kind != 'delegate' AND i.state IN ('failed', 'cancelled'))
  OR NEW.attempt IS NOT coalesce((SELECT r.attempt FROM retries r WHERE r.retry_invocation_id = NEW.invocation_id), 1) + 1
BEGIN
  SELECT RAISE(ABORT, 'a re-queue is of a non-delegate invocation of its topic that ended failed or cancelled, counting one attempt more than it (L-6)');
END;

CREATE TRIGGER retries_claimed_once
BEFORE UPDATE ON retries
WHEN OLD.retry_invocation_id IS NOT NULL
  OR NEW.invocation_id IS NOT OLD.invocation_id OR NEW.topic_id IS NOT OLD.topic_id OR NEW.attempt IS NOT OLD.attempt
  OR NEW.requested_by IS NOT OLD.requested_by OR NEW.reason IS NOT OLD.reason OR NEW.requested_at IS NOT OLD.requested_at
  OR NOT EXISTS (SELECT 1 FROM invocations n JOIN invocations o ON o.invocation_id = OLD.invocation_id
                 WHERE n.invocation_id = NEW.retry_invocation_id AND n.topic_id = o.topic_id AND n.kind = o.kind)
BEGIN
  SELECT RAISE(ABORT, 'a re-queue is claimed once, by an invocation of the same topic and kind (L-6)');
END;
CREATE TRIGGER retries_no_delete BEFORE DELETE ON retries
BEGIN
  SELECT RAISE(ABORT, 're-queues are never deleted: they are the retry budget''s consumption');
END;

-- trace: design review §4 ("An amended protocol triggers deterministic
-- identification of affected screening labels, dossiers, verification, and
-- index generations; it must not silently reuse incompatible results"),
-- §5 step 3 ("Reject or explicitly reconcile stale work"); flow S3, §6.1
-- (an edited brief re-versions), §6.4-6.5 (reframe migration: labels and
-- coverage stale-under-new-framing, exclusions reopened; auto-promotions
-- suspended); BOUNDARIES.md Router; INVARIANTS G-1, G-6, C-10, C-12, V-10;
-- the 1a review (G-1 impact before Phase 1 acceptance) and the 1b review's
-- ruling on proposal 3 (amendment_pending is interim).
-- One immutable record per approval that supersedes a contract revision
-- (contract/amendment/reframe approval) or a confirmed brief version (brief
-- confirmation): its deterministic classification and the document listing
-- every affected item with its disposition, written in the approval's own
-- transaction. The record identifies; it rewrites nothing it lists.
CREATE TABLE amendment_impacts (
  decision_id TEXT PRIMARY KEY REFERENCES operator_decisions (decision_id),
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  kind TEXT NOT NULL CHECK (kind IN ('contract', 'brief')),
  classification TEXT NOT NULL CHECK (classification IN ('compatible', 'protocol_changed', 'reframed', 'lineage_only', 'content_changed')),
  document TEXT NOT NULL CHECK (json_valid(document)),
  recorded_at TEXT NOT NULL,
  CHECK ((kind = 'contract') = (classification IN ('compatible', 'protocol_changed', 'reframed'))),
  CHECK (json_extract(document, '$.decision_id') IS decision_id AND json_extract(document, '$.topic_id') IS topic_id
     AND json_extract(document, '$.kind') IS kind AND json_extract(document, '$.classification') IS classification)
) STRICT;

CREATE TRIGGER amendment_impacts_of_an_approval
BEFORE INSERT ON amendment_impacts
WHEN NOT EXISTS (
  SELECT 1 FROM operator_decisions d
  WHERE d.decision_id = NEW.decision_id AND d.topic_id = NEW.topic_id AND d.disposition = 'approved'
    AND d.kind IN (CASE NEW.kind WHEN 'contract' THEN 'contract_approval' ELSE 'brief_confirmation' END,
                   CASE NEW.kind WHEN 'contract' THEN 'amendment_approval' END, CASE NEW.kind WHEN 'contract' THEN 'reframe_approval' END))
BEGIN
  SELECT RAISE(ABORT, 'an amendment impact is recorded for an approved contract or brief approval of its topic (G-1)');
END;

CREATE TRIGGER amendment_impacts_immutable_u BEFORE UPDATE ON amendment_impacts
BEGIN
  SELECT RAISE(ABORT, 'an amendment impact record is immutable');
END;
CREATE TRIGGER amendment_impacts_no_delete BEFORE DELETE ON amendment_impacts
BEGIN
  SELECT RAISE(ABORT, 'amendment impact records are never deleted (G-1: older revisions and decisions are preserved)');
END;

-- trace: flow S1, §6.1 (an edited brief re-versions; the contract takes it
-- only through an approved framework diff), S3; INVARIANTS G-4, G-6, C-12;
-- task 2a-repair-3 (Astra 2a-repair-2 review, F1-R continued: that a brief
-- was replaced is recorded when it happens, not reconstructed from history).
-- One permanent row per confirmed brief version that a later confirmation
-- replaced, written by the router in the confirming decision's transaction
-- for every version of the topic confirmed before it, of any brief id, that
-- it does not succeed in lineage alone (amendments.py). Archiving either
-- version, or confirming the old content again, removes nothing. After the
-- topic's first contract approval, a revision naming a replaced version is
-- neither proposed nor approved; one naming the newer basis incorporates it
-- (G-6: a changed decision record is a reframe).
CREATE TABLE brief_replacements (
  topic_id TEXT NOT NULL,
  brief_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  replaced_by_decision_id TEXT NOT NULL REFERENCES operator_decisions (decision_id),
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, brief_id, version),
  FOREIGN KEY (topic_id, brief_id, version) REFERENCES intake_briefs (topic_id, brief_id, version)
) STRICT;

-- By the decision that confirmed the topic's confirmed version, about a
-- version another decision confirmed: so one confirmed before it (one
-- confirmed version per topic, and confirmed is never re-entered).
CREATE TRIGGER brief_replacements_by_a_later_confirmation
BEFORE INSERT ON brief_replacements
WHEN NOT EXISTS (
  SELECT 1 FROM intake_briefs n, intake_briefs o
  WHERE n.topic_id = NEW.topic_id AND n.status = 'confirmed' AND n.confirmed_by_decision_id = NEW.replaced_by_decision_id
    AND o.topic_id = NEW.topic_id AND o.brief_id = NEW.brief_id AND o.version = NEW.version
    AND o.confirmed_by_decision_id != NEW.replaced_by_decision_id)
BEGIN
  SELECT RAISE(ABORT, 'a brief version is replaced only by the decision confirming a later version of its topic (G-4)');
END;

CREATE TRIGGER brief_replacements_immutable_u BEFORE UPDATE ON brief_replacements
BEGIN
  SELECT RAISE(ABORT, 'a brief replacement is permanent');
END;
CREATE TRIGGER brief_replacements_no_delete BEFORE DELETE ON brief_replacements
BEGIN
  SELECT RAISE(ABORT, 'brief replacements are never deleted: a replaced version stays replaced');
END;

-- G-12 (task 1d): the coalesced signal queue attaches a trigger only to a
-- review episode of its own topic.
CREATE TRIGGER review_triggers_episode_of_their_topic
BEFORE UPDATE OF episode_id ON review_triggers
WHEN NEW.episode_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM review_episodes e WHERE e.episode_id = NEW.episode_id AND e.topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'a trigger joins only a review episode of its own topic (G-12)');
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
