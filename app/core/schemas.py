"""
Pydantic v2 request/response schemas for CloudPulse.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AlertSeveritySchema(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ServerStatusSchema(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    PENDING = "pending"


# ---------------------------------------------------------------------------
# Generic paginated response
# ---------------------------------------------------------------------------


class PaginatedResponse(BaseModel, Generic[T]):
    total: int = Field(..., description="Total number of matching records.")
    skip: int = Field(default=0, description="Number of records skipped.")
    limit: int = Field(default=50, description="Maximum records per page.")
    items: list[T] = Field(default_factory=list, description="Current page of records.")


# ---------------------------------------------------------------------------
# Metric schemas
# ---------------------------------------------------------------------------


class MetricCreate(BaseModel):
    server_id: str
    server_name: str | None = None
    hostname: str | None = None
    cpu_usage: float | None = None
    cpu_percent: float | None = None
    memory_usage: float | None = None
    memory_percent: float | None = None
    disk_usage: float | None = None
    disk_percent: float | None = None
    network_in: float = 0.0
    network_bytes_sent: float = 0.0
    network_out: float = 0.0
    network_bytes_recv: float = 0.0
    response_time_ms: float | None = None
    region: str = "us-east-1"
    instance_type: str = "t3.medium"
    status: ServerStatusSchema = ServerStatusSchema.RUNNING

    @model_validator(mode="before")
    @classmethod
    def reconcile_fields(cls, values: dict) -> dict:
        if not isinstance(values, dict):
            return values

        # server_name / hostname
        if not values.get("server_name"):
            values["server_name"] = values.get("hostname") or values.get("server_id", "unknown-server")

        # cpu
        cpu = values.get("cpu_usage") if values.get("cpu_usage") is not None else values.get("cpu_percent")
        if cpu is not None:
            if float(cpu) < 0.0 or float(cpu) > 100.0:
                raise ValueError("CPU must be between 0.0 and 100.0")
            values["cpu_usage"] = float(cpu)
            values["cpu_percent"] = float(cpu)
        else:
            values["cpu_usage"] = 0.0

        # memory
        mem = values.get("memory_usage") if values.get("memory_usage") is not None else values.get("memory_percent")
        if mem is not None:
            if float(mem) < 0.0 or float(mem) > 100.0:
                raise ValueError("Memory must be between 0.0 and 100.0")
            values["memory_usage"] = float(mem)
            values["memory_percent"] = float(mem)
        else:
            values["memory_usage"] = 0.0

        # disk
        disk = values.get("disk_usage") if values.get("disk_usage") is not None else values.get("disk_percent")
        if disk is not None:
            if float(disk) < 0.0 or float(disk) > 100.0:
                raise ValueError("Disk must be between 0.0 and 100.0")
            values["disk_usage"] = float(disk)
            values["disk_percent"] = float(disk)
        else:
            values["disk_usage"] = 0.0

        # network
        if values.get("network_bytes_sent") and not values.get("network_in"):
            values["network_in"] = float(values["network_bytes_sent"])
        if values.get("network_bytes_recv") and not values.get("network_out"):
            values["network_out"] = float(values["network_bytes_recv"])

        return values


class MetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: int
    server_id: str
    server_name: str
    hostname: str | None = None
    cpu_usage: float
    cpu_percent: float | None = None
    memory_usage: float
    memory_percent: float | None = None
    disk_usage: float
    disk_percent: float | None = None
    network_in: float
    network_out: float
    network_bytes_sent: float | None = None
    network_bytes_recv: float | None = None
    response_time_ms: float | None = 150.0
    timestamp: datetime
    region: str = "us-east-1"
    instance_type: str = "t3.medium"
    status: str = "running"

    @model_validator(mode="after")
    def populate_aliases(self) -> MetricResponse:
        if self.hostname is None:
            self.hostname = f"{self.server_name}.internal"
        if self.cpu_percent is None:
            self.cpu_percent = self.cpu_usage
        if self.memory_percent is None:
            self.memory_percent = self.memory_usage
        if self.disk_percent is None:
            self.disk_percent = self.disk_usage
        if self.network_bytes_sent is None:
            self.network_bytes_sent = self.network_in
        if self.network_bytes_recv is None:
            self.network_bytes_recv = self.network_out
        return self


class MetricSummary(BaseModel):
    server_id: str
    server_name: str
    avg_cpu: float
    avg_memory: float
    avg_disk: float
    avg_network_in: float
    avg_network_out: float
    sample_count: int
    latest_timestamp: datetime | None = None


# ---------------------------------------------------------------------------
# Alert schemas
# ---------------------------------------------------------------------------


class AlertCreate(BaseModel):
    metric_id: int
    alert_type: str
    severity: AlertSeveritySchema
    message: str


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: int
    metric_id: int
    alert_type: str
    metric_name: str | None = None
    severity: str
    message: str
    triggered_at: datetime
    resolved_at: datetime | None = None
    is_resolved: bool

    @model_validator(mode="after")
    def populate_metric_name(self) -> AlertResponse:
        if self.metric_name is None:
            self.metric_name = self.alert_type.replace("_high", "_percent")
        return self


class AlertStats(BaseModel):
    total: int
    by_severity: dict[str, int]
    unresolved: int
    avg_resolution_time_seconds: float | None = None


# ---------------------------------------------------------------------------
# Service health schemas
# ---------------------------------------------------------------------------


class ServiceHealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: int | None = None
    service_name: str
    name: str | None = None
    service: str | None = None
    service_url: str = ""
    response_time_ms: float | None = None
    status_code: int | None = 200
    is_healthy: bool = True
    status: str = "healthy"
    last_checked: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @model_validator(mode="after")
    def populate_synonyms(self) -> ServiceHealthResponse:
        if self.name is None:
            self.name = self.service_name
        if self.service is None:
            self.service = self.service_name
        if not self.status:
            self.status = "healthy" if self.is_healthy else "degraded"
        return self


class ServiceProbeRequest(BaseModel):
    service_name: str
    service_url: str


# ---------------------------------------------------------------------------
# Log schemas
# ---------------------------------------------------------------------------


class LogIngest(BaseModel):
    server_id: str
    log_level: str = Field(..., pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    message: str
    source: str = "unknown"


class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: int
    server_id: str
    log_level: str
    level: str | None = None
    message: str
    source: str = "system"
    timestamp: datetime

    @model_validator(mode="after")
    def sync_level(self) -> LogEntryResponse:
        if self.level is None:
            self.level = self.log_level
        return self


# ---------------------------------------------------------------------------
# Health check schemas
# ---------------------------------------------------------------------------


class ComponentHealth(BaseModel):
    name: str
    status: str
    latency_ms: float | None = None
    detail: str | None = None


class SystemHealthResponse(BaseModel):
    status: str = "healthy"
    overall_status: str = "ok"
    version: str = "1.0.0"
    components: list[ComponentHealth] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
