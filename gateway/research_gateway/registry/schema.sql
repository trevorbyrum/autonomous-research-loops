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
CREATE INDEX IF NOT EXISTS calls_source_at_idx ON gateway.calls (source_id, at DESC);

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

-- Tier 0 local index over harvested registries (Phase 6).
CREATE TABLE IF NOT EXISTS gateway.index_docs (
  identity  text PRIMARY KEY,
  kind      text NOT NULL,
  domain    text,
  year      integer,
  tsv       tsvector NOT NULL
);
CREATE INDEX IF NOT EXISTS index_docs_tsv_idx ON gateway.index_docs USING gin (tsv);
