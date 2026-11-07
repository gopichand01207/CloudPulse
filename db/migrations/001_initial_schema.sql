-- =============================================================================
-- CloudPulse Initial Database Schema
-- Migration: 001_initial_schema.sql
-- Description: Creates core tables, enums, indexes, and analytical views
--              for the CloudPulse infrastructure monitoring platform.
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- =============================================================================
-- ENUMS
-- =============================================================================

CREATE TYPE alert_severity   AS ENUM ('info', 'warning', 'critical');
CREATE TYPE alert_status      AS ENUM ('open', 'acknowledged', 'resolved', 'suppressed');
CREATE TYPE service_status    AS ENUM ('healthy', 'degraded', 'down', 'unknown');
CREATE TYPE log_level         AS ENUM ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL');
CREATE TYPE cloud_provider    AS ENUM ('aws', 'gcp', 'azure', 'on-premise');

-- =============================================================================
-- TABLE: server_metrics
-- Time-series metrics snapshots collected from each monitored server.
-- =============================================================================

CREATE TABLE server_metrics (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    server_id           VARCHAR(64)   NOT NULL,
    hostname            VARCHAR(255)  NOT NULL,
    ip_address          INET          NOT NULL,
    cloud_provider      cloud_provider NOT NULL DEFAULT 'aws',
    region              VARCHAR(32),
    availability_zone   VARCHAR(32),

    -- CPU
    cpu_usage_percent   NUMERIC(5, 2) NOT NULL CHECK (cpu_usage_percent BETWEEN 0 AND 100),
    cpu_count           SMALLINT      NOT NULL DEFAULT 1,
    load_avg_1m         NUMERIC(6, 2),
    load_avg_5m         NUMERIC(6, 2),
    load_avg_15m        NUMERIC(6, 2),

    -- Memory
    memory_total_mb     BIGINT        NOT NULL,
    memory_used_mb      BIGINT        NOT NULL,
    memory_free_mb      BIGINT        NOT NULL,
    memory_usage_percent NUMERIC(5, 2) NOT NULL CHECK (memory_usage_percent BETWEEN 0 AND 100),
    swap_total_mb       BIGINT        NOT NULL DEFAULT 0,
    swap_used_mb        BIGINT        NOT NULL DEFAULT 0,

    -- Disk (primary mount)
    disk_total_gb       NUMERIC(10, 2) NOT NULL,
    disk_used_gb        NUMERIC(10, 2) NOT NULL,
    disk_free_gb        NUMERIC(10, 2) NOT NULL,
    disk_usage_percent  NUMERIC(5, 2)  NOT NULL CHECK (disk_usage_percent BETWEEN 0 AND 100),
    disk_read_mb_s      NUMERIC(10, 2),
    disk_write_mb_s     NUMERIC(10, 2),

    -- Network
    network_in_mb_s     NUMERIC(10, 2),
    network_out_mb_s    NUMERIC(10, 2),
    network_in_packets  BIGINT,
    network_out_packets BIGINT,
    network_errors      INTEGER DEFAULT 0,

    -- Process / runtime
    process_count       INTEGER,
    uptime_seconds      BIGINT,

    -- Timing
    collected_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Indexes for server_metrics
CREATE INDEX idx_server_metrics_server_id         ON server_metrics (server_id);
CREATE INDEX idx_server_metrics_collected_at      ON server_metrics (collected_at DESC);
CREATE INDEX idx_server_metrics_server_collected  ON server_metrics (server_id, collected_at DESC);
CREATE INDEX idx_server_metrics_cpu_high          ON server_metrics (cpu_usage_percent) WHERE cpu_usage_percent > 80;
CREATE INDEX idx_server_metrics_memory_high       ON server_metrics (memory_usage_percent) WHERE memory_usage_percent > 80;

-- Partition hint (not enforced here — use pg_partman for high-volume deployments)
COMMENT ON TABLE server_metrics IS
    'Time-series server metric snapshots. Consider range-partitioning by collected_at for large datasets.';

-- =============================================================================
-- TABLE: alert_events
-- Records every alert triggered by the monitoring rules engine.
-- =============================================================================

CREATE TABLE alert_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    server_id       VARCHAR(64)      NOT NULL,
    metric_id       UUID             REFERENCES server_metrics(id) ON DELETE SET NULL,
    alert_name      VARCHAR(128)     NOT NULL,
    severity        alert_severity   NOT NULL,
    status          alert_status     NOT NULL DEFAULT 'open',
    title           VARCHAR(256)     NOT NULL,
    description     TEXT,
    metric_value    NUMERIC(12, 4),
    threshold_value NUMERIC(12, 4),
    unit            VARCHAR(32),
    labels          JSONB            NOT NULL DEFAULT '{}',
    annotations     JSONB            NOT NULL DEFAULT '{}',
    runbook_url     TEXT,
    acknowledged_by VARCHAR(128),
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    fired_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- Indexes for alert_events
CREATE INDEX idx_alert_events_server_id    ON alert_events (server_id);
CREATE INDEX idx_alert_events_severity     ON alert_events (severity);
CREATE INDEX idx_alert_events_status       ON alert_events (status);
CREATE INDEX idx_alert_events_fired_at     ON alert_events (fired_at DESC);
CREATE INDEX idx_alert_events_open         ON alert_events (status, fired_at DESC) WHERE status = 'open';
CREATE INDEX idx_alert_events_labels       ON alert_events USING GIN (labels);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_alert_events_updated_at
    BEFORE UPDATE ON alert_events
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- TABLE: service_health
-- Latest health check results for each monitored service endpoint.
-- =============================================================================

CREATE TABLE service_health (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name        VARCHAR(128)   NOT NULL,
    endpoint_url        TEXT           NOT NULL,
    server_id           VARCHAR(64),
    status              service_status NOT NULL DEFAULT 'unknown',
    http_status_code    SMALLINT,
    response_time_ms    INTEGER,
    error_message       TEXT,
    consecutive_failures INTEGER       NOT NULL DEFAULT 0,
    last_success_at     TIMESTAMPTZ,
    last_failure_at     TIMESTAMPTZ,
    checked_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_service_health_unique_service ON service_health (service_name, endpoint_url);
CREATE INDEX idx_service_health_status               ON service_health (status);
CREATE INDEX idx_service_health_checked_at           ON service_health (checked_at DESC);

CREATE TRIGGER trg_service_health_updated_at
    BEFORE UPDATE ON service_health
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- TABLE: log_entries
-- Structured log pipeline — application and system log ingestion.
-- =============================================================================

CREATE TABLE log_entries (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    server_id   VARCHAR(64)   NOT NULL,
    service     VARCHAR(128)  NOT NULL,
    log_level   log_level     NOT NULL,
    message     TEXT          NOT NULL,
    logger      VARCHAR(256),
    trace_id    VARCHAR(64),
    span_id     VARCHAR(32),
    extra       JSONB         NOT NULL DEFAULT '{}',
    timestamp   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    ingested_at TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Core lookup indexes
CREATE INDEX idx_log_entries_server_timestamp   ON log_entries (server_id, timestamp DESC);
CREATE INDEX idx_log_entries_level_timestamp    ON log_entries (log_level, timestamp DESC);
CREATE INDEX idx_log_entries_service            ON log_entries (service, timestamp DESC);
CREATE INDEX idx_log_entries_trace_id           ON log_entries (trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX idx_log_entries_extra              ON log_entries USING GIN (extra);

-- Partial index for high-priority logs
CREATE INDEX idx_log_entries_errors ON log_entries (timestamp DESC)
    WHERE log_level IN ('ERROR', 'CRITICAL');

COMMENT ON TABLE log_entries IS
    'Structured log entries ingested from application and OS log pipelines.';

-- =============================================================================
-- VIEW: alert_summary
-- Aggregates current alert counts by server and severity.
-- =============================================================================

CREATE VIEW alert_summary AS
SELECT
    server_id,
    COUNT(*)                                            AS total_alerts,
    COUNT(*) FILTER (WHERE severity = 'critical')       AS critical_count,
    COUNT(*) FILTER (WHERE severity = 'warning')        AS warning_count,
    COUNT(*) FILTER (WHERE severity = 'info')           AS info_count,
    COUNT(*) FILTER (WHERE status   = 'open')           AS open_count,
    COUNT(*) FILTER (WHERE status   = 'acknowledged')   AS acknowledged_count,
    MAX(fired_at)                                       AS latest_alert_at
FROM alert_events
WHERE status IN ('open', 'acknowledged')
GROUP BY server_id;

COMMENT ON VIEW alert_summary IS
    'Real-time aggregate of open and acknowledged alerts per server.';

-- =============================================================================
-- VIEW: server_health_overview
-- Joins the latest server metric snapshot with open alert counts.
-- =============================================================================

CREATE VIEW server_health_overview AS
WITH latest_metrics AS (
    SELECT DISTINCT ON (server_id)
        server_id,
        hostname,
        ip_address,
        cloud_provider,
        region,
        availability_zone,
        cpu_usage_percent,
        memory_usage_percent,
        disk_usage_percent,
        network_in_mb_s,
        network_out_mb_s,
        uptime_seconds,
        collected_at
    FROM server_metrics
    ORDER BY server_id, collected_at DESC
),
alert_counts AS (
    SELECT
        server_id,
        COUNT(*) FILTER (WHERE severity = 'critical' AND status = 'open') AS open_critical,
        COUNT(*) FILTER (WHERE severity = 'warning'  AND status = 'open') AS open_warning
    FROM alert_events
    GROUP BY server_id
),
health_status AS (
    SELECT
        service_name,
        server_id,
        status,
        response_time_ms,
        checked_at
    FROM service_health
)
SELECT
    lm.server_id,
    lm.hostname,
    lm.ip_address::TEXT,
    lm.cloud_provider,
    lm.region,
    lm.availability_zone,
    lm.cpu_usage_percent,
    lm.memory_usage_percent,
    lm.disk_usage_percent,
    lm.network_in_mb_s,
    lm.network_out_mb_s,
    lm.uptime_seconds,
    lm.collected_at                             AS last_metric_at,
    COALESCE(ac.open_critical, 0)               AS open_critical_alerts,
    COALESCE(ac.open_warning, 0)                AS open_warning_alerts,
    CASE
        WHEN COALESCE(ac.open_critical, 0) > 0  THEN 'critical'
        WHEN COALESCE(ac.open_warning, 0) > 0   THEN 'warning'
        WHEN lm.collected_at < NOW() - INTERVAL '5 minutes' THEN 'stale'
        ELSE 'healthy'
    END                                         AS overall_health
FROM latest_metrics lm
LEFT JOIN alert_counts ac USING (server_id);

COMMENT ON VIEW server_health_overview IS
    'One row per server showing the latest metrics and aggregated alert health status.';

-- =============================================================================
-- Grants (adjust roles to match your environment)
-- =============================================================================

-- Read-only role (Grafana dashboards, reporting)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cloudpulse_reader') THEN
        CREATE ROLE cloudpulse_reader NOLOGIN;
    END IF;
END $$;

GRANT CONNECT ON DATABASE cloudpulse TO cloudpulse_reader;
GRANT USAGE   ON SCHEMA public TO cloudpulse_reader;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO cloudpulse_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cloudpulse_reader;
