"""
LogPipeline — ingests, parses, and queries server log entries.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metrics import LogEntry

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex for structured log parsing (common formats)
# ---------------------------------------------------------------------------

# Matches: 2024-01-15T12:30:00Z [ERROR] myapp: something went wrong
_STRUCTURED_RE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"\[(?P<level>[A-Z]+)\]\s+"
    r"(?P<source>[^\s:]+):\s+"
    r"(?P<message>.+)",
    re.DOTALL,
)

# Fallback: leading log-level keyword
_LEVEL_RE = re.compile(
    r"^(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\s*[:\-]?\s*(?P<message>.+)",
    re.IGNORECASE | re.DOTALL,
)

_LEVEL_MAP = {
    "WARN": "WARNING",
    "FATAL": "CRITICAL",
}


class LogPipeline:
    """Handles log ingestion, parsing, storage, and querying."""

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def ingest_log(
        self,
        session: AsyncSession,
        server_id: str,
        log_level: str,
        message: str,
        source: str = "unknown",
    ) -> LogEntry:
        """Create and persist a single log entry."""
        normalized_level = _LEVEL_MAP.get(log_level.upper(), log_level.upper())
        entry = LogEntry(
            server_id=server_id,
            log_level=normalized_level,
            message=message.strip(),
            source=source,
            timestamp=datetime.now(tz=timezone.utc),
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        logger.debug("log_ingested", server_id=server_id, level=normalized_level)
        return entry

    async def batch_ingest(
        self, session: AsyncSession, log_entries: list[dict]
    ) -> list[LogEntry]:
        """
        Bulk-insert log entries.

        Each dict must contain: server_id, log_level, message.
        Optional keys: source, timestamp.
        """
        objects: list[LogEntry] = []
        for entry in log_entries:
            normalized_level = _LEVEL_MAP.get(
                entry["log_level"].upper(), entry["log_level"].upper()
            )
            obj = LogEntry(
                server_id=entry["server_id"],
                log_level=normalized_level,
                message=entry["message"].strip(),
                source=entry.get("source", "unknown"),
                timestamp=entry.get("timestamp", datetime.now(tz=timezone.utc)),
            )
            session.add(obj)
            objects.append(obj)

        await session.flush()
        for obj in objects:
            await session.refresh(obj)

        logger.info("batch_log_ingested", count=len(objects))
        return objects

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_log_line(self, raw_line: str) -> dict:
        """
        Parse a raw log line into a structured dict.

        Returns keys: level, message, source, timestamp (or None).
        """
        raw_line = raw_line.strip()

        # Try structured format first
        m = _STRUCTURED_RE.match(raw_line)
        if m:
            level = _LEVEL_MAP.get(m.group("level"), m.group("level"))
            ts_str = m.group("timestamp")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                ts = None
            return {
                "level": level,
                "message": m.group("message").strip(),
                "source": m.group("source"),
                "timestamp": ts,
            }

        # Try level-prefixed format
        m2 = _LEVEL_RE.match(raw_line)
        if m2:
            level = _LEVEL_MAP.get(m2.group("level").upper(), m2.group("level").upper())
            return {
                "level": level,
                "message": m2.group("message").strip(),
                "source": "unknown",
                "timestamp": None,
            }

        # Fallback: treat as INFO
        return {
            "level": "INFO",
            "message": raw_line,
            "source": "unknown",
            "timestamp": None,
        }

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    async def tail_logs(
        self,
        session: AsyncSession,
        server_id: str,
        limit: int = 100,
    ) -> list[LogEntry]:
        """Return the most recent `limit` log entries for a server."""
        result = await session.execute(
            select(LogEntry)
            .where(LogEntry.server_id == server_id)
            .order_by(LogEntry.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def aggregate_error_rate(
        self,
        session: AsyncSession,
        server_id: str,
        window_minutes: int = 5,
    ) -> dict:
        """
        Count ERROR and CRITICAL log entries within the last `window_minutes` minutes.

        Returns a dict with keys: server_id, window_minutes, error_count, critical_count, total.
        """
        since = datetime.now(tz=timezone.utc) - timedelta(minutes=window_minutes)

        result = await session.execute(
            select(LogEntry.log_level, func.count(LogEntry.id).label("cnt"))
            .where(
                LogEntry.server_id == server_id,
                LogEntry.log_level.in_(["ERROR", "CRITICAL"]),
                LogEntry.timestamp >= since,
            )
            .group_by(LogEntry.log_level)
        )
        rows = result.fetchall()
        counts = {row[0]: row[1] for row in rows}

        error_count = counts.get("ERROR", 0)
        critical_count = counts.get("CRITICAL", 0)

        return {
            "server_id": server_id,
            "window_minutes": window_minutes,
            "error_count": error_count,
            "critical_count": critical_count,
            "total": error_count + critical_count,
        }
