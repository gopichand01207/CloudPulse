"""
SQLAlchemy ORM models for CloudPulse.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AlertSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ServerStatus(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    PENDING = "pending"


# ---------------------------------------------------------------------------
# ServerMetric
# ---------------------------------------------------------------------------


class ServerMetric(Base):
    """Stores a point-in-time snapshot of server resource usage."""

    __tablename__ = "server_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    server_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cpu_usage: Mapped[float] = mapped_column(Float, nullable=False)
    memory_usage: Mapped[float] = mapped_column(Float, nullable=False)
    disk_usage: Mapped[float] = mapped_column(Float, nullable=False)
    network_in: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    network_out: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    region: Mapped[str] = mapped_column(String(32), nullable=False, default="us-east-1")
    instance_type: Mapped[str] = mapped_column(String(32), nullable=False, default="t3.medium")
    status: Mapped[str] = mapped_column(
        Enum(ServerStatus, name="server_status_enum"),
        nullable=False,
        default=ServerStatus.RUNNING,
    )

    # Relationships
    alerts: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="metric", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_server_metrics_server_id_timestamp", "server_id", "timestamp"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ServerMetric id={self.id} server={self.server_name} "
            f"cpu={self.cpu_usage:.1f}% ts={self.timestamp}>"
        )


# ---------------------------------------------------------------------------
# AlertEvent
# ---------------------------------------------------------------------------


class AlertEvent(Base):
    """Records an alert triggered when a server metric crosses a threshold."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    metric_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("server_metrics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(
        Enum(AlertSeverity, name="alert_severity_enum"),
        nullable=False,
        default=AlertSeverity.MEDIUM,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Relationships
    metric: Mapped["ServerMetric"] = relationship("ServerMetric", back_populates="alerts")

    __table_args__ = (
        Index("ix_alert_events_severity_resolved", "severity", "is_resolved"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AlertEvent id={self.id} type={self.alert_type} "
            f"severity={self.severity} resolved={self.is_resolved}>"
        )


# ---------------------------------------------------------------------------
# ServiceHealth
# ---------------------------------------------------------------------------


class ServiceHealth(Base):
    """Records the latest health-check result for a monitored microservice."""

    __tablename__ = "service_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    service_url: Mapped[str] = mapped_column(String(512), nullable=False)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_checked: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ServiceHealth name={self.service_name} healthy={self.is_healthy}>"


# ---------------------------------------------------------------------------
# LogEntry
# ---------------------------------------------------------------------------


class LogEntry(Base):
    """Stores a single log line ingested from a server or service."""

    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    log_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    @property
    def level(self) -> str:
        return self.log_level

    @level.setter
    def level(self, val: str) -> None:
        self.log_level = val

    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False, default="unknown")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("ix_log_entries_server_id_level_timestamp", "server_id", "log_level", "timestamp"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LogEntry id={self.id} server={self.server_id} level={self.log_level}>"
