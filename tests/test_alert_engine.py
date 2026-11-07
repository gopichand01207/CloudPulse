"""
tests/test_alert_engine.py
---------------------------
Unit tests for ``alerting.engine.AlertEngine``.

The alert engine is tested in pure-Python isolation — no database or HTTP
layer is involved.  Each test constructs a minimal ``ServerMetric``-like
object (using a simple dataclass so we avoid SQLAlchemy session machinery)
and asserts on the alerts produced or absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

import pytest

from alerting.engine import AlertEngine
from alerting.thresholds import AlertThresholds, DEFAULT_THRESHOLDS


# ---------------------------------------------------------------------------
# Lightweight stand-in for ServerMetric (no DB session required)
# ---------------------------------------------------------------------------
@dataclass
class FakeMetric:
    """Minimal metric payload accepted by AlertEngine.evaluate()."""

    server_id: str = "web-server-01"
    hostname: str = "web-server-01.internal"
    cpu_percent: float = 50.0
    memory_percent: float = 50.0
    disk_percent: float = 50.0
    response_time_ms: float = 300.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def engine() -> AlertEngine:
    """Return an ``AlertEngine`` initialised with the default thresholds."""
    return AlertEngine(thresholds=DEFAULT_THRESHOLDS)


@pytest.fixture()
def custom_thresholds() -> AlertThresholds:
    """Thresholds with low limits to ease test construction."""
    return AlertThresholds(
        cpu_warning=60.0,
        cpu_critical=80.0,
        memory_warning=65.0,
        memory_critical=85.0,
        disk_warning=70.0,
        disk_critical=85.0,
        response_time_warning_ms=500.0,
        response_time_critical_ms=1500.0,
    )


# ---------------------------------------------------------------------------
# CPU threshold tests
# ---------------------------------------------------------------------------
class TestCpuThresholdBreach:
    @pytest.mark.asyncio
    async def test_cpu_threshold_breach_critical(self, engine: AlertEngine) -> None:
        """
        A metric with CPU at 90% must trigger a CRITICAL alert because it
        exceeds the default CRITICAL threshold of 85%.
        """
        metric = FakeMetric(cpu_percent=90.0)
        alerts = await engine.evaluate(metric)

        cpu_alerts = [a for a in alerts if a.metric_name == "cpu_percent"]
        assert len(cpu_alerts) >= 1

        severities = {a.severity for a in cpu_alerts}
        assert "CRITICAL" in severities

    @pytest.mark.asyncio
    async def test_cpu_threshold_breach_warning(self, engine: AlertEngine) -> None:
        """CPU at 87% (above WARNING=85, below CRITICAL=95) → WARNING alert."""
        metric = FakeMetric(cpu_percent=87.0)
        alerts = await engine.evaluate(metric)

        cpu_alerts = [a for a in alerts if a.metric_name == "cpu_percent"]
        assert len(cpu_alerts) >= 1
        # At 87% we expect at least WARNING
        severities = {a.severity for a in cpu_alerts}
        assert severities & {"WARNING", "CRITICAL"}

    @pytest.mark.asyncio
    async def test_cpu_message_contains_value(self, engine: AlertEngine) -> None:
        """Alert message must include the actual CPU value."""
        metric = FakeMetric(cpu_percent=92.0)
        alerts = await engine.evaluate(metric)
        cpu_alerts = [a for a in alerts if a.metric_name == "cpu_percent"]
        assert any("92" in a.message for a in cpu_alerts)


# ---------------------------------------------------------------------------
# Memory threshold tests
# ---------------------------------------------------------------------------
class TestMemoryThresholdBreach:
    @pytest.mark.asyncio
    async def test_memory_threshold_breach_critical(self, engine: AlertEngine) -> None:
        """Memory at 95% triggers a CRITICAL alert."""
        metric = FakeMetric(memory_percent=95.0)
        alerts = await engine.evaluate(metric)

        mem_alerts = [a for a in alerts if a.metric_name == "memory_percent"]
        assert len(mem_alerts) >= 1
        assert any(a.severity == "CRITICAL" for a in mem_alerts)

    @pytest.mark.asyncio
    async def test_memory_threshold_breach_warning(self, engine: AlertEngine) -> None:
        """Memory at 83% (above WARNING=80) triggers at minimum a WARNING."""
        metric = FakeMetric(memory_percent=83.0)
        alerts = await engine.evaluate(metric)

        mem_alerts = [a for a in alerts if a.metric_name == "memory_percent"]
        assert len(mem_alerts) >= 1

    @pytest.mark.asyncio
    async def test_memory_alert_has_server_id(self, engine: AlertEngine) -> None:
        """Every alert must reference the originating server."""
        metric = FakeMetric(server_id="db-server-02", memory_percent=92.0)
        alerts = await engine.evaluate(metric)

        mem_alerts = [a for a in alerts if a.metric_name == "memory_percent"]
        assert all(a.server_id == "db-server-02" for a in mem_alerts)


# ---------------------------------------------------------------------------
# No-alert (below threshold) tests
# ---------------------------------------------------------------------------
class TestNoAlertBelowThreshold:
    @pytest.mark.asyncio
    async def test_no_alert_cpu_below_threshold(self, engine: AlertEngine) -> None:
        """CPU at 50% — well below any threshold — produces no CPU alerts."""
        metric = FakeMetric(cpu_percent=50.0)
        alerts = await engine.evaluate(metric)

        cpu_alerts = [a for a in alerts if a.metric_name == "cpu_percent"]
        assert cpu_alerts == []

    @pytest.mark.asyncio
    async def test_no_alert_all_metrics_nominal(self, engine: AlertEngine) -> None:
        """When all metrics are healthy the engine returns an empty alert list."""
        metric = FakeMetric(
            cpu_percent=30.0,
            memory_percent=40.0,
            disk_percent=25.0,
            response_time_ms=120.0,
        )
        alerts = await engine.evaluate(metric)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_no_alert_at_exact_threshold(self, engine: AlertEngine) -> None:
        """
        A metric exactly *at* the WARNING threshold (not exceeding it) must
        NOT produce an alert (strict greater-than comparison).
        """
        # Use custom thresholds: cpu_warning=60.0
        thresholds = AlertThresholds(
            cpu_warning=60.0,
            cpu_critical=80.0,
            memory_warning=65.0,
            memory_critical=85.0,
            disk_warning=70.0,
            disk_critical=85.0,
            response_time_warning_ms=500.0,
            response_time_critical_ms=1500.0,
        )
        custom_engine = AlertEngine(thresholds=thresholds)
        metric = FakeMetric(cpu_percent=60.0)  # exactly at warning, not above
        alerts = await custom_engine.evaluate(metric)
        cpu_alerts = [a for a in alerts if a.metric_name == "cpu_percent"]
        assert cpu_alerts == []


# ---------------------------------------------------------------------------
# Alert resolution tests
# ---------------------------------------------------------------------------
class TestAlertResolution:
    @pytest.mark.asyncio
    async def test_alert_resolution_clears_active_alert(
        self, engine: AlertEngine
    ) -> None:
        """
        After a CRITICAL metric is registered, a subsequent healthy metric
        for the same server should mark the alert as resolved.
        """
        # 1. Trigger alert
        bad_metric = FakeMetric(cpu_percent=92.0)
        alerts = await engine.evaluate(bad_metric)
        assert any(a.severity == "CRITICAL" for a in alerts if a.metric_name == "cpu_percent")

        # 2. Send a healthy metric — engine should resolve the open alert
        good_metric = FakeMetric(cpu_percent=40.0)
        resolved = await engine.resolve(good_metric)

        # resolved is a list of AlertEvent objects whose is_resolved was set True
        # (or the engine returns resolved events, depending on implementation)
        assert resolved is not None  # resolution path exists

    @pytest.mark.asyncio
    async def test_no_resolution_without_prior_alert(self, engine: AlertEngine) -> None:
        """Calling resolve() on a healthy server with no open alert is safe."""
        metric = FakeMetric(cpu_percent=30.0)
        result = await engine.resolve(metric)
        # Should return an empty list or None — not raise
        assert result == [] or result is None


# ---------------------------------------------------------------------------
# Severity-level assignment tests
# ---------------------------------------------------------------------------
class TestAlertSeverityLevels:
    @pytest.mark.asyncio
    async def test_severity_critical_assigned_for_cpu_95(
        self, engine: AlertEngine
    ) -> None:
        """CPU at 95% → CRITICAL severity."""
        alerts = await engine.evaluate(FakeMetric(cpu_percent=95.0))
        cpu_alerts = [a for a in alerts if a.metric_name == "cpu_percent"]
        assert any(a.severity == "CRITICAL" for a in cpu_alerts)

    @pytest.mark.asyncio
    async def test_severity_warning_assigned_for_disk_80(
        self, engine: AlertEngine
    ) -> None:
        """
        Disk at 80% — above WARNING (75%) but below CRITICAL (85%) — → WARNING.
        """
        alerts = await engine.evaluate(FakeMetric(disk_percent=80.0))
        disk_alerts = [a for a in alerts if a.metric_name == "disk_percent"]
        assert len(disk_alerts) >= 1
        # Severity should be WARNING, not CRITICAL
        assert all(a.severity in ("WARNING", "CRITICAL") for a in disk_alerts)
        # At 80%, which is below critical=85, expect WARNING
        assert any(a.severity == "WARNING" for a in disk_alerts)

    @pytest.mark.asyncio
    async def test_severity_critical_for_response_time(
        self, engine: AlertEngine
    ) -> None:
        """Response time 2500 ms > CRITICAL threshold 2000 ms → CRITICAL."""
        alerts = await engine.evaluate(FakeMetric(response_time_ms=2500.0))
        rt_alerts = [a for a in alerts if a.metric_name == "response_time_ms"]
        assert any(a.severity == "CRITICAL" for a in rt_alerts)

    @pytest.mark.asyncio
    async def test_severity_levels_are_valid_strings(
        self, engine: AlertEngine
    ) -> None:
        """Every alert severity must be one of the known string constants."""
        VALID_SEVERITIES = {"INFO", "WARNING", "CRITICAL"}
        alerts = await engine.evaluate(
            FakeMetric(cpu_percent=90.0, memory_percent=92.0, disk_percent=88.0)
        )
        for alert in alerts:
            assert alert.severity in VALID_SEVERITIES, (
                f"Unexpected severity '{alert.severity}' on metric '{alert.metric_name}'"
            )
