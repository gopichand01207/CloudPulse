"""
Alerts API router — /api/v1/alerts
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.schemas import AlertResponse, AlertStats, PaginatedResponse
from app.models.metrics import AlertEvent, AlertSeverity, ServerMetric
from app.services.alert_engine import AlertEngine

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("/", response_model=PaginatedResponse[AlertResponse])
async def list_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    severity: AlertSeverity | None = Query(None, description="Filter by severity level."),
    is_resolved: bool | None = Query(None, description="Filter by resolution status."),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AlertResponse]:
    """List alerts with optional severity and resolution filters."""

    base_q = select(AlertEvent).order_by(AlertEvent.triggered_at.desc())
    count_q = select(func.count()).select_from(AlertEvent)

    if severity:
        base_q = base_q.where(AlertEvent.severity == severity)
        count_q = count_q.where(AlertEvent.severity == severity)
    if is_resolved is not None:
        base_q = base_q.where(AlertEvent.is_resolved == is_resolved)
        count_q = count_q.where(AlertEvent.is_resolved == is_resolved)

    total = (await db.execute(count_q)).scalar_one()
    items = list((await db.execute(base_q.offset(skip).limit(limit))).scalars().all())

    return PaginatedResponse[AlertResponse](
        total=total,
        skip=skip,
        limit=limit,
        items=[AlertResponse.model_validate(a) for a in items],
    )


# ---------------------------------------------------------------------------
# GET /active
# ---------------------------------------------------------------------------


@router.get("/active", response_model=list[AlertResponse])
async def list_active_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertResponse]:
    """Return all unresolved alerts ordered by severity (CRITICAL first)."""

    _severity_order = {
        AlertSeverity.CRITICAL: 0,
        AlertSeverity.HIGH: 1,
        AlertSeverity.MEDIUM: 2,
        AlertSeverity.LOW: 3,
    }

    result = await db.execute(
        select(AlertEvent)
        .where(AlertEvent.is_resolved.is_(False))
        .order_by(AlertEvent.triggered_at.desc())
    )
    alerts = list(result.scalars().all())
    alerts.sort(key=lambda a: _severity_order.get(a.severity, 99))

    return [AlertResponse.model_validate(a) for a in alerts]


# ---------------------------------------------------------------------------
# POST /resolve/{alert_id}
# ---------------------------------------------------------------------------


@router.post("/resolve/{alert_id}", response_model=AlertResponse)
async def resolve_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """Mark a specific alert as resolved."""

    result = await db.execute(select(AlertEvent).where(AlertEvent.id == alert_id))
    alert = result.scalar_one_or_none()

    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found.",
        )
    if alert.is_resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} is already resolved.",
        )

    alert.is_resolved = True
    alert.resolved_at = datetime.now(tz=timezone.utc)
    await db.flush()
    await db.refresh(alert)

    logger.info("alert_manually_resolved", alert_id=alert_id)
    return AlertResponse.model_validate(alert)


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=AlertStats)
async def get_alert_stats(db: AsyncSession = Depends(get_db)) -> AlertStats:
    """Return aggregate statistics: count by severity, unresolved count, avg resolution time."""

    # Count by severity
    sev_result = await db.execute(
        select(AlertEvent.severity, func.count(AlertEvent.id).label("cnt"))
        .group_by(AlertEvent.severity)
    )
    by_severity = {row[0]: row[1] for row in sev_result.fetchall()}

    # Total & unresolved
    total_result = await db.execute(select(func.count()).select_from(AlertEvent))
    total = total_result.scalar_one()

    unresolved_result = await db.execute(
        select(func.count()).select_from(AlertEvent).where(AlertEvent.is_resolved.is_(False))
    )
    unresolved = unresolved_result.scalar_one()

    # Avg resolution time (seconds) for resolved alerts
    avg_result = await db.execute(
        select(
            func.avg(
                func.extract("epoch", AlertEvent.resolved_at)
                - func.extract("epoch", AlertEvent.triggered_at)
            )
        ).where(AlertEvent.is_resolved.is_(True), AlertEvent.resolved_at.isnot(None))
    )
    avg_resolution = avg_result.scalar_one()

    return AlertStats(
        total=total,
        by_severity=by_severity,
        unresolved=unresolved,
        avg_resolution_time_seconds=round(avg_resolution, 2) if avg_resolution else None,
    )


# ---------------------------------------------------------------------------
# POST /test
# ---------------------------------------------------------------------------


@router.post("/test", status_code=status.HTTP_200_OK)
async def trigger_test_alert(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Create and dispatch a test alert notification.
    Uses the first ServerMetric in the DB; if none exist, returns a 404.
    """

    result = await db.execute(select(ServerMetric).limit(1))
    metric = result.scalar_one_or_none()

    if metric is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No server metrics exist yet. Run /api/v1/metrics/collect first.",
        )

    test_alert = AlertEvent(
        metric_id=metric.id,
        alert_type="test_alert",
        severity=AlertSeverity.LOW,
        message=(
            f"This is a test alert from CloudPulse for server '{metric.server_name}'. "
            "No action required."
        ),
        triggered_at=datetime.now(tz=timezone.utc),
        is_resolved=False,
    )
    db.add(test_alert)
    await db.flush()
    await db.refresh(test_alert)

    engine = AlertEngine()
    try:
        engine.send_alert_notification(test_alert)
    except Exception as exc:  # noqa: BLE001
        logger.warning("test_alert_notification_failed", error=str(exc))

    logger.info("test_alert_dispatched", alert_id=test_alert.id)
    return {
        "status": "ok",
        "alert_id": test_alert.id,
        "message": "Test alert created and notification dispatched.",
    }
