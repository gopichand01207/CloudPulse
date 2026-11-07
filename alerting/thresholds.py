"""
alerting/thresholds.py
-----------------------
Alert threshold definitions and evaluation logic for CloudPulse.

Usage::

    from alerting.thresholds import DEFAULT_THRESHOLDS, ThresholdEvaluator

    breached, severity, message = ThresholdEvaluator.evaluate(
        metric_name="cpu_percent",
        value=92.0,
        thresholds=DEFAULT_THRESHOLDS,
    )
    if breached:
        print(f"[{severity}] {message}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Threshold configuration dataclass
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class AlertThresholds:
    """
    Configurable alert thresholds for every tracked metric.

    All percentage values are in the range [0, 100].
    Response-time values are in milliseconds.

    Attributes
    ----------
    cpu_warning:
        CPU utilisation (%) that triggers a WARNING alert.
    cpu_critical:
        CPU utilisation (%) that triggers a CRITICAL alert.
    memory_warning:
        Memory utilisation (%) that triggers a WARNING alert.
    memory_critical:
        Memory utilisation (%) that triggers a CRITICAL alert.
    disk_warning:
        Disk utilisation (%) that triggers a WARNING alert.
    disk_critical:
        Disk utilisation (%) that triggers a CRITICAL alert.
    response_time_warning_ms:
        HTTP response time (ms) that triggers a WARNING alert.
    response_time_critical_ms:
        HTTP response time (ms) that triggers a CRITICAL alert.
    """

    # CPU
    cpu_warning: float = 85.0
    cpu_critical: float = 95.0

    # Memory
    memory_warning: float = 80.0
    memory_critical: float = 90.0

    # Disk
    disk_warning: float = 75.0
    disk_critical: float = 85.0

    # HTTP response time
    response_time_warning_ms: float = 1_000.0
    response_time_critical_ms: float = 2_000.0


# ──────────────────────────────────────────────────────────────────────────────
# Singleton default thresholds
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS: AlertThresholds = AlertThresholds()
"""
Pre-instantiated thresholds using the class defaults.

Import this directly for single-configuration deployments::

    from alerting.thresholds import DEFAULT_THRESHOLDS
"""


# ──────────────────────────────────────────────────────────────────────────────
# Threshold evaluator
# ──────────────────────────────────────────────────────────────────────────────

# Mapping from metric name → (warning attr, critical attr, unit label)
_METRIC_MAPPING: dict[str, Tuple[str, str, str]] = {
    "cpu_percent": ("cpu_warning", "cpu_critical", "%"),
    "memory_percent": ("memory_warning", "memory_critical", "%"),
    "disk_percent": ("disk_warning", "disk_critical", "%"),
    "response_time_ms": (
        "response_time_warning_ms",
        "response_time_critical_ms",
        "ms",
    ),
}


class ThresholdEvaluator:
    """
    Stateless evaluator that compares a single metric value against
    the provided thresholds.

    All methods are class-methods — no instantiation is required.

    Example
    -------
    ::

        breached, severity, message = ThresholdEvaluator.evaluate(
            metric_name="memory_percent",
            value=93.5,
            thresholds=DEFAULT_THRESHOLDS,
        )
    """

    @classmethod
    def evaluate(
        cls,
        metric_name: str,
        value: float,
        thresholds: AlertThresholds,
    ) -> Tuple[bool, str, str]:
        """
        Evaluate a single metric value against the given thresholds.

        Parameters
        ----------
        metric_name:
            Canonical metric identifier.  Supported values:
            ``"cpu_percent"``, ``"memory_percent"``,
            ``"disk_percent"``, ``"response_time_ms"``.
        value:
            The observed metric value.
        thresholds:
            An :class:`AlertThresholds` instance to compare against.

        Returns
        -------
        (breached, severity, message)
            * **breached** – ``True`` if any threshold is exceeded.
            * **severity** – ``"CRITICAL"`` | ``"WARNING"`` | ``""``
              (empty string when no threshold is breached).
            * **message** – Human-readable description of the breach,
              or an empty string when no threshold is breached.

        Raises
        ------
        ValueError
            If ``metric_name`` is not recognised.
        """
        if metric_name not in _METRIC_MAPPING:
            known = ", ".join(sorted(_METRIC_MAPPING))
            raise ValueError(
                f"Unknown metric '{metric_name}'.  Known metrics: {known}"
            )

        warn_attr, crit_attr, unit = _METRIC_MAPPING[metric_name]
        warn_limit: float = getattr(thresholds, warn_attr)
        crit_limit: float = getattr(thresholds, crit_attr)

        # CRITICAL takes priority over WARNING
        if value > crit_limit:
            severity = "CRITICAL"
            message = cls._build_message(metric_name, value, crit_limit, severity, unit)
            return True, severity, message

        if value > warn_limit:
            severity = "WARNING"
            message = cls._build_message(metric_name, value, warn_limit, severity, unit)
            return True, severity, message

        return False, "", ""

    @classmethod
    def evaluate_all(
        cls,
        metrics: dict[str, float],
        thresholds: AlertThresholds,
    ) -> list[Tuple[str, bool, str, str]]:
        """
        Evaluate a mapping of metric names → values in one call.

        Parameters
        ----------
        metrics:
            Dict of ``{metric_name: value}`` pairs.
        thresholds:
            An :class:`AlertThresholds` instance.

        Returns
        -------
        list of (metric_name, breached, severity, message)
            One tuple per metric that was evaluated.  Unrecognised metrics
            are silently skipped.
        """
        results: list[Tuple[str, bool, str, str]] = []
        for name, value in metrics.items():
            if name not in _METRIC_MAPPING:
                continue
            breached, severity, message = cls.evaluate(name, value, thresholds)
            results.append((name, breached, severity, message))
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_message(
        metric_name: str,
        value: float,
        limit: float,
        severity: str,
        unit: str,
    ) -> str:
        """Return a formatted human-readable alert message."""
        readable_name = metric_name.replace("_", " ").title()
        return (
            f"{readable_name} is {value:.1f}{unit}, "
            f"exceeding the {severity} threshold of {limit:.1f}{unit}."
        )
