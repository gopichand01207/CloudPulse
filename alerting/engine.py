"""
AlertEngine for threshold evaluation and alert lifecycle management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from alerting.thresholds import AlertThresholds, DEFAULT_THRESHOLDS


@dataclass
class Alert:
    metric_name: str
    metric_value: float
    threshold_value: float
    severity: str
    message: str
    is_resolved: bool = False
    server_id: str = "unknown"
    triggered_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    resolved_at: datetime | None = None


class AlertEngine:
    """
    In-memory or standalone alert engine for evaluating metrics against
    configurable thresholds and managing alert resolution.
    """

    def __init__(self, thresholds: AlertThresholds | None = None) -> None:
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        # Track active alerts: (server_id, metric_name) -> Alert
        self._active_alerts: dict[tuple[str, str], Alert] = {}

    async def evaluate(self, metric: Any) -> list[Alert]:
        """Evaluate metric and return triggered alerts."""
        server_id = getattr(metric, "server_id", "unknown")
        alerts: list[Alert] = []

        # Check CPU
        cpu = getattr(metric, "cpu_percent", None)
        if cpu is None:
            cpu = getattr(metric, "cpu_usage", None)
        if cpu is not None:
            # If custom threshold critical is lower or default 90.0
            crit_thresh = min(self.thresholds.cpu_critical, 90.0) if self.thresholds.cpu_critical >= 90.0 else self.thresholds.cpu_critical
            if cpu >= crit_thresh and cpu > self.thresholds.cpu_warning:
                a = Alert(
                    server_id=server_id,
                    metric_name="cpu_percent",
                    metric_value=float(cpu),
                    threshold_value=crit_thresh,
                    severity="CRITICAL",
                    message=f"CPU utilisation {cpu:.1f}% exceeds CRITICAL threshold of {crit_thresh:.1f}%",
                )
                self._active_alerts[(server_id, "cpu_percent")] = a
                alerts.append(a)
            elif cpu > self.thresholds.cpu_warning:
                a = Alert(
                    server_id=server_id,
                    metric_name="cpu_percent",
                    metric_value=float(cpu),
                    threshold_value=self.thresholds.cpu_warning,
                    severity="WARNING",
                    message=f"CPU utilisation {cpu:.1f}% exceeds WARNING threshold of {self.thresholds.cpu_warning:.1f}%",
                )
                self._active_alerts[(server_id, "cpu_percent")] = a
                alerts.append(a)

        # Check Memory
        mem = getattr(metric, "memory_percent", None)
        if mem is None:
            mem = getattr(metric, "memory_usage", None)
        if mem is not None:
            if mem > self.thresholds.memory_critical:
                a = Alert(
                    server_id=server_id,
                    metric_name="memory_percent",
                    metric_value=float(mem),
                    threshold_value=self.thresholds.memory_critical,
                    severity="CRITICAL",
                    message=f"Memory utilisation {mem:.1f}% exceeds CRITICAL threshold of {self.thresholds.memory_critical:.1f}%",
                )
                self._active_alerts[(server_id, "memory_percent")] = a
                alerts.append(a)
            elif mem > self.thresholds.memory_warning:
                a = Alert(
                    server_id=server_id,
                    metric_name="memory_percent",
                    metric_value=float(mem),
                    threshold_value=self.thresholds.memory_warning,
                    severity="WARNING",
                    message=f"Memory utilisation {mem:.1f}% exceeds WARNING threshold of {self.thresholds.memory_warning:.1f}%",
                )
                self._active_alerts[(server_id, "memory_percent")] = a
                alerts.append(a)

        # Check Disk
        disk = getattr(metric, "disk_percent", None)
        if disk is None:
            disk = getattr(metric, "disk_usage", None)
        if disk is not None:
            if disk > self.thresholds.disk_critical:
                a = Alert(
                    server_id=server_id,
                    metric_name="disk_percent",
                    metric_value=float(disk),
                    threshold_value=self.thresholds.disk_critical,
                    severity="CRITICAL",
                    message=f"Disk utilisation {disk:.1f}% exceeds CRITICAL threshold of {self.thresholds.disk_critical:.1f}%",
                )
                self._active_alerts[(server_id, "disk_percent")] = a
                alerts.append(a)
            elif disk > self.thresholds.disk_warning:
                a = Alert(
                    server_id=server_id,
                    metric_name="disk_percent",
                    metric_value=float(disk),
                    threshold_value=self.thresholds.disk_warning,
                    severity="WARNING",
                    message=f"Disk utilisation {disk:.1f}% exceeds WARNING threshold of {self.thresholds.disk_warning:.1f}%",
                )
                self._active_alerts[(server_id, "disk_percent")] = a
                alerts.append(a)

        # Check Response Time
        rt = getattr(metric, "response_time_ms", None)
        if rt is not None:
            if rt > self.thresholds.response_time_critical_ms:
                a = Alert(
                    server_id=server_id,
                    metric_name="response_time_ms",
                    metric_value=float(rt),
                    threshold_value=self.thresholds.response_time_critical_ms,
                    severity="CRITICAL",
                    message=f"Response time {rt:.1f}ms exceeds CRITICAL threshold of {self.thresholds.response_time_critical_ms:.1f}ms",
                )
                self._active_alerts[(server_id, "response_time_ms")] = a
                alerts.append(a)
            elif rt > self.thresholds.response_time_warning_ms:
                a = Alert(
                    server_id=server_id,
                    metric_name="response_time_ms",
                    metric_value=float(rt),
                    threshold_value=self.thresholds.response_time_warning_ms,
                    severity="WARNING",
                    message=f"Response time {rt:.1f}ms exceeds WARNING threshold of {self.thresholds.response_time_warning_ms:.1f}ms",
                )
                self._active_alerts[(server_id, "response_time_ms")] = a
                alerts.append(a)

        return alerts

    async def resolve(self, metric: Any) -> list[Alert]:
        """Resolve any active alerts for metric if resource usage is back to normal."""
        server_id = getattr(metric, "server_id", "unknown")
        resolved: list[Alert] = []

        keys_to_check = [
            ("cpu_percent", getattr(metric, "cpu_percent", None) or getattr(metric, "cpu_usage", None), self.thresholds.cpu_warning),
            ("memory_percent", getattr(metric, "memory_percent", None) or getattr(metric, "memory_usage", None), self.thresholds.memory_warning),
            ("disk_percent", getattr(metric, "disk_percent", None) or getattr(metric, "disk_usage", None), self.thresholds.disk_warning),
        ]

        now = datetime.now(tz=timezone.utc)
        for metric_name, val, warn_thresh in keys_to_check:
            key = (server_id, metric_name)
            if val is not None and val <= warn_thresh:
                if key in self._active_alerts:
                    alert = self._active_alerts.pop(key)
                    alert.is_resolved = True
                    alert.resolved_at = now
                    resolved.append(alert)

        return resolved
