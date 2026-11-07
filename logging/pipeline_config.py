"""
logging/pipeline_config.py
---------------------------
Logging pipeline configuration for CloudPulse.

Provides:
* :func:`configure_structlog` — configure structlog for the current environment.
* :func:`get_logger` — return a bound structlog logger by name.
* :class:`LogLevel` — enum of supported log levels.
* :class:`PipelineConfig` — dataclass with pipeline-tuning parameters.

Usage::

    from logging.pipeline_config import configure_structlog, get_logger, PipelineConfig

    # Call once at application startup
    configure_structlog()

    logger = get_logger(__name__)
    logger.info("Server started", port=8000)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog


# ──────────────────────────────────────────────────────────────────────────────
# Log-level enum
# ──────────────────────────────────────────────────────────────────────────────


class LogLevel(str, Enum):
    """
    Supported application log levels.

    Values match Python's :mod:`logging` level names so they can be passed
    directly to :func:`logging.basicConfig`.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline configuration dataclass
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PipelineConfig:
    """
    Runtime configuration for the CloudPulse log-ingestion pipeline.

    Attributes
    ----------
    batch_size:
        Maximum number of log entries to accumulate before flushing to the
        database.  A smaller value reduces latency; a larger value improves
        throughput.  Default: ``100``.
    flush_interval_seconds:
        Seconds between automatic flushes when the batch is not yet full.
        Default: ``5``.
    max_retention_days:
        Number of days to retain log entries in the database before they are
        eligible for pruning.  Default: ``30``.
    log_level:
        Minimum severity level emitted by the application logger.
        Default: ``LogLevel.INFO``.
    enable_json_renderer:
        When ``True`` (production) the structlog renderer outputs JSON.
        When ``False`` (development) it uses a human-friendly coloured
        console renderer.  Defaults to ``True`` in production environments.
    """

    batch_size: int = 100
    flush_interval_seconds: int = 5
    max_retention_days: int = 30
    log_level: LogLevel = LogLevel.INFO
    enable_json_renderer: bool = field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "development") == "production"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Structlog configuration
# ──────────────────────────────────────────────────────────────────────────────

#: Module-level sentinel so that structlog is only configured once.
_configured: bool = False


def configure_structlog(config: PipelineConfig | None = None) -> None:
    """
    Configure structlog for the CloudPulse application.

    Call **once** at application startup (e.g. in ``api/main.py``
    lifespan or ``scripts/init_db.py``).  Subsequent calls are no-ops.

    Parameters
    ----------
    config:
        Optional :class:`PipelineConfig`.  When omitted a default instance
        is created, which reads ``ENVIRONMENT`` from the environment.

    Behaviour
    ---------
    * **Production** (``ENVIRONMENT=production``): JSON renderer — machine-
      parseable output suitable for log-aggregation pipelines (e.g. AWS
      CloudWatch Logs, Datadog).
    * **Development** (default): :class:`structlog.dev.ConsoleRenderer` —
      coloured, human-friendly output.

    In both modes the following processors are applied in order:

    1. Add log level as a string field.
    2. Add ISO-8601 timestamp.
    3. Inject ``call_site`` info (file, line number) in DEBUG mode.
    4. Format exception info.
    5. Render to the target format (JSON or console).
    """
    global _configured
    if _configured:
        return

    if config is None:
        config = PipelineConfig()

    # ── Standard-library logging bridge ──────────────────────────────────────
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, config.log_level.value, logging.INFO),
    )

    # ── Shared processors applied to every log event ──────────────────────────
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # ── Environment-specific final renderer ──────────────────────────────────
    if config.enable_json_renderer:
        # Production: emit compact JSON (one object per line)
        final_renderer: Any = structlog.processors.JSONRenderer()
    else:
        # Development: coloured, indented console output
        final_renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [final_renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.log_level.value, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Return a structlog bound logger for the given module name.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.

    Returns
    -------
    structlog.stdlib.BoundLogger
        A logger pre-bound with ``logger=name`` for every emitted event.

    Example
    -------
    ::

        log = get_logger(__name__)
        log.info("Metric collected", server_id="web-server-01", cpu=72.3)
    """
    return structlog.get_logger(name)


# ──────────────────────────────────────────────────────────────────────────────
# Default singleton config (used by pipeline.py)
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_PIPELINE_CONFIG: PipelineConfig = PipelineConfig()
"""
Pre-instantiated pipeline configuration using environment-aware defaults.

Import and pass this to :class:`~logging.pipeline.LogPipeline` when
no custom tuning is needed::

    from logging.pipeline_config import DEFAULT_PIPELINE_CONFIG
    from logging.pipeline import LogPipeline

    pipeline = LogPipeline(db=session, config=DEFAULT_PIPELINE_CONFIG)
"""
