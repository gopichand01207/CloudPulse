"""
tests/test_log_pipeline.py
---------------------------
Unit tests for ``logging.pipeline.LogPipeline``.

The pipeline is tested against an in-memory SQLite database (provided by
the ``async_db_session`` fixture in conftest.py) so no external services
are required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from logging.pipeline import LogPipeline
from api.models.log_entry import LogEntry


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------
def _make_raw_log(
    level: str = "INFO",
    message: str = "Service started",
    server_id: str = "web-server-01",
    structured: bool = True,
) -> str:
    """Return a raw log line, either as a JSON string or a plain-text line."""
    if structured:
        return json.dumps(
            {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "level": level,
                "server_id": server_id,
                "message": message,
                "logger": "cloudpulse.api",
            }
        )
    return f"[{datetime.now(tz=timezone.utc).isoformat()}] {level} {server_id} — {message}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def pipeline(async_db_session: AsyncSession) -> LogPipeline:
    """Return a ``LogPipeline`` connected to the in-memory test database."""
    return LogPipeline(db=async_db_session)


# ---------------------------------------------------------------------------
# Single-log ingest
# ---------------------------------------------------------------------------
class TestIngestSingleLog:
    @pytest.mark.asyncio
    async def test_ingest_single_log_persists_entry(
        self, pipeline: LogPipeline, async_db_session: AsyncSession
    ) -> None:
        """A single log line is saved as a ``LogEntry`` row."""
        raw = _make_raw_log(level="ERROR", message="Disk I/O error")
        saved = await pipeline.ingest(raw)

        assert saved is not None
        assert saved.id is not None  # DB-assigned PK
        assert saved.level == "ERROR"
        assert "Disk I/O error" in saved.message

    @pytest.mark.asyncio
    async def test_ingest_single_log_server_id(
        self, pipeline: LogPipeline
    ) -> None:
        """server_id from the log line is preserved on the persisted entry."""
        raw = _make_raw_log(server_id="db-server-02")
        saved = await pipeline.ingest(raw)
        assert saved.server_id == "db-server-02"

    @pytest.mark.asyncio
    async def test_ingest_single_log_timestamp_set(
        self, pipeline: LogPipeline
    ) -> None:
        """The persisted entry has a non-null timestamp."""
        raw = _make_raw_log()
        saved = await pipeline.ingest(raw)
        assert saved.timestamp is not None


# ---------------------------------------------------------------------------
# Batch ingest
# ---------------------------------------------------------------------------
class TestBatchIngest:
    @pytest.mark.asyncio
    async def test_batch_ingest_all_persisted(
        self, pipeline: LogPipeline
    ) -> None:
        """All 10 log lines supplied to ``ingest_batch`` are persisted."""
        raw_lines = [_make_raw_log(message=f"Event {i}") for i in range(10)]
        saved = await pipeline.ingest_batch(raw_lines)

        assert isinstance(saved, list)
        assert len(saved) == 10

    @pytest.mark.asyncio
    async def test_batch_ingest_returns_log_entry_objects(
        self, pipeline: LogPipeline
    ) -> None:
        """Every item returned by ``ingest_batch`` is a ``LogEntry`` instance."""
        raw_lines = [_make_raw_log() for _ in range(5)]
        saved = await pipeline.ingest_batch(raw_lines)

        for entry in saved:
            assert isinstance(entry, LogEntry)

    @pytest.mark.asyncio
    async def test_batch_ingest_empty_list(self, pipeline: LogPipeline) -> None:
        """Calling ``ingest_batch`` with an empty list is safe and returns []."""
        saved = await pipeline.ingest_batch([])
        assert saved == []

    @pytest.mark.asyncio
    async def test_batch_ingest_mixed_levels(self, pipeline: LogPipeline) -> None:
        """Batch with mixed log levels preserves each level correctly."""
        raw_lines = [
            _make_raw_log(level="INFO"),
            _make_raw_log(level="WARNING"),
            _make_raw_log(level="ERROR"),
            _make_raw_log(level="CRITICAL"),
        ]
        saved = await pipeline.ingest_batch(raw_lines)
        levels = {e.level for e in saved}
        assert levels == {"INFO", "WARNING", "ERROR", "CRITICAL"}


# ---------------------------------------------------------------------------
# Log-line parsing — structured (JSON)
# ---------------------------------------------------------------------------
class TestParseLogLineStructured:
    def test_parse_structured_returns_dict(self, pipeline: LogPipeline) -> None:
        """Parsing a JSON log line returns a dict (not raises)."""
        raw = _make_raw_log(structured=True, level="WARNING", message="High load")
        parsed = pipeline.parse_line(raw)

        assert isinstance(parsed, dict)

    def test_parse_structured_extracts_level(self, pipeline: LogPipeline) -> None:
        """'level' field is extracted from JSON log line."""
        raw = _make_raw_log(structured=True, level="ERROR")
        parsed = pipeline.parse_line(raw)
        assert parsed.get("level") == "ERROR"

    def test_parse_structured_extracts_message(self, pipeline: LogPipeline) -> None:
        """'message' field is extracted from JSON log line."""
        raw = _make_raw_log(structured=True, message="Connection refused")
        parsed = pipeline.parse_line(raw)
        assert parsed.get("message") == "Connection refused"

    def test_parse_structured_extracts_server_id(self, pipeline: LogPipeline) -> None:
        """'server_id' field is extracted from JSON log line."""
        raw = _make_raw_log(structured=True, server_id="app-server-03")
        parsed = pipeline.parse_line(raw)
        assert parsed.get("server_id") == "app-server-03"

    def test_parse_structured_timestamp_present(self, pipeline: LogPipeline) -> None:
        """Parsed dict has a 'timestamp' key."""
        raw = _make_raw_log(structured=True)
        parsed = pipeline.parse_line(raw)
        assert "timestamp" in parsed


# ---------------------------------------------------------------------------
# Log-line parsing — unstructured (plain text)
# ---------------------------------------------------------------------------
class TestParseLogLineUnstructured:
    def test_parse_unstructured_returns_dict(self, pipeline: LogPipeline) -> None:
        """Plain-text log lines are parsed to a dict without error."""
        raw = _make_raw_log(structured=False, level="INFO", message="Server OK")
        parsed = pipeline.parse_line(raw)
        assert isinstance(parsed, dict)

    def test_parse_unstructured_message_captured(self, pipeline: LogPipeline) -> None:
        """The message portion of the plain-text log is included in parsed output."""
        raw = _make_raw_log(structured=False, message="Disk almost full")
        parsed = pipeline.parse_line(raw)
        raw_text = parsed.get("message") or parsed.get("raw") or ""
        assert "Disk almost full" in raw_text

    def test_parse_unstructured_level_detected(self, pipeline: LogPipeline) -> None:
        """Log level token is detected from an unstructured line."""
        raw = _make_raw_log(structured=False, level="ERROR")
        parsed = pipeline.parse_line(raw)
        assert parsed.get("level") == "ERROR"

    def test_parse_unknown_format_does_not_raise(
        self, pipeline: LogPipeline
    ) -> None:
        """A completely unexpected format returns a dict (never raises)."""
        parsed = pipeline.parse_line("!!!garbled nonsense###")
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# Error-rate aggregation
# ---------------------------------------------------------------------------
class TestAggregateErrorRate:
    @pytest.mark.asyncio
    async def test_error_rate_zero_when_no_errors(
        self, pipeline: LogPipeline
    ) -> None:
        """Error rate is 0.0 when only INFO logs are present."""
        raw_lines = [_make_raw_log(level="INFO") for _ in range(10)]
        await pipeline.ingest_batch(raw_lines)

        window_start = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        rate = await pipeline.aggregate_error_rate(
            server_id="web-server-01", since=window_start
        )
        assert rate == 0.0

    @pytest.mark.asyncio
    async def test_error_rate_nonzero_when_errors_present(
        self, pipeline: LogPipeline
    ) -> None:
        """Error rate is > 0 when ERROR logs have been ingested."""
        lines = [
            _make_raw_log(level="INFO"),
            _make_raw_log(level="INFO"),
            _make_raw_log(level="ERROR"),
            _make_raw_log(level="ERROR"),
        ]
        await pipeline.ingest_batch(lines)

        window_start = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        rate = await pipeline.aggregate_error_rate(
            server_id="web-server-01", since=window_start
        )
        assert rate > 0.0

    @pytest.mark.asyncio
    async def test_error_rate_is_correct_proportion(
        self, pipeline: LogPipeline
    ) -> None:
        """
        With 2 ERROR logs out of 10 total, error rate should be 0.20
        (± small floating-point tolerance).
        """
        lines = (
            [_make_raw_log(level="INFO") for _ in range(8)]
            + [_make_raw_log(level="ERROR") for _ in range(2)]
        )
        await pipeline.ingest_batch(lines)

        window_start = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        rate = await pipeline.aggregate_error_rate(
            server_id="web-server-01", since=window_start
        )
        assert pytest.approx(rate, abs=0.05) == 0.20

    @pytest.mark.asyncio
    async def test_error_rate_empty_window(self, pipeline: LogPipeline) -> None:
        """Error rate returns 0.0 (not an exception) when the window has no logs."""
        future_start = datetime.now(tz=timezone.utc) + timedelta(hours=24)
        rate = await pipeline.aggregate_error_rate(
            server_id="web-server-01", since=future_start
        )
        assert rate == 0.0
