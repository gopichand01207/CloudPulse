#!/usr/bin/env python3
"""
CloudPulse — Load Simulation Script
=====================================
Continuously sends realistic metric payloads, log batches, and controlled
CPU/memory spikes to the CloudPulse API, exercising the full ingest pipeline
and triggering alert rules for end-to-end demonstration.

Usage:
    python scripts/simulate_load.py [--duration 3600] [--api-url http://localhost:8000]

Options:
    --duration      Total seconds to run (default: 3600, 0 = run forever)
    --api-url       Base URL of the CloudPulse API (default: http://localhost:8000)
    --interval      Seconds between regular metric sends (default: 30)
    --spike-every   Seconds between CPU/memory spikes (default: 300)
    --verbose       Print every request/response
"""

import argparse
import json
import math
import random
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    import requests
    from requests.adapters import HTTPAdapter, Retry
except ImportError:
    sys.exit("requests is not installed.  Run: pip install requests")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SERVERS = [
    {"server_id": "srv-web-01", "hostname": "web-server-01.cloudpulse.internal", "ip": "10.0.1.10"},
    {"server_id": "srv-web-02", "hostname": "web-server-02.cloudpulse.internal", "ip": "10.0.1.11"},
    {"server_id": "srv-web-03", "hostname": "web-server-03.cloudpulse.internal", "ip": "10.0.2.10"},
    {"server_id": "srv-api-01", "hostname": "api-server-01.cloudpulse.internal", "ip": "10.0.3.20"},
    {"server_id": "srv-api-02", "hostname": "api-server-02.cloudpulse.internal", "ip": "10.0.3.21"},
    {"server_id": "srv-db-01",  "hostname": "db-server-01.cloudpulse.internal",  "ip": "10.0.4.30"},
]

LOG_MESSAGES = [
    ("INFO",    "Request processed successfully",           "app.api.router"),
    ("INFO",    "Cache hit for key metrics:{}",             "app.cache"),
    ("INFO",    "Database query completed in {} ms",        "app.db"),
    ("WARNING", "Slow query detected: {} ms",               "app.db"),
    ("WARNING", "Redis connection pool at {} % capacity",   "app.cache"),
    ("ERROR",   "Unhandled exception in endpoint /metrics", "app.api.metrics"),
    ("ERROR",   "Database connection timeout after 5000 ms","app.db"),
    ("CRITICAL","OOM killer invoked — process terminated",  "app.system"),
    ("DEBUG",   "Collected {} metrics for server {}",       "app.collector"),
    ("INFO",    "Health check passed for {}",               "app.health"),
]

SERVICES = [
    "cloudpulse-api",
    "postgres",
    "redis",
    "prometheus",
    "grafana",
    "alertmanager",
]

# Track per-server baseline to drift it slowly
_baselines: dict[str, dict[str, float]] = {
    srv["server_id"]: {
        "cpu":    random.uniform(15, 60),
        "memory": random.uniform(30, 70),
        "disk":   random.uniform(20, 60),
    }
    for srv in SERVERS
}

# Running flag for clean shutdown
_running = True


def _handle_signal(sig: int, frame: Any) -> None:
    global _running
    print("\n\n⚡  Signal received — shutting down gracefully …\n")
    _running = False


signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# HTTP session with retry
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://",  adapter)
    session.mount("https://", adapter)
    session.headers.update({"Content-Type": "application/json", "X-Simulator": "cloudpulse-load-sim"})
    return session


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _drift(value: float, lo: float, hi: float, noise: float = 3.0) -> float:
    """Random-walk a value within [lo, hi]."""
    return max(lo, min(hi, value + random.gauss(0, noise)))


def build_metrics_payload(spike_server_id: str | None = None) -> dict:
    """Build the POST body for /api/v1/metrics/collect."""
    servers_data = []
    for srv in SERVERS:
        sid = srv["server_id"]
        b = _baselines[sid]

        # Drift baselines slowly
        b["cpu"]    = _drift(b["cpu"],    5,  95, noise=2)
        b["memory"] = _drift(b["memory"], 10, 95, noise=1.5)
        b["disk"]   = _drift(b["disk"],   5,  90, noise=0.3)

        cpu    = b["cpu"]
        memory = b["memory"]
        disk   = b["disk"]

        # Apply spike if this server is chosen
        if sid == spike_server_id:
            cpu    = random.uniform(88, 98)
            memory = random.uniform(91, 97)

        mem_total = 16384
        mem_used  = int(mem_total * memory / 100)

        servers_data.append({
            "server_id":           sid,
            "hostname":            srv["hostname"],
            "ip_address":          srv["ip"],
            "cloud_provider":      "aws",
            "region":              "us-east-1",
            "availability_zone":   "us-east-1a",
            "cpu_usage_percent":   round(cpu, 2),
            "cpu_count":           4,
            "load_avg_1m":         round(cpu / 100 * 4, 2),
            "load_avg_5m":         round(cpu / 100 * 3.8, 2),
            "load_avg_15m":        round(cpu / 100 * 3.5, 2),
            "memory_total_mb":     mem_total,
            "memory_used_mb":      mem_used,
            "memory_free_mb":      mem_total - mem_used,
            "memory_usage_percent": round(memory, 2),
            "swap_total_mb":       4096,
            "swap_used_mb":        random.randint(0, 1024),
            "disk_total_gb":       200,
            "disk_used_gb":        round(disk * 2, 2),
            "disk_free_gb":        round((100 - disk) * 2, 2),
            "disk_usage_percent":  round(disk, 2),
            "disk_read_mb_s":      round(random.uniform(0, 60), 2),
            "disk_write_mb_s":     round(random.uniform(0, 25), 2),
            "network_in_mb_s":     round(random.uniform(1, 120), 2),
            "network_out_mb_s":    round(random.uniform(0.5, 60), 2),
            "network_in_packets":  random.randint(1000, 100000),
            "network_out_packets": random.randint(500,  80000),
            "network_errors":      random.randint(0, 3),
            "process_count":       random.randint(80, 350),
            "uptime_seconds":      random.randint(86400, 2592000),
            "collected_at":        _now_iso(),
        })

    return {"servers": servers_data, "collected_at": _now_iso()}


def build_log_batch(count: int = 20) -> dict:
    """Build the POST body for /api/v1/logs/ingest."""
    entries = []
    for _ in range(count):
        srv      = random.choice(SERVERS)
        level, tmpl, logger = random.choice(LOG_MESSAGES)
        args = [random.randint(10, 5000) if "{}" in tmpl else ""]
        message  = tmpl.format(*args) if "{}" in tmpl else tmpl
        entries.append({
            "server_id":  srv["server_id"],
            "service":    random.choice(SERVICES),
            "log_level":  level,
            "message":    message,
            "logger":     logger,
            "trace_id":   str(uuid.uuid4()) if random.random() > 0.5 else None,
            "extra":      {"pid": random.randint(1, 32000)},
            "timestamp":  _now_iso(),
        })
    return {"entries": entries}


def build_service_health_payload() -> list[dict]:
    """Build the POST body for /api/v1/services/health."""
    statuses = []
    for name in SERVICES:
        ok = random.random() > 0.05  # 5 % chance of degraded
        statuses.append({
            "service_name":    name,
            "endpoint_url":    f"http://{name}:8000/health",
            "status":          "healthy" if ok else "degraded",
            "http_status_code": 200 if ok else 503,
            "response_time_ms": random.randint(5, 150) if ok else random.randint(2000, 5000),
            "checked_at":      _now_iso(),
        })
    return statuses


# ---------------------------------------------------------------------------
# Stats tracker
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self) -> None:
        self.total_requests   = 0
        self.successful       = 0
        self.failed           = 0
        self.spikes_triggered = 0
        self.start_time       = time.time()

    def elapsed(self) -> str:
        s = int(time.time() - self.start_time)
        return f"{s // 3600:02d}h {(s % 3600) // 60:02d}m {s % 60:02d}s"

    def print_line(self, spike_server: str | None = None) -> None:
        bar_width = 20
        ok_pct = (self.successful / max(self.total_requests, 1)) * 100
        filled  = math.floor(ok_pct / 100 * bar_width)
        bar     = "█" * filled + "░" * (bar_width - filled)
        spike_info = f"  ⚡ spike → {spike_server}" if spike_server else ""
        print(
            f"\r  [{bar}] {ok_pct:5.1f}% ok  |"
            f"  total={self.total_requests}  ok={self.successful}  err={self.failed}"
            f"  spikes={self.spikes_triggered}  elapsed={self.elapsed()}{spike_info}          ",
            end="",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _post(session: requests.Session, url: str, payload: Any, stats: Stats, verbose: bool) -> bool:
    stats.total_requests += 1
    try:
        resp = session.post(url, data=json.dumps(payload, default=str), timeout=10)
        resp.raise_for_status()
        stats.successful += 1
        if verbose:
            print(f"\n  POST {url} → {resp.status_code} ({resp.elapsed.total_seconds()*1000:.0f} ms)")
        return True
    except requests.RequestException as exc:
        stats.failed += 1
        if verbose:
            print(f"\n  POST {url} → ERROR: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(api_url: str, duration: int, interval: int, spike_every: int, verbose: bool) -> None:
    session     = _build_session()
    stats       = Stats()
    last_spike  = time.time() - spike_every  # trigger spike soon after start
    deadline    = time.time() + duration if duration > 0 else float("inf")

    print(f"\n🔥  CloudPulse Load Simulator")
    print(f"    API URL  : {api_url}")
    print(f"    Duration : {'∞' if duration == 0 else f'{duration} s'}")
    print(f"    Interval : {interval} s   │   Spike every: {spike_every} s")
    print(f"    Servers  : {len(SERVERS)}")
    print("\n  Press Ctrl+C to stop.\n")

    while _running and time.time() < deadline:
        loop_start = time.time()

        # ── Spike decision ────────────────────────────────────────────────
        spike_server: str | None = None
        if time.time() - last_spike >= spike_every:
            spike_server = random.choice(SERVERS)["server_id"]
            stats.spikes_triggered += 1
            last_spike = time.time()

        # ── POST metrics ──────────────────────────────────────────────────
        metrics_payload = build_metrics_payload(spike_server_id=spike_server)
        _post(session, f"{api_url}/api/v1/metrics/collect", metrics_payload, stats, verbose)

        # ── POST logs (every other cycle) ─────────────────────────────────
        if stats.total_requests % 2 == 0:
            log_payload = build_log_batch(count=random.randint(10, 30))
            _post(session, f"{api_url}/api/v1/logs/ingest", log_payload, stats, verbose)

        # ── POST service health (every 3rd cycle) ─────────────────────────
        if stats.total_requests % 3 == 0:
            health_payload = build_service_health_payload()
            _post(session, f"{api_url}/api/v1/services/health", health_payload, stats, verbose)

        stats.print_line(spike_server)

        # ── Sleep remainder of interval ───────────────────────────────────
        elapsed = time.time() - loop_start
        sleep_for = max(0.0, interval - elapsed)
        # Sleep in 0.5-s chunks so SIGINT is responsive
        for _ in range(int(sleep_for / 0.5)):
            if not _running:
                break
            time.sleep(0.5)

    print(f"\n\n✅  Simulation complete.")
    print(f"    Total requests : {stats.total_requests}")
    print(f"    Successful     : {stats.successful}")
    print(f"    Failed         : {stats.failed}")
    print(f"    Spikes fired   : {stats.spikes_triggered}")
    print(f"    Duration       : {stats.elapsed()}\n")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CloudPulse load simulation script",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--api-url",    default="http://localhost:8000", help="Base URL of the CloudPulse API")
    parser.add_argument("--duration",   type=int, default=3600,          help="Total runtime in seconds (0 = infinite)")
    parser.add_argument("--interval",   type=int, default=30,            help="Seconds between metric POSTs")
    parser.add_argument("--spike-every",type=int, default=300,           help="Seconds between CPU/memory spikes")
    parser.add_argument("--verbose",    action="store_true",             help="Print every request/response")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        api_url    = args.api_url.rstrip("/"),
        duration   = args.duration,
        interval   = args.interval,
        spike_every= args.spike_every,
        verbose    = args.verbose,
    )
