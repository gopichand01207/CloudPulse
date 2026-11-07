"""
Metrics API router — /api/v1/metrics
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.schemas import (
    MetricCreate,
    MetricResponse,
    MetricSummary,
    PaginatedResponse,
)
from app.models.metrics import ServerMetric, ServerStatus
from app.services.collector import MetricCollector

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedResponse[MetricResponse])
@router.get("/", response_model=PaginatedResponse[MetricResponse], include_in_schema=False)
async def list_metrics(
    skip: int = Query(0, ge=0, description="Number of records to skip."),
    limit: int = Query(50, ge=1, le=500, description="Max records to return."),
    server_id: str | None = Query(None, description="Filter by server ID."),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MetricResponse]:
    """Return a paginated list of server metrics, optionally filtered by server_id."""

    base_q = select(ServerMetric).order_by(ServerMetric.timestamp.desc())
    count_q = select(func.count()).select_from(ServerMetric)

    if server_id:
        base_q = base_q.where(ServerMetric.server_id == server_id)
        count_q = count_q.where(ServerMetric.server_id == server_id)

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    paged_result = await db.execute(base_q.offset(skip).limit(limit))
    items = list(paged_result.scalars().all())

    return PaginatedResponse[MetricResponse](
        total=total,
        skip=skip,
        limit=limit,
        items=[MetricResponse.model_validate(m) for m in items],
    )


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=list[MetricSummary])
async def get_summary(db: AsyncSession = Depends(get_db)) -> list[MetricSummary]:
    """Return per-server aggregate statistics (avg CPU, memory, disk, network)."""

    result = await db.execute(
        select(
            ServerMetric.server_id,
            ServerMetric.server_name,
            func.avg(ServerMetric.cpu_usage).label("avg_cpu"),
            func.avg(ServerMetric.memory_usage).label("avg_memory"),
            func.avg(ServerMetric.disk_usage).label("avg_disk"),
            func.avg(ServerMetric.network_in).label("avg_network_in"),
            func.avg(ServerMetric.network_out).label("avg_network_out"),
            func.count(ServerMetric.id).label("sample_count"),
            func.max(ServerMetric.timestamp).label("latest_timestamp"),
        ).group_by(ServerMetric.server_id, ServerMetric.server_name)
    )
    rows = result.fetchall()

    return [
        MetricSummary(
            server_id=row.server_id,
            server_name=row.server_name,
            avg_cpu=round(row.avg_cpu or 0.0, 2),
            avg_memory=round(row.avg_memory or 0.0, 2),
            avg_disk=round(row.avg_disk or 0.0, 2),
            avg_network_in=round(row.avg_network_in or 0.0, 4),
            avg_network_out=round(row.avg_network_out or 0.0, 4),
            sample_count=row.sample_count,
            latest_timestamp=row.latest_timestamp,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /realtime/{server_id}
# ---------------------------------------------------------------------------


@router.get("/realtime/{server_id}", response_model=MetricResponse)
async def get_realtime_metric(
    server_id: str,
    db: AsyncSession = Depends(get_db),
) -> MetricResponse:
    """Return the latest metric snapshot for a specific server."""

    result = await db.execute(
        select(ServerMetric)
        .where(ServerMetric.server_id == server_id)
        .order_by(ServerMetric.timestamp.desc())
        .limit(1)
    )
    metric = result.scalar_one_or_none()
    if metric is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No metrics found for server '{server_id}'.",
        )
    return MetricResponse.model_validate(metric)


# ---------------------------------------------------------------------------
# GET /history and GET /history/{server_id}
# ---------------------------------------------------------------------------


@router.get("/history", response_model=list[MetricResponse])
async def get_history_query(
    server_id: str | None = Query(None, description="Filter by server ID."),
    start_time: datetime | None = Query(None, description="Start time (ISO 8601)."),
    end_time: datetime | None = Query(None, description="End time (ISO 8601)."),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[MetricResponse]:
    """Query metric history by time range and optional server_id."""
    base_q = select(ServerMetric).order_by(ServerMetric.timestamp.desc())
    if server_id:
        base_q = base_q.where(ServerMetric.server_id == server_id)
    if start_time:
        base_q = base_q.where(ServerMetric.timestamp >= start_time)
    if end_time:
        base_q = base_q.where(ServerMetric.timestamp <= end_time)

    result = await db.execute(base_q.limit(limit))
    items = list(result.scalars().all())
    return [MetricResponse.model_validate(m) for m in items]


@router.get("/history/{server_id}", response_model=PaginatedResponse[MetricResponse])
async def get_metric_history(
    server_id: str,
    start_time: datetime | None = Query(None, description="Start of time range (ISO 8601)."),
    end_time: datetime | None = Query(None, description="End of time range (ISO 8601)."),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MetricResponse]:
    """Return historical metrics for a server, with optional time-range filtering."""

    base_q = (
        select(ServerMetric)
        .where(ServerMetric.server_id == server_id)
        .order_by(ServerMetric.timestamp.desc())
    )
    count_q = (
        select(func.count())
        .select_from(ServerMetric)
        .where(ServerMetric.server_id == server_id)
    )

    if start_time:
        base_q = base_q.where(ServerMetric.timestamp >= start_time)
        count_q = count_q.where(ServerMetric.timestamp >= start_time)
    if end_time:
        base_q = base_q.where(ServerMetric.timestamp <= end_time)
        count_q = count_q.where(ServerMetric.timestamp <= end_time)

    total = (await db.execute(count_q)).scalar_one()
    items = list((await db.execute(base_q.offset(skip).limit(limit))).scalars().all())

    return PaginatedResponse[MetricResponse](
        total=total,
        skip=skip,
        limit=limit,
        items=[MetricResponse.model_validate(m) for m in items],
    )


# ---------------------------------------------------------------------------
# POST /collect
# ---------------------------------------------------------------------------


@router.post("/collect", status_code=status.HTTP_200_OK)
async def collect_metrics(
    body: MetricCreate | None = None,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Ingest a metric payload or trigger a full background collection cycle.
    """
    if body is not None:
        metric = ServerMetric(
            server_id=body.server_id,
            server_name=body.server_name or body.server_id,
            cpu_usage=body.cpu_usage or 0.0,
            memory_usage=body.memory_usage or 0.0,
            disk_usage=body.disk_usage or 0.0,
            network_in=body.network_in or 0.0,
            network_out=body.network_out or 0.0,
            region=body.region,
            instance_type=body.instance_type,
            status=ServerStatus.RUNNING,
            timestamp=datetime.now(tz=timezone.utc),
        )
        db.add(metric)
        await db.commit()
        await db.refresh(metric)
        logger.info("metric_ingested", server_id=body.server_id, cpu=body.cpu_usage)
        return MetricResponse.model_validate(metric)

    collector = MetricCollector()
    await collector.collect_all_server_metrics()
    logger.info("manual_metric_collection_triggered")
    return {"status": "accepted", "message": "Metric collection cycle completed."}
