-- Rederive schema. Record versions are immutable: a rebuild or correction
-- inserts a new version and flips the status of the old one.

CREATE TABLE IF NOT EXISTS recipe (
  hash      text PRIMARY KEY,
  template  text NOT NULL,
  model     text NOT NULL,
  params    jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS record (
  id              uuid NOT NULL,
  version         int  NOT NULL,
  kind            text NOT NULL,  -- observation | summary | belief | procedure
  text            text NOT NULL,
  embedding       real[],
  -- valid | stale | rebuilding | retracted | superseded | equivalent
  -- superseded: replaced by a version with different content.
  -- equivalent: replaced by a version the cutoff judged equal.
  status          text NOT NULL DEFAULT 'valid',
  recipe_hash     text NULL REFERENCES recipe(hash),
  -- Versions that the cutoff judged equal share a content_version, so a child
  -- built on any of them does not need a rebuild.
  content_version int  NOT NULL,
  meta            jsonb NOT NULL DEFAULT '{}'::jsonb,
  deleted         boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, version)
);

-- One row per record id. fence_token increments on every invalidation, so a
-- worker holding an older token knows its output is obsolete.
CREATE TABLE IF NOT EXISTS record_head (
  id              uuid PRIMARY KEY,
  latest_version  int NOT NULL,
  fence_token     bigint NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edge (
  child_id        uuid NOT NULL,
  child_version   int  NOT NULL,
  parent_id       uuid NOT NULL,
  parent_version  int  NOT NULL,
  -- alias edges point a child at a newer, equivalent parent version without
  -- rebuilding the child.
  alias           boolean NOT NULL DEFAULT false,
  -- Input order for the recipe. Rebuilds keep the order from derive time.
  position        int NOT NULL DEFAULT 0,
  PRIMARY KEY (child_id, child_version, parent_id, parent_version)
);
CREATE INDEX IF NOT EXISTS edge_parent_idx ON edge (parent_id, parent_version);

CREATE TABLE IF NOT EXISTS constraint_rule (
  id         uuid PRIMARY KEY,
  kind       text NOT NULL,  -- must_not_contain
  payload    text NOT NULL,
  source_id  uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exposure (
  tool_call_id text NOT NULL,
  tool_name    text,
  record_id    uuid NOT NULL,
  version      int  NOT NULL,
  at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS exposure_record_idx ON exposure (record_id, version);

CREATE TABLE IF NOT EXISTS rebuild_job (
  id              bigserial PRIMARY KEY,
  record_id       uuid NOT NULL,
  target_version  int  NOT NULL,
  -- queued | running | done | cut_off | skipped | discarded | failed
  state           text NOT NULL DEFAULT 'queued',
  fence_token     bigint NOT NULL,
  depth           int NOT NULL,
  result          jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz
);
CREATE INDEX IF NOT EXISTS rebuild_job_state_idx ON rebuild_job (state);

-- Verifier results per rebuilt or derived version.
CREATE TABLE IF NOT EXISTS verification (
  record_id     uuid NOT NULL,
  version       int  NOT NULL,
  constraint_id uuid NOT NULL REFERENCES constraint_rule(id),
  exact_hit     boolean NOT NULL,
  normalized_hit boolean NOT NULL,
  paraphrase_hit boolean NOT NULL,
  attempt       int NOT NULL,
  at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event (
  id      bigserial PRIMARY KEY,
  kind    text NOT NULL,  -- stale | rebuilding | rebuilt | cut_off | skipped | retracted | failed | ...
  payload jsonb NOT NULL,
  at      timestamptz NOT NULL DEFAULT now()
);
