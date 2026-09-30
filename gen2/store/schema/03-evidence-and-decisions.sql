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

