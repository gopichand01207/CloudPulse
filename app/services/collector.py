"""
MetricCollector service — gathers real (psutil) and simulated server metrics.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import psutil
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.metrics import ServerMetric, ServerStatus
from app.services.alert_engine import AlertEngine

logger = structlog.get_logger(__name__)

# Simulated server definitions (static seed so values are reproducible per cycle)
_SIMULATED_SERVERS: list[dict] = [
    {
        "server_id": "i-0a1b2c3d4e5f60001",
        "server_name": "web-server-01",
        "region": "us-east-1",
        "instance_type": "t3.medium",
        "base_cpu": 45.0,
        "base_mem": 60.0,
        "base_disk": 55.0,
    },
    {
        "server_id": "i-0a1b2c3d4e5f60002",
        "server_name": "web-server-02",
        "region": "us-east-1",
        "instance_type": "t3.medium",
        "base_cpu": 38.0,
        "base_mem": 52.0,
        "base_disk": 48.0,
    },
    {
        "server_id": "i-0a1b2c3d4e5f60003",
        "server_name": "web-server-03",
        "region": "us-west-2",
        "instance_type": "t3.large",
        "base_cpu": 72.0,
        "base_mem": 78.0,
        "base_disk": 62.0,
    },
    {
        "server_id": "i-0a1b2c3d4e5f60004",
        "server_name": "web-server-04",
        "region": "eu-west-1",
        "instance_type": "t3.small",
        "base_cpu": 25.0,
        "base_mem": 40.0,
        "base_disk": 35.0,
    },
    {
        "server_id": "i-0a1b2c3d4e5f60010",
        "server_name": "db-server-01",
        "region": "us-east-1",
        "instance_type": "r5.xlarge",
        "base_cpu": 55.0,
        "base_mem": 85.0,
        "base_disk": 78.0,
    },
    {
        "server_id": "i-0a1b2c3d4e5f60020",
        "server_name": "cache-server-01",
        "region": "us-east-1",
        "instance_type": "r6g.medium",
        "base_cpu": 15.0,
        "base_mem": 70.0,
        "base_disk": 20.0,
    },
]

_JITTER = 15.0  # ±% jitter applied to base values


def _jitter(base: float, seed: int) -> float:
    """Apply deterministic jitter to a base metric value."""
    rng = random.Random(seed)
    delta = rng.uniform(-_JITTER, _JITTER)
    return max(0.0, min(100.0, base + delta))


class MetricCollector:
    """Responsible for collecting, simulating, and persisting server metrics."""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def collect_all_server_metrics(self) -> None:
        """Collect metrics for all servers (real + simulated) and persist them."""
        async with SessionLocal() as session:
            metrics = await self.collect_system_metrics()
            simulated = self.get_simulated_servers()
            all_metrics = metrics + simulated

            saved = await self.save_metrics_to_db(session, all_metrics)
            await session.commit()

            # Evaluate alerts for each saved metric
            engine = AlertEngine()
            for metric_obj in saved:
                await engine.evaluate_metrics(session, metric_obj)

            await session.commit()
            logger.info("metrics_collected", count=len(saved))

    # ------------------------------------------------------------------
    # Real system metrics (local host via psutil)
    # ------------------------------------------------------------------

    async def collect_system_metrics(self) -> list[dict]:
        """Collect metrics for the local host using psutil."""
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent

        net = psutil.net_io_counters()
        net_in = net.bytes_recv / 1024 / 1024  # MB
        net_out = net.bytes_sent / 1024 / 1024

        return [
            {
                "server_id": "local-host",
                "server_name": "local-host",
                "cpu_usage": cpu,
                "memory_usage": mem,
                "disk_usage": disk,
                "network_in": net_in,
                "network_out": net_out,
                "region": "local",
                "instance_type": "bare-metal",
                "status": ServerStatus.RUNNING,
                "timestamp": datetime.now(tz=timezone.utc),
            }
        ]

    # ------------------------------------------------------------------
    # Simulated servers
    # ------------------------------------------------------------------

    def get_simulated_servers(self) -> list[dict]:
        """Return a list of realistic mock metrics for simulated AWS EC2 instances."""
        now = datetime.now(tz=timezone.utc)
        # Use minute-level epoch as seed so values are consistent per cycle
        seed_base = int(now.timestamp()) // 60

        results: list[dict] = []
        for i, srv in enumerate(_SIMULATED_SERVERS):
            seed = seed_base + i * 100
            rng = random.Random(seed)
            results.append(
                {
                    "server_id": srv["server_id"],
                    "server_name": srv["server_name"],
                    "cpu_usage": _jitter(srv["base_cpu"], seed),
                    "memory_usage": _jitter(srv["base_mem"], seed + 1),
                    "disk_usage": _jitter(srv["base_disk"], seed + 2),
                    "network_in": rng.uniform(10.0, 500.0),
                    "network_out": rng.uniform(5.0, 300.0),
                    "region": srv["region"],
                    "instance_type": srv["instance_type"],
                    "status": ServerStatus.RUNNING,
                    "timestamp": now,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save_metrics_to_db(
        self, session: AsyncSession, metrics: list[dict]
    ) -> list[ServerMetric]:
        """Bulk-insert ServerMetric records and return the saved ORM objects."""
        objects: list[ServerMetric] = []
        for m in metrics:
            obj = ServerMetric(
                server_id=m["server_id"],
                server_name=m["server_name"],
                cpu_usage=round(m["cpu_usage"], 2),
                memory_usage=round(m["memory_usage"], 2),
                disk_usage=round(m["disk_usage"], 2),
                network_in=round(m.get("network_in", 0.0), 4),
                network_out=round(m.get("network_out", 0.0), 4),
                region=m.get("region", "us-east-1"),
                instance_type=m.get("instance_type", "t3.medium"),
                status=m.get("status", ServerStatus.RUNNING),
                timestamp=m.get("timestamp", datetime.now(tz=timezone.utc)),
            )
            session.add(obj)
            objects.append(obj)

        await session.flush()  # Assign IDs without committing
        # Refresh all to populate server-generated fields
        for obj in objects:
            await session.refresh(obj)

        logger.debug("metrics_persisted", count=len(objects))
        return objects

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_latest_metric(
        self, session: AsyncSession, server_id: str
    ) -> ServerMetric | None:
        """Return the most recent metric snapshot for a given server."""
        result = await session.execute(
            select(ServerMetric)
            .where(ServerMetric.server_id == server_id)
            .order_by(ServerMetric.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
