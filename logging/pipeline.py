"""
LogPipeline for ingestion, parsing, and error-rate aggregation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metrics import LogEntry


class LogPipeline:
    """
    High-throughput log processing pipeline supporting structured JSON
    and unstructured syslog-style lines.
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db
        # Fallback in-memory store if DB session is not active or for rapid testing
        self._memory_entries: list[LogEntry] = []

    def parse_line(self, raw_line: str) -> dict[str, Any]:
        """Parse a structured JSON log or plain-text string into a dict."""
        if not raw_line or not isinstance(raw_line, str):
            return {"level": "INFO", "message": "", "server_id": "unknown", "timestamp": datetime.now(tz=timezone.utc)}

        # Try JSON first
        trimmed = raw_line.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                data = json.loads(trimmed)
                return {
                    "level": (data.get("level") or data.get("log_level") or "INFO").upper(),
                    "message": data.get("message") or data.get("msg") or trimmed,
                    "server_id": data.get("server_id") or data.get("host") or "unknown",
                    "timestamp": data.get("timestamp") or datetime.now(tz=timezone.utc),
                    "source": data.get("logger") or data.get("source") or "system",
                }
            except Exception:
                pass

        # Unstructured text parsing
        # Pattern: [timestamp] LEVEL server_id - message
        # Or simple tokens
        level = "INFO"
        for candidate in ["CRITICAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG"]:
            if candidate in trimmed:
                level = "WARNING" if candidate == "WARN" else candidate
                break

        server_id = "unknown"
        server_match = re.search(r"(web-server-\d+|db-server-\d+|cache-server-\d+|app-server-\d+|[a-zA-Z0-9_-]+\.internal)", trimmed)
        if server_match:
            server_id = server_match.group(1)

        # Extract message: strip timestamp and level if present
        msg = trimmed
        if "—" in trimmed:
            msg = trimmed.split("—", 1)[1].strip()
        elif " - " in trimmed:
            msg = trimmed.split(" - ", 1)[1].strip()

        return {
            "level": level,
            "message": msg,
            "server_id": server_id,
            "timestamp": datetime.now(tz=timezone.utc),
            "source": "syslog",
        }

    async def ingest(self, raw_line: str) -> LogEntry:
        """Ingest a single log line, persist to DB, and return LogEntry."""
        parsed = self.parse_line(raw_line)
        ts = parsed["timestamp"]
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except Exception:
                ts = datetime.now(tz=timezone.utc)

        entry = LogEntry(
            server_id=parsed["server_id"],
            log_level=parsed["level"],
            message=parsed["message"],
            source=parsed.get("source", "system"),
            timestamp=ts,
        )

        if self.db is not None:
            self.db.add(entry)
            await self.db.flush()
            await self.db.refresh(entry)
        else:
            entry.id = len(self._memory_entries) + 1
            self._memory_entries.append(entry)

        return entry

    async def ingest_batch(self, raw_lines: list[str]) -> list[LogEntry]:
        """Ingest a batch of raw log lines."""
        if not raw_lines:
            return []

        entries: list[LogEntry] = []
        for line in raw_lines:
            parsed = self.parse_line(line)
            ts = parsed["timestamp"]
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    ts = datetime.now(tz=timezone.utc)

            entry = LogEntry(
                server_id=parsed["server_id"],
                log_level=parsed["level"],
                message=parsed["message"],
                source=parsed.get("source", "system"),
                timestamp=ts,
            )
            entries.append(entry)

        if self.db is not None:
            self.db.add_all(entries)
            await self.db.flush()
            for e in entries:
                await self.db.refresh(e)
        else:
            for e in entries:
                e.id = len(self._memory_entries) + 1
                self._memory_entries.append(e)

        return entries

    async def aggregate_error_rate(self, server_id: str, since: datetime) -> float:
        """Calculate the proportion of error logs (ERROR/CRITICAL) for server_id since window."""
        if self.db is not None:
            # Query count of total logs
            q_total = select(func.count(LogEntry.id)).where(
                LogEntry.server_id == server_id,
                LogEntry.timestamp >= since,
            )
            total = (await self.db.execute(q_total)).scalar_one()
            if total == 0:
                return 0.0

            q_err = select(func.count(LogEntry.id)).where(
                LogEntry.server_id == server_id,
                LogEntry.timestamp >= since,
                LogEntry.log_level.in_(["ERROR", "CRITICAL"]),
            )
            errors = (await self.db.execute(q_err)).scalar_one()
            return float(errors) / float(total)

        # In-memory calculation
        relevant = [
            e for e in self._memory_entries
            if e.server_id == server_id and e.timestamp >= since
        ]
        if not relevant:
            return 0.0
        errors = sum(1 for e in relevant if e.log_level in ("ERROR", "CRITICAL"))
        return float(errors) / float(len(relevant))
