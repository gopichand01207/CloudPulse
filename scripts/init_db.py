#!/usr/bin/env python3
"""
CloudPulse — Database Initialisation Script
============================================
Connects to PostgreSQL, runs the initial migration SQL, and seeds the
database with realistic server records, alert events, and service-health
entries suitable for demonstration and load testing.

Usage:
    python scripts/init_db.py

Environment variables (or .env file):
    DATABASE_URL — asyncpg DSN, e.g.
        postgresql+asyncpg://cloudpulse:password@localhost:5432/cloudpulse
"""

import asyncio
import os
import pathlib
import random
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

try:
    import asyncpg
except ImportError:
    sys.exit("asyncpg is not installed. Run: pip install asyncpg")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; fall back to real env vars


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(tz=timezone.utc)

def _dsn() -> str:
    """Return a raw asyncpg DSN (strip the SQLAlchemy dialect prefix)."""
    url = os.getenv("DATABASE_URL", "postgresql+asyncpg://cloudpulse:cloudpulse_secret@localhost:5432/cloudpulse")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m  {msg}")


def _err(msg: str, exc: Exception) -> None:
    print(f"  \033[31m✗\033[0m  {msg}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

async def run_migration(conn: asyncpg.Connection) -> None:
    sql_path = pathlib.Path(__file__).parent.parent / "db" / "migrations" / "001_initial_schema.sql"
    if not sql_path.exists():
        raise FileNotFoundError(f"Migration file not found: {sql_path}")
    sql = sql_path.read_text(encoding="utf-8")
    await conn.execute(sql)
    _ok(f"Migration applied: {sql_path.name}")


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SERVERS = [
    {"server_id": "srv-web-01",  "hostname": "web-server-01.cloudpulse.internal",  "ip": "10.0.1.10", "region": "us-east-1", "az": "us-east-1a"},
    {"server_id": "srv-web-02",  "hostname": "web-server-02.cloudpulse.internal",  "ip": "10.0.1.11", "region": "us-east-1", "az": "us-east-1b"},
    {"server_id": "srv-web-03",  "hostname": "web-server-03.cloudpulse.internal",  "ip": "10.0.2.10", "region": "us-east-1", "az": "us-east-1a"},
    {"server_id": "srv-api-01",  "hostname": "api-server-01.cloudpulse.internal",  "ip": "10.0.3.20", "region": "us-east-1", "az": "us-east-1a"},
    {"server_id": "srv-api-02",  "hostname": "api-server-02.cloudpulse.internal",  "ip": "10.0.3.21", "region": "us-east-1", "az": "us-east-1b"},
    {"server_id": "srv-db-01",   "hostname": "db-server-01.cloudpulse.internal",   "ip": "10.0.4.30", "region": "us-east-1", "az": "us-east-1a"},
]

SERVICES = [
    ("CloudPulse API",        "http://cloudpulse-api:8000/health"),
    ("PostgreSQL",            "postgresql://postgres:5432"),
    ("Redis Cache",           "redis://redis:6379"),
    ("Prometheus",            "http://prometheus:9090/-/healthy"),
    ("Grafana",               "http://grafana:3000/api/health"),
    ("Alertmanager",          "http://alertmanager:9093/-/healthy"),
]


async def seed_server_metrics(conn: asyncpg.Connection) -> None:
    """Insert 10 metric snapshots per server (last 5 minutes, every 30 s)."""
    rows: list[dict[str, Any]] = []
    for srv in SERVERS:
        base_cpu = random.uniform(10, 75)
        base_mem = random.uniform(30, 80)
        for i in range(10):
            ts = NOW - timedelta(seconds=i * 30)
            cpu = min(100, base_cpu + random.uniform(-5, 5))
            mem = min(100, base_mem + random.uniform(-3, 3))
            disk = random.uniform(20, 65)
            mem_total = 16384
            mem_used = int(mem_total * mem / 100)
            rows.append({
                "id":                   str(uuid.uuid4()),
                "server_id":            srv["server_id"],
                "hostname":             srv["hostname"],
                "ip_address":           srv["ip"],
                "cloud_provider":       "aws",
                "region":               srv["region"],
                "availability_zone":    srv["az"],
                "cpu_usage_percent":    round(cpu, 2),
                "cpu_count":            4,
                "load_avg_1m":          round(cpu / 100 * 4, 2),
                "load_avg_5m":          round(cpu / 100 * 3.8, 2),
                "load_avg_15m":         round(cpu / 100 * 3.5, 2),
                "memory_total_mb":      mem_total,
                "memory_used_mb":       mem_used,
                "memory_free_mb":       mem_total - mem_used,
                "memory_usage_percent": round(mem, 2),
                "swap_total_mb":        4096,
                "swap_used_mb":         random.randint(0, 512),
                "disk_total_gb":        round(random.uniform(100, 500), 2),
                "disk_used_gb":         round(disk * 2, 2),
                "disk_free_gb":         round((100 - disk) * 2, 2),
                "disk_usage_percent":   round(disk, 2),
                "disk_read_mb_s":       round(random.uniform(0, 50), 2),
                "disk_write_mb_s":      round(random.uniform(0, 20), 2),
                "network_in_mb_s":      round(random.uniform(1, 100), 2),
                "network_out_mb_s":     round(random.uniform(0.5, 50), 2),
                "network_in_packets":   random.randint(1000, 100000),
                "network_out_packets":  random.randint(500, 80000),
                "network_errors":       random.randint(0, 5),
                "process_count":        random.randint(80, 300),
                "uptime_seconds":       random.randint(86400, 2592000),
                "collected_at":         ts,
                "created_at":           ts,
            })

    await conn.executemany(
        """
        INSERT INTO server_metrics (
            id, server_id, hostname, ip_address, cloud_provider, region, availability_zone,
            cpu_usage_percent, cpu_count, load_avg_1m, load_avg_5m, load_avg_15m,
            memory_total_mb, memory_used_mb, memory_free_mb, memory_usage_percent,
            swap_total_mb, swap_used_mb,
            disk_total_gb, disk_used_gb, disk_free_gb, disk_usage_percent,
            disk_read_mb_s, disk_write_mb_s,
            network_in_mb_s, network_out_mb_s, network_in_packets, network_out_packets,
            network_errors, process_count, uptime_seconds, collected_at, created_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, $10, $11, $12,
            $13, $14, $15, $16,
            $17, $18,
            $19, $20, $21, $22,
            $23, $24,
            $25, $26, $27, $28,
            $29, $30, $31, $32, $33
        ) ON CONFLICT DO NOTHING
        """,
        [
            (
                r["id"], r["server_id"], r["hostname"], r["ip_address"],
                r["cloud_provider"], r["region"], r["availability_zone"],
                r["cpu_usage_percent"], r["cpu_count"],
                r["load_avg_1m"], r["load_avg_5m"], r["load_avg_15m"],
                r["memory_total_mb"], r["memory_used_mb"], r["memory_free_mb"],
                r["memory_usage_percent"], r["swap_total_mb"], r["swap_used_mb"],
                r["disk_total_gb"], r["disk_used_gb"], r["disk_free_gb"],
                r["disk_usage_percent"], r["disk_read_mb_s"], r["disk_write_mb_s"],
                r["network_in_mb_s"], r["network_out_mb_s"],
                r["network_in_packets"], r["network_out_packets"],
                r["network_errors"], r["process_count"], r["uptime_seconds"],
                r["collected_at"], r["created_at"],
            )
            for r in rows
        ],
    )
    _ok(f"Seeded {len(rows)} server_metrics rows ({len(SERVERS)} servers × 10 snapshots)")


async def seed_alert_events(conn: asyncpg.Connection) -> None:
    """Insert sample alert events covering open, acknowledged, and resolved states."""
    alerts = [
        {
            "id":              str(uuid.uuid4()),
            "server_id":       "srv-web-01",
            "alert_name":      "HighCPUUsage",
            "severity":        "critical",
            "status":          "open",
            "title":           "High CPU usage on srv-web-01",
            "description":     "CPU usage has exceeded 85% for more than 2 minutes.",
            "metric_value":    91.4,
            "threshold_value": 85.0,
            "unit":            "percent",
            "labels":          '{"team": "ops", "environment": "production"}',
            "annotations":     '{"runbook": "https://wiki.example.com/runbooks/high-cpu"}',
            "fired_at":        NOW - timedelta(minutes=10),
        },
        {
            "id":              str(uuid.uuid4()),
            "server_id":       "srv-db-01",
            "alert_name":      "HighMemoryUsage",
            "severity":        "critical",
            "status":          "acknowledged",
            "title":           "High memory usage on srv-db-01",
            "description":     "Memory usage exceeded 90% for 2 minutes.",
            "metric_value":    93.1,
            "threshold_value": 90.0,
            "unit":            "percent",
            "labels":          '{"team": "dba", "environment": "production"}',
            "annotations":     '{"runbook": "https://wiki.example.com/runbooks/high-memory"}',
            "fired_at":        NOW - timedelta(hours=1),
        },
        {
            "id":              str(uuid.uuid4()),
            "server_id":       "srv-api-01",
            "alert_name":      "SlowResponseTime",
            "severity":        "warning",
            "status":          "resolved",
            "title":           "Slow API response time on srv-api-01",
            "description":     "p95 response time exceeded 2000 ms.",
            "metric_value":    2340.5,
            "threshold_value": 2000.0,
            "unit":            "ms",
            "labels":          '{"team": "dev", "environment": "production"}',
            "annotations":     '{"runbook": "https://wiki.example.com/runbooks/slow-api"}',
            "fired_at":        NOW - timedelta(hours=3),
        },
        {
            "id":              str(uuid.uuid4()),
            "server_id":       "srv-web-02",
            "alert_name":      "HighDiskUsage",
            "severity":        "warning",
            "status":          "open",
            "title":           "High disk usage on srv-web-02",
            "description":     "Disk usage at / exceeded 85%.",
            "metric_value":    87.3,
            "threshold_value": 85.0,
            "unit":            "percent",
            "labels":          '{"team": "ops", "environment": "production"}',
            "annotations":     '{}',
            "fired_at":        NOW - timedelta(minutes=25),
        },
        {
            "id":              str(uuid.uuid4()),
            "server_id":       "srv-api-02",
            "alert_name":      "APIHighErrorRate",
            "severity":        "critical",
            "status":          "open",
            "title":           "High HTTP 5xx error rate on srv-api-02",
            "description":     "More than 10% of requests are returning 5xx errors.",
            "metric_value":    0.14,
            "threshold_value": 0.10,
            "unit":            "ratio",
            "labels":          '{"team": "dev", "environment": "production"}',
            "annotations":     '{"runbook": "https://wiki.example.com/runbooks/high-error-rate"}',
            "fired_at":        NOW - timedelta(minutes=5),
        },
    ]

    await conn.executemany(
        """
        INSERT INTO alert_events (
            id, server_id, alert_name, severity, status,
            title, description, metric_value, threshold_value, unit,
            labels, annotations, fired_at, created_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11::jsonb, $12::jsonb, $13, $13
        ) ON CONFLICT DO NOTHING
        """,
        [
            (
                a["id"], a["server_id"], a["alert_name"], a["severity"], a["status"],
                a["title"], a["description"], a["metric_value"], a["threshold_value"], a["unit"],
                a["labels"], a["annotations"], a["fired_at"],
            )
            for a in alerts
        ],
    )
    _ok(f"Seeded {len(alerts)} alert_events rows")


async def seed_service_health(conn: asyncpg.Connection) -> None:
    """Insert current health check entries for every monitored service."""
    statuses = ["healthy", "healthy", "healthy", "degraded", "healthy", "healthy"]
    rows = []
    for (name, url), status in zip(SERVICES, statuses):
        rows.append((
            str(uuid.uuid4()),
            name,
            url,
            "srv-web-01",
            status,
            200 if status == "healthy" else 503,
            random.randint(5, 150) if status == "healthy" else random.randint(2000, 5000),
            None if status == "healthy" else "Connection timeout after 5000 ms",
            0 if status == "healthy" else random.randint(1, 3),
            NOW if status == "healthy" else None,
            None if status == "healthy" else NOW - timedelta(minutes=2),
            NOW,
        ))

    await conn.executemany(
        """
        INSERT INTO service_health (
            id, service_name, endpoint_url, server_id, status,
            http_status_code, response_time_ms, error_message,
            consecutive_failures, last_success_at, last_failure_at, checked_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (service_name, endpoint_url) DO UPDATE SET
            status               = EXCLUDED.status,
            http_status_code     = EXCLUDED.http_status_code,
            response_time_ms     = EXCLUDED.response_time_ms,
            error_message        = EXCLUDED.error_message,
            consecutive_failures = EXCLUDED.consecutive_failures,
            last_success_at      = EXCLUDED.last_success_at,
            last_failure_at      = EXCLUDED.last_failure_at,
            checked_at           = EXCLUDED.checked_at,
            updated_at           = NOW()
        """,
        rows,
    )
    _ok(f"Seeded {len(rows)} service_health rows")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("\n🚀  CloudPulse Database Initialisation\n" + "─" * 42)
    dsn = _dsn()
    print(f"  Connecting to: {dsn.split('@')[-1]}")

    try:
        conn = await asyncpg.connect(dsn)
    except Exception as exc:
        _err("Failed to connect", exc)
        sys.exit(1)

    try:
        # 1. Run migration
        print("\n[1/4] Applying migration …")
        try:
            await run_migration(conn)
        except asyncpg.PostgresError as exc:
            if "already exists" in str(exc):
                _ok("Schema already exists — skipping migration")
            else:
                raise

        # 2. Seed server metrics
        print("\n[2/4] Seeding server_metrics …")
        try:
            await seed_server_metrics(conn)
        except Exception as exc:
            _err("seed_server_metrics", exc)

        # 3. Seed alert events
        print("\n[3/4] Seeding alert_events …")
        try:
            await seed_alert_events(conn)
        except Exception as exc:
            _err("seed_alert_events", exc)

        # 4. Seed service health
        print("\n[4/4] Seeding service_health …")
        try:
            await seed_service_health(conn)
        except Exception as exc:
            _err("seed_service_health", exc)

    finally:
        await conn.close()

    print("\n\033[32m✓  Database initialisation complete.\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())
