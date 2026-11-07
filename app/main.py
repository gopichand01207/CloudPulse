"""
CloudPulse: Infrastructure & Microservices Observability Platform
Main FastAPI application entry point.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api import alerts, health, metrics, services
from app.core.config import settings
from app.core.database import init_db
from app.services.collector import MetricCollector

# ---------------------------------------------------------------------------
# Structlog / stdlib logging configuration
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(message)s",
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Background metric collection
# ---------------------------------------------------------------------------

_collector_task: asyncio.Task | None = None


async def collect_metrics_loop() -> None:
    """Background loop that collects metrics every METRICS_COLLECTION_INTERVAL seconds."""
    collector = MetricCollector()
    logger.info(
        "metric_collection_loop_started",
        interval=settings.METRICS_COLLECTION_INTERVAL,
    )
    while True:
        try:
            await collector.collect_all_server_metrics()
            logger.debug("metric_collection_cycle_complete")
        except Exception as exc:  # noqa: BLE001
            logger.error("metric_collection_error", error=str(exc), exc_info=True)
        await asyncio.sleep(settings.METRICS_COLLECTION_INTERVAL)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    """Application lifespan: startup -> yield -> shutdown."""
    global _collector_task  # noqa: PLW0603

    logger.info("cloudpulse_startup", version=settings.VERSION)

    # Initialise database tables (fails gracefully if DB not reachable yet)
    try:
        await init_db()
    except Exception as exc:
        logger.warning("db_init_skipped_or_deferred", error=str(exc))

    # Start background metric collection
    _collector_task = asyncio.create_task(collect_metrics_loop(), name="metric_collector")

    yield

    # Graceful shutdown
    if _collector_task and not _collector_task.done():
        _collector_task.cancel()
        try:
            await _collector_task
        except asyncio.CancelledError:
            pass
    logger.info("cloudpulse_shutdown")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CloudPulse: Infrastructure & Microservices Observability",
    description=(
        "Real-time monitoring platform for cloud infrastructure and microservices. "
        "Collects server metrics, evaluates alert thresholds, aggregates logs, "
        "and exposes a rich REST API for dashboards."
    ),
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Prometheus instrumentation (with fallback)
# ---------------------------------------------------------------------------

try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/health"],
        inprogress_name="cloudpulse_inprogress_requests",
        inprogress_labels=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except ImportError:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["Metrics"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(health.router, prefix="/api/v1/health", tags=["Health"])
app.include_router(services.router, prefix="/api/v1/services", tags=["Services"])


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
