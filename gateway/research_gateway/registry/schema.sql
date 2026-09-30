-- Research gateway schema (PLAN.md §2). Additive-only migrations in v1.
-- Applied by: python -m research_gateway.registry.load --schema

CREATE SCHEMA IF NOT EXISTS gateway;

-- What exists, what it can do, and under what terms. Mirrors seed/sources.toml.
CREATE TABLE IF NOT EXISTS gateway.sources (
  id                 text PRIMARY KEY,
  name               text NOT NULL,
  kind               text NOT NULL,           -- article | dataset | citation | resolver | statistical | manual
  homepage           text,
  docs_url           text,
  capabilities       text[] NOT NULL,         -- subset of find|resolve|enrich|fetch|data
  identifiers        text[] NOT NULL DEFAULT '{}',  -- doi|issn|arxiv|handle|title|series
  base_for           text[] NOT NULL DEFAULT '{}',  -- kinds this source is a base lane for
  domains            text[] NOT NULL DEFAULT '{}',  -- domain tags that ADD this lane
  auth               text NOT NULL,           -- none | email | key | optional_token | client_credentials | username_key | account
  secret_ref         text,                    -- logical secret name only; never a value or a path
  key_instructions   text,
  license            text,
  use_commercial     text NOT NULL,           -- allow | per-item | deny | unknown
  use_evidence       text,
  freshness_lag      text,
  substitution_group text,
  enabled            boolean NOT NULL DEFAULT false,
  notes              text,
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- Documented limits; a source without a row is never scheduled (I-3).
CREATE TABLE IF NOT EXISTS gateway.rate_policies (
  source_id        text PRIMARY KEY REFERENCES gateway.sources(id) ON DELETE CASCADE,
  per_second       numeric,
  per_minute       numeric,
  per_hour         numeric,
  per_day          numeric,
  cost_cap_per_day numeric,
  burst            integer,
  verified         boolean NOT NULL DEFAULT false,   -- true once observed from headers/docs in Phase 3
  evidence         text
);

-- Job queue (Phase 2 fills it; defined now so the schema is complete).
CREATE TABLE IF NOT EXISTS gateway.jobs (
  id            bigserial PRIMARY KEY,
  request_type  text NOT NULL,                -- find | resolve | enrich | fetch | data
  payload       jsonb NOT NULL,
  payload_hash  text NOT NULL,
  priority      smallint NOT NULL DEFAULT 5,  -- lower runs first: 1 interactive, 5 enrichment, 9 harvest
  status        text NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
  client_id     text NOT NULL,
  topic_id      text,
  commercial    boolean NOT NULL DEFAULT false,
  attempts      integer NOT NULL DEFAULT 0,
  claim_token   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  started_at    timestamptz,
  finished_at   timestamptz,
  result        jsonb,
  error_class   text
);
CREATE INDEX IF NOT EXISTS jobs_queued_idx ON gateway.jobs (status, priority, created_at) WHERE status = 'queued';
CREATE UNIQUE INDEX IF NOT EXISTS jobs_inflight_idx ON gateway.jobs (request_type, payload_hash) WHERE status IN ('queued','running');

-- Every outbound call (I-6).
CREATE TABLE IF NOT EXISTS gateway.calls (
  id             bigserial PRIMARY KEY,
  job_id         bigint REFERENCES gateway.jobs(id) ON DELETE SET NULL,
  source_id      text NOT NULL,
  request_type   text NOT NULL,
  identity       text,
  query          text,
  status         integer,
  latency_ms     integer,
  ratelimit      jsonb,
  credits        numeric,
  cache_hit      boolean NOT NULL DEFAULT false,
  result_count   integer,
  failure_class  text,                        -- auth | quota | outage | botwall | notfound | refused | ok
  domain_resolved text,
  client_id      text,                        -- which front-door client asked (I-6)
  at             timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS client_id text;   -- databases created before Phase 5
-- Phase 9·0 tracing (D-33): correlation and span data, OUTSIDE semantic request identity —
-- these never enter payloads, cache keys or the job-dedup hash
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS wait_ms integer;      -- broker/queue wait before dispatch
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS iteration text;       -- chassis iteration stamp of the dispatching context
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS batch_entry integer;  -- research_batch entry index, when applicable
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS topic text;           -- caller's topic id (tracing; two topics can share an iteration second)
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS params_fp text;       -- request-payload fingerprint for repeat classification (never identity)
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS hop smallint;         -- redirect-hop index within one logical dispatch (0 = the request)
ALTER TABLE gateway.jobs  ADD COLUMN IF NOT EXISTS topic text;           -- creator's TRACING topic (header channel); topic_id stays the POLICY binding
ALTER TABLE gateway.jobs  ADD COLUMN IF NOT EXISTS iteration text;       -- creator's iteration (per-caller attribution on coalesce is the creator's; a coalesced waiter made no calls)
ALTER TABLE gateway.jobs  ADD COLUMN IF NOT EXISTS batch_entry integer;  -- creator's research_batch entry index (same creator's-attribution rule)
ALTER TABLE gateway.jobs ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;  -- lease reclaim (D-23)
ALTER TABLE gateway.jobs ADD COLUMN IF NOT EXISTS claim_token text;  -- claim fencing (D-24)
CREATE INDEX IF NOT EXISTS calls_source_at_idx ON gateway.calls (source_id, at DESC);
-- Task 2b correlation (INVARIANTS H-1, H-5): the caller's invocation and attempt, and the
-- identity of the complete effective request (core/request_identity.py), on every call row
-- and on each job (the creator's). Written once: the trigger below refuses any change.
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS invocation_id text;
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS attempt integer CHECK (attempt >= 1);
ALTER TABLE gateway.calls ADD COLUMN IF NOT EXISTS request_identity text;
ALTER TABLE gateway.jobs  ADD COLUMN IF NOT EXISTS invocation_id text;
ALTER TABLE gateway.jobs  ADD COLUMN IF NOT EXISTS attempt integer CHECK (attempt >= 1);
ALTER TABLE gateway.jobs  ADD COLUMN IF NOT EXISTS request_identity text;
CREATE INDEX IF NOT EXISTS calls_invocation_idx ON gateway.calls (invocation_id, attempt) WHERE invocation_id IS NOT NULL;
CREATE OR REPLACE FUNCTION gateway.correlation_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.invocation_id IS DISTINCT FROM OLD.invocation_id OR NEW.attempt IS DISTINCT FROM OLD.attempt
     OR NEW.request_identity IS DISTINCT FROM OLD.request_identity THEN
    RAISE EXCEPTION 'invocation, attempt and request identity are immutable once written (task 2b)';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS calls_correlation_immutable ON gateway.calls;
CREATE TRIGGER calls_correlation_immutable BEFORE UPDATE ON gateway.calls
  FOR EACH ROW EXECUTE FUNCTION gateway.correlation_immutable();
DROP TRIGGER IF EXISTS jobs_correlation_immutable ON gateway.jobs;
CREATE TRIGGER jobs_correlation_immutable BEFORE UPDATE ON gateway.jobs
  FOR EACH ROW EXECUTE FUNCTION gateway.correlation_immutable();

CREATE TABLE IF NOT EXISTS gateway.breakers (
  source_id    text PRIMARY KEY REFERENCES gateway.sources(id) ON DELETE CASCADE,
  state        text NOT NULL DEFAULT 'closed',  -- closed | open
  opened_at    timestamptz,
  retry_after  timestamptz,
  reason       text
);

-- One merged record per identity; never full text (I-7).
CREATE TABLE IF NOT EXISTS gateway.records (
  identity    text PRIMARY KEY,               -- e.g. doi:10.1000/xyz ; issn:1234-5678 ; series:fred:GDP
  kind        text NOT NULL,
  canonical   jsonb NOT NULL,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now()
);

-- Each contributing source's raw payload, with provenance and cache policy (I-8).
CREATE TABLE IF NOT EXISTS gateway.record_sources (
  identity        text NOT NULL REFERENCES gateway.records(identity) ON DELETE CASCADE,
  source_id       text NOT NULL,
  raw             jsonb NOT NULL,
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  license         text,
  redistributable boolean NOT NULL DEFAULT false,
  PRIMARY KEY (identity, source_id)
);

-- Task 2b: storage and redistribution are separate facts. A row here is by definition
-- storable (only storable members are persisted); `redistribution` is whether its CONTENT
-- may travel downstream, decided by its own content licence (core/licenses.py), and
-- `redistributable` is true only when that is `permitted`. Rows written before this
-- carried redistributable = true for every persisted member (it meant "storable"): with no
-- assessment they are not known to be redistributable, so they are set false.
ALTER TABLE gateway.record_sources ADD COLUMN IF NOT EXISTS redistribution text
  CHECK (redistribution IN ('permitted', 'conditional', 'prohibited', 'unknown'));
UPDATE gateway.record_sources SET redistributable = false WHERE redistribution IS NULL AND redistributable;
-- Task 2b-repair A3: the licence of the registry or source METADATA a row came with (DOAJ's
-- CC0 catalogue, a snapshot's CC0 dump) is its own column: it never stands in for `license`,
-- the record's CONTENT licence, which alone decides `redistribution`.
ALTER TABLE gateway.record_sources ADD COLUMN IF NOT EXISTS metadata_license text;
-- Task 2b-repair-2 R1, 2b-repair-4 F2: true when the row's members carry the source's own
-- statements about them — in canonical provenance (the cache's writer) or, with none there, in
-- record_sources (the harvest's). Earlier writers' rows default to false: registry/migrate.py
-- converts them once, and a gateway never opens a database that still holds one (core/cache.py).
ALTER TABLE gateway.records ADD COLUMN IF NOT EXISTS restriction_inputs boolean NOT NULL DEFAULT false;
-- Task 2b-repair-5 F2: the ONE place a stored record is read to be served — every serving read
-- and count goes through this view, never gateway.records (tests/test_record_gate.py fails on any
-- other). A row not yet converted is here withheld: its identity and kind, its canonical NULL, so
-- a reader can count what it refused and can never serve it.
CREATE OR REPLACE VIEW gateway.servable_records AS
  SELECT identity, kind, CASE WHEN restriction_inputs THEN canonical END AS canonical, last_seen
  FROM gateway.records;

-- Tier 0 local index over harvested registries (Phase 6).
CREATE TABLE IF NOT EXISTS gateway.index_docs (
  identity  text PRIMARY KEY,
  kind      text NOT NULL,
  domain    text,
  year      integer,
  tsv       tsvector NOT NULL
);
CREATE INDEX IF NOT EXISTS index_docs_tsv_idx ON gateway.index_docs USING gin (tsv);

-- Operational metadata: last successful harvest per loader, and anything else a
-- maintenance run must prove happened (partial batch commits make "last row
-- updated" insufficient evidence of a completed refresh) — Phase 8f.
CREATE TABLE IF NOT EXISTS gateway.meta (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
