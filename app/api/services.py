"""
Services API router — /api/v1/services
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.schemas import LogEntryResponse, MetricResponse, ServiceHealthResponse
from app.models.metrics import LogEntry, ServerMetric, ServiceHealth
from app.services.log_pipeline import LogPipeline

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ServiceHealthResponse])
async def list_monitored_services(
    db: AsyncSession = Depends(get_db),
) -> list[ServiceHealthResponse]:
    """Return all monitored microservices with their latest health status."""

    result = await db.execute(
        select(ServiceHealth).order_by(ServiceHealth.service_name)
    )
    services = list(result.scalars().all())
    return [ServiceHealthResponse.model_validate(s) for s in services]


# ---------------------------------------------------------------------------
# GET /{service_name}/metrics
# ---------------------------------------------------------------------------


@router.get("/{service_name}/metrics", response_model=list[MetricResponse])
async def get_service_metrics(
    service_name: str,
    limit: int = Query(20, ge=1, le=200, description="Max metrics to return."),
    db: AsyncSession = Depends(get_db),
) -> list[MetricResponse]:
    """
    Return recent server metrics for the servers hosting a given service.

    The server_name is matched against `service_name` (case-insensitive prefix match).
    """

    result = await db.execute(
        select(ServerMetric)
        .where(ServerMetric.server_name.ilike(f"%{service_name}%"))
        .order_by(ServerMetric.timestamp.desc())
        .limit(limit)
    )
    metrics = list(result.scalars().all())

    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No server metrics found matching service name '{service_name}'.",
        )

    return [MetricResponse.model_validate(m) for m in metrics]


# ---------------------------------------------------------------------------
# GET /{service_name}/logs
# ---------------------------------------------------------------------------


@router.get("/{service_name}/logs", response_model=list[LogEntryResponse])
async def get_service_logs(
    service_name: str,
    limit: int = Query(100, ge=1, le=500, description="Max log entries to return."),
    db: AsyncSession = Depends(get_db),
) -> list[LogEntryResponse]:
    """
    Return recent log entries associated with a service.

    Logs are matched by server_id containing the service_name substring
    or by source field.
    """

    result = await db.execute(
        select(LogEntry)
        .where(
            LogEntry.server_id.ilike(f"%{service_name}%")
            | LogEntry.source.ilike(f"%{service_name}%")
        )
        .order_by(LogEntry.timestamp.desc())
        .limit(limit)
    )
    logs = list(result.scalars().all())

    if not logs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No logs found for service '{service_name}'.",
        )

    return [LogEntryResponse.model_validate(log) for log in logs]
