"""
AlertEngine — evaluates server metrics against thresholds and fires notifications.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.metrics import AlertEvent, AlertSeverity, ServerMetric

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

CPU_THRESHOLD = 85.0        # %
MEMORY_THRESHOLD = 90.0     # %
DISK_THRESHOLD = 85.0       # %
RESPONSE_TIME_THRESHOLD = 2000.0  # ms


def _severity_for_value(value: float, threshold: float) -> AlertSeverity:
    """Map overage ratio to a severity level."""
    ratio = value / threshold
    if ratio >= 1.20:
        return AlertSeverity.CRITICAL
    if ratio >= 1.10:
        return AlertSeverity.HIGH
    if ratio >= 1.05:
        return AlertSeverity.MEDIUM
    return AlertSeverity.LOW


class AlertEngine:
    """Evaluates metrics, creates alert events, and dispatches notifications."""

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate_metrics(
        self, session: AsyncSession, metric: ServerMetric
    ) -> list[AlertEvent]:
        """Check a ServerMetric against all thresholds; create AlertEvent if breached."""
        alerts_created: list[AlertEvent] = []

        checks = [
            ("cpu_high", metric.cpu_usage, CPU_THRESHOLD, "CPU"),
            ("memory_high", metric.memory_usage, MEMORY_THRESHOLD, "Memory"),
            ("disk_high", metric.disk_usage, DISK_THRESHOLD, "Disk"),
        ]

        for alert_type, value, threshold, label in checks:
            if value >= threshold:
                severity = _severity_for_value(value, threshold)
                message = (
                    f"{label} usage on {metric.server_name} is {value:.1f}% "
                    f"(threshold: {threshold:.0f}%)"
                )
                alert = AlertEvent(
                    metric_id=metric.id,
                    alert_type=alert_type,
                    severity=severity,
                    message=message,
                    triggered_at=datetime.now(tz=timezone.utc),
                    is_resolved=False,
                )
                session.add(alert)
                await session.flush()
                await session.refresh(alert)
                alerts_created.append(alert)

                logger.warning(
                    "alert_triggered",
                    alert_type=alert_type,
                    severity=severity,
                    server=metric.server_name,
                    value=value,
                )

                # Fire and forget notification (non-blocking)
                try:
                    self.send_alert_notification(alert)
                except Exception as exc:  # noqa: BLE001
                    logger.error("notification_dispatch_failed", error=str(exc))

        # Resolve old alerts for this server when metrics recover
        if metric.cpu_usage < CPU_THRESHOLD:
            await self.resolve_alerts(session, metric.server_id, "cpu_high")
        if metric.memory_usage < MEMORY_THRESHOLD:
            await self.resolve_alerts(session, metric.server_id, "memory_high")
        if metric.disk_usage < DISK_THRESHOLD:
            await self.resolve_alerts(session, metric.server_id, "disk_high")

        return alerts_created

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def resolve_alerts(
        self,
        session: AsyncSession,
        server_id: str,
        alert_type: str | None = None,
    ) -> int:
        """
        Mark all unresolved alerts for server_id (optionally filtered by alert_type)
        as resolved with the current timestamp.
        Returns the number of alerts resolved.
        """
        # Collect unresolved alert IDs for the given server via JOIN
        stmt = (
            select(AlertEvent.id)
            .join(ServerMetric, AlertEvent.metric_id == ServerMetric.id)
            .where(
                ServerMetric.server_id == server_id,
                AlertEvent.is_resolved.is_(False),
            )
        )
        if alert_type:
            stmt = stmt.where(AlertEvent.alert_type == alert_type)

        result = await session.execute(stmt)
        ids = [row[0] for row in result.fetchall()]

        if not ids:
            return 0

        now = datetime.now(tz=timezone.utc)
        await session.execute(
            update(AlertEvent)
            .where(AlertEvent.id.in_(ids))
            .values(is_resolved=True, resolved_at=now)
        )
        logger.info("alerts_resolved", count=len(ids), server_id=server_id)
        return len(ids)

    # ------------------------------------------------------------------
    # Notification dispatch
    # ------------------------------------------------------------------

    def send_alert_notification(self, alert: AlertEvent) -> None:
        """Route alert notification to configured channels."""
        if settings.SMTP_USER and settings.SMTP_PASS and settings.ALERT_EMAIL:
            try:
                self.send_email_notification(alert)
            except Exception as exc:  # noqa: BLE001
                logger.error("email_notification_failed", error=str(exc))

        if settings.SLACK_WEBHOOK_URL:
            try:
                self.send_slack_notification(alert)
            except Exception as exc:  # noqa: BLE001
                logger.error("slack_notification_failed", error=str(exc))

    def send_email_notification(self, alert: AlertEvent) -> None:
        """Send an SMTP alert email."""
        subject = f"[{alert.severity}] CloudPulse Alert: {alert.alert_type}"
        body = (
            f"Alert ID   : {alert.id}\n"
            f"Type       : {alert.alert_type}\n"
            f"Severity   : {alert.severity}\n"
            f"Message    : {alert.message}\n"
            f"Triggered  : {alert.triggered_at.isoformat()}\n\n"
            "— CloudPulse Monitoring"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_USER
        msg["To"] = settings.ALERT_EMAIL
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.sendmail(settings.SMTP_USER, settings.ALERT_EMAIL, msg.as_string())

        logger.info("email_sent", to=settings.ALERT_EMAIL, alert_id=alert.id)

    def send_slack_notification(self, alert: AlertEvent) -> None:
        """POST an alert payload to the configured Slack webhook."""
        severity_emoji = {
            AlertSeverity.LOW: "🟡",
            AlertSeverity.MEDIUM: "🟠",
            AlertSeverity.HIGH: "🔴",
            AlertSeverity.CRITICAL: "🚨",
        }.get(alert.severity, "⚠️")

        payload = {
            "text": f"{severity_emoji} *CloudPulse Alert* [{alert.severity}]",
            "attachments": [
                {
                    "color": {
                        AlertSeverity.LOW: "warning",
                        AlertSeverity.MEDIUM: "warning",
                        AlertSeverity.HIGH: "danger",
                        AlertSeverity.CRITICAL: "danger",
                    }.get(alert.severity, "warning"),
                    "fields": [
                        {"title": "Alert Type", "value": alert.alert_type, "short": True},
                        {"title": "Severity", "value": alert.severity, "short": True},
                        {"title": "Message", "value": alert.message, "short": False},
                        {
                            "title": "Triggered At",
                            "value": alert.triggered_at.isoformat(),
                            "short": True,
                        },
                    ],
                }
            ],
        }

        response = requests.post(
            settings.SLACK_WEBHOOK_URL,
            json=payload,
            timeout=5,
        )
        response.raise_for_status()
        logger.info("slack_notification_sent", alert_id=alert.id, status=response.status_code)
