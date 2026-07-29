-- SADMC Shield — SaaS backend schema
-- Adapted from SADMC_Shield_Architecture.md §5.2, with two additions:
--   - refresh_tokens (the doc describes opaque DB-stored refresh tokens in
--     prose but never defines a table for them)
--   - metrics.raw_metrics JSONB (stores the full ~42-key metrics dict +
--     feature_vector from every ingest call, not just the 5 summary columns)

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── TENANTS ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_name VARCHAR(255) NOT NULL,
    email             VARCHAR(255) UNIQUE NOT NULL,
    password_hash     VARCHAR(255) NOT NULL,
    subscription_plan VARCHAR(50)  DEFAULT 'free',
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);

-- ── REFRESH TOKENS (addition — not in the doc's literal DDL) ────
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,
    token_hash  VARCHAR(255) NOT NULL,  -- bcrypt hash of the opaque token
    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_tenant ON refresh_tokens(tenant_id);

-- ── API KEYS (plaintext never stored) ─────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash     VARCHAR(255) UNIQUE NOT NULL,  -- bcrypt hash
    key_prefix   VARCHAR(40)  NOT NULL,          -- for display (first ~20 chars)
    name         VARCHAR(100),                   -- user-defined label
    is_active    BOOLEAN      DEFAULT TRUE,
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);

-- ── CLUSTERS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    cluster_uuid    VARCHAR(100) UNIQUE NOT NULL,
    k8s_version     VARCHAR(20),
    node_count      INTEGER,
    agent_version   VARCHAR(20),
    status          VARCHAR(20)  DEFAULT 'active',
    last_heartbeat  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_clusters_tenant ON clusters(tenant_id);

-- ── SERVICES (dynamically updated each discovery cycle) ────────
CREATE TABLE IF NOT EXISTS services (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id   UUID REFERENCES clusters(id) ON DELETE CASCADE,
    service_name VARCHAR(255) NOT NULL,
    namespace    VARCHAR(255) NOT NULL,
    last_seen    TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(cluster_id, service_name, namespace)
);

-- ── ANOMALY EVENTS ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomaly_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id       UUID REFERENCES clusters(id) ON DELETE CASCADE,
    service_id       UUID REFERENCES services(id),
    service_name     VARCHAR(255) NOT NULL,
    namespace        VARCHAR(255) NOT NULL,
    anomaly_type     VARCHAR(50)  NOT NULL,  -- NORMAL|CPU_HOG|MEMORY_LEAK|NETWORK_DELAY
    confidence       FLOAT        NOT NULL,
    metrics_snapshot JSONB,
    "timestamp"      TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_anomaly_cluster ON anomaly_events(cluster_id, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_service ON anomaly_events(service_name, "timestamp" DESC);

-- ── REMEDIATION ACTIONS ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS remediation_actions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    anomaly_event_id UUID REFERENCES anomaly_events(id),
    cluster_id       UUID REFERENCES clusters(id),
    service_name     VARCHAR(255) NOT NULL,
    namespace        VARCHAR(255) NOT NULL,
    action_type      VARCHAR(50)  NOT NULL,  -- THROTTLE_CPU|RESTART_POD|SCALE_UP|NO_ACTION
    action_params    JSONB,
    status           VARCHAR(20)  DEFAULT 'pending',  -- pending|success|failed|skipped
    executed_at      TIMESTAMPTZ,
    duration_ms      INTEGER,
    error_message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_remediation_cluster ON remediation_actions(cluster_id, executed_at DESC);

-- ── METRICS TIME-SERIES (TimescaleDB hypertable) ─────────────────
CREATE TABLE IF NOT EXISTS metrics (
    time                  TIMESTAMPTZ NOT NULL,
    cluster_id            UUID        NOT NULL,
    service_name          VARCHAR(255) NOT NULL,
    namespace             VARCHAR(255) NOT NULL,
    cpu_usage_percent     FLOAT,
    memory_usage_mb       FLOAT,
    network_latency_ms    FLOAT,
    request_rate          FLOAT,
    error_rate            FLOAT,
    raw_metrics           JSONB   -- full ~42-key metrics dict + feature_vector
);
SELECT create_hypertable('metrics', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_metrics_cluster_service ON metrics(cluster_id, service_name, time DESC);

-- Auto-drop data older than 90 days
SELECT add_retention_policy('metrics', INTERVAL '90 days', if_not_exists => TRUE);

-- ── ROW-LEVEL SECURITY (multi-tenant isolation) ───────────────────
-- Extended from the doc's anomaly_events-only example to every
-- tenant-scoped table. app.tenant_id is SET per request/transaction
-- by the dashboard routes before querying.

-- Postgres has no "CREATE POLICY IF NOT EXISTS", so drop-then-create to
-- keep this script safely re-runnable against an existing database.

ALTER TABLE clusters ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON clusters;
CREATE POLICY tenant_isolation ON clusters
  USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

ALTER TABLE services ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON services;
CREATE POLICY tenant_isolation ON services
  USING (cluster_id IN (
    SELECT id FROM clusters WHERE tenant_id = current_setting('app.tenant_id', true)::UUID
  ));

ALTER TABLE anomaly_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON anomaly_events;
CREATE POLICY tenant_isolation ON anomaly_events
  USING (cluster_id IN (
    SELECT id FROM clusters WHERE tenant_id = current_setting('app.tenant_id', true)::UUID
  ));

ALTER TABLE remediation_actions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON remediation_actions;
CREATE POLICY tenant_isolation ON remediation_actions
  USING (cluster_id IN (
    SELECT id FROM clusters WHERE tenant_id = current_setting('app.tenant_id', true)::UUID
  ));

ALTER TABLE metrics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON metrics;
CREATE POLICY tenant_isolation ON metrics
  USING (cluster_id IN (
    SELECT id FROM clusters WHERE tenant_id = current_setting('app.tenant_id', true)::UUID
  ));

-- NOTE: RLS policies above only apply to the unprivileged app role.
-- The pool connects as the 'sadmc' superuser-equivalent owner in this
-- dev/docker-compose setup, and Postgres superusers/table owners bypass
-- RLS by default. Dashboard routes still filter by tenant_id explicitly
-- in application SQL (see services/*.js) so isolation is enforced even
-- though RLS is best-effort in this single-role dev configuration.
