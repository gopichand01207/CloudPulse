"""
tests/conftest.py
-----------------
Shared pytest fixtures for the CloudPulse test suite.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Generator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import importlib.util
_pipe_path = ROOT / "logging" / "pipeline.py"
if _pipe_path.exists():
    _spec = importlib.util.spec_from_file_location("logging.pipeline", _pipe_path)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["logging.pipeline"] = _mod
    _spec.loader.exec_module(_mod)

import pytest

import importlib.util
_pipe_path = ROOT / "logging" / "pipeline.py"
if _pipe_path.exists():
    _spec = importlib.util.spec_from_file_location("logging.pipeline", _pipe_path)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["logging.pipeline"] = _mod
    _spec.loader.exec_module(_mod)

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from app.main import app
from app.core.database import get_db, Base
from app.models.metrics import ServerMetric, AlertEvent, LogEntry, ServiceHealth, AlertSeverity, ServerStatus

# ---------------------------------------------------------------------------
# In-memory SQLite engine for tests
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="function", autouse=True)
async def create_test_tables() -> AsyncGenerator[None, None]:
    """Create all ORM tables in the in-memory database per test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session backed by in-memory SQLite."""
    async with TestSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def test_client(async_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTPX client wired to FastAPI app using ASGITransport."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Domain-object fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_server_metric() -> ServerMetric:
    """Return an unsaved ServerMetric instance."""
    return ServerMetric(
        server_id="web-server-01",
        server_name="web-server-01",
        cpu_usage=42.5,
        memory_usage=61.3,
        disk_usage=55.0,
        network_in=1_048_576.0,
        network_out=2_097_152.0,
        status=ServerStatus.RUNNING,
        timestamp=datetime.now(tz=timezone.utc),
    )


@pytest.fixture()
def sample_alert() -> AlertEvent:
    """Return an unsaved AlertEvent instance."""
    return AlertEvent(
        metric_id=1,
        alert_type="cpu_high",
        severity=AlertSeverity.CRITICAL,
        message="CPU utilisation 91.2% exceeds CRITICAL threshold of 85%",
        is_resolved=False,
        triggered_at=datetime.now(tz=timezone.utc),
    )
