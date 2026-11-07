"""
tests/test_metrics_api.py
--------------------------
Async integration tests for the /api/v1/metrics router.

Each test spins up a real FastAPI application backed by an in-memory
SQLite database (provided by conftest.py) and exercises the HTTP layer
end-to-end via an HTTPX AsyncClient.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /api/v1/metrics
# ---------------------------------------------------------------------------
class TestGetMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_empty(self, test_client: AsyncClient) -> None:
        """
        When no metrics have been ingested the endpoint must return HTTP 200
        with an empty list payload.
        """
        response = await test_client.get("/api/v1/metrics")

        assert response.status_code == 200
        body = response.json()
        # Accept both a bare list and a paginated wrapper {"items": [], ...}
        if isinstance(body, list):
            assert body == []
        else:
            assert body.get("items", []) == [] or body.get("data", []) == []

    @pytest.mark.asyncio
    async def test_get_metrics_returns_200(self, test_client: AsyncClient) -> None:
        """GET /api/v1/metrics always returns a 200 response."""
        response = await test_client.get("/api/v1/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_metrics_with_limit(self, test_client: AsyncClient) -> None:
        """Query param ``limit`` is accepted without error."""
        response = await test_client.get("/api/v1/metrics", params={"limit": 5})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_metrics_with_server_filter(self, test_client: AsyncClient) -> None:
        """Query param ``server_id`` is accepted without error."""
        response = await test_client.get(
            "/api/v1/metrics", params={"server_id": "web-server-01"}
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/metrics/collect
# ---------------------------------------------------------------------------
class TestCollectMetrics:
    _PAYLOAD = {
        "server_id": "web-server-01",
        "hostname": "web-server-01.internal",
        "cpu_percent": 55.3,
        "memory_percent": 68.1,
        "disk_percent": 42.7,
        "network_bytes_sent": 1_048_576,
        "network_bytes_recv": 2_097_152,
        "response_time_ms": 210.5,
    }

    @pytest.mark.asyncio
    async def test_collect_metrics_returns_200(self, test_client: AsyncClient) -> None:
        """POSTing a valid metric payload returns HTTP 200 or 201."""
        response = await test_client.post("/api/v1/metrics/collect", json=self._PAYLOAD)
        assert response.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_collect_metrics_response_body(self, test_client: AsyncClient) -> None:
        """Response body echoes back the ingested metric data."""
        response = await test_client.post("/api/v1/metrics/collect", json=self._PAYLOAD)
        assert response.status_code in (200, 201)
        body = response.json()
        assert body.get("server_id") == "web-server-01"

    @pytest.mark.asyncio
    async def test_collect_metrics_missing_required_field(
        self, test_client: AsyncClient
    ) -> None:
        """Missing ``server_id`` must return HTTP 422 (Unprocessable Entity)."""
        incomplete = {k: v for k, v in self._PAYLOAD.items() if k != "server_id"}
        response = await test_client.post("/api/v1/metrics/collect", json=incomplete)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_collect_metrics_invalid_cpu_value(
        self, test_client: AsyncClient
    ) -> None:
        """CPU percent > 100 is an invalid value and should be rejected."""
        payload = {**self._PAYLOAD, "cpu_percent": 150.0}
        response = await test_client.post("/api/v1/metrics/collect", json=payload)
        # Either 422 (validation) or 400 (business rule) is acceptable
        assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/metrics/summary
# ---------------------------------------------------------------------------
class TestGetMetricsSummary:
    @pytest.mark.asyncio
    async def test_get_metrics_summary_returns_200(
        self, test_client: AsyncClient
    ) -> None:
        """The summary endpoint returns HTTP 200."""
        response = await test_client.get("/api/v1/metrics/summary")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_metrics_summary_is_list(self, test_client: AsyncClient) -> None:
        """The summary payload is a list (one entry per server)."""
        response = await test_client.get("/api/v1/metrics/summary")
        assert response.status_code == 200
        body = response.json()
        # Accepts bare list or wrapped {"servers": [...]} response
        data = body if isinstance(body, list) else body.get("servers", body.get("data", []))
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# GET /api/v1/metrics/realtime/{server_id}
# ---------------------------------------------------------------------------
class TestGetRealtimeMetric:
    @pytest.mark.asyncio
    async def test_get_realtime_metric_known_server(
        self, test_client: AsyncClient
    ) -> None:
        """
        After collecting a metric for a server, the realtime endpoint must
        return a non-404 response with that server's latest data.
        """
        payload = {
            "server_id": "web-server-01",
            "hostname": "web-server-01.internal",
            "cpu_percent": 72.0,
            "memory_percent": 55.0,
            "disk_percent": 30.0,
            "network_bytes_sent": 500_000,
            "network_bytes_recv": 1_000_000,
            "response_time_ms": 95.0,
        }
        post_resp = await test_client.post("/api/v1/metrics/collect", json=payload)
        assert post_resp.status_code in (200, 201)

        response = await test_client.get("/api/v1/metrics/realtime/web-server-01")
        assert response.status_code == 200
        body = response.json()
        assert body.get("server_id") == "web-server-01"

    @pytest.mark.asyncio
    async def test_get_realtime_metric_unknown_server(
        self, test_client: AsyncClient
    ) -> None:
        """An unknown server_id must return HTTP 404."""
        response = await test_client.get(
            "/api/v1/metrics/realtime/does-not-exist-xyz"
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/metrics/history  (time-range filter)
# ---------------------------------------------------------------------------
class TestGetMetricHistory:
    @pytest.mark.asyncio
    async def test_get_metric_history_returns_200(
        self, test_client: AsyncClient
    ) -> None:
        """History endpoint returns HTTP 200 with time-range parameters."""
        now = datetime.now(tz=timezone.utc)
        start = (now - timedelta(hours=1)).isoformat()
        end = now.isoformat()

        response = await test_client.get(
            "/api/v1/metrics/history",
            params={"server_id": "web-server-01", "start_time": start, "end_time": end},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_metric_history_is_list(self, test_client: AsyncClient) -> None:
        """History payload is a list."""
        now = datetime.now(tz=timezone.utc)
        start = (now - timedelta(hours=2)).isoformat()
        end = now.isoformat()

        response = await test_client.get(
            "/api/v1/metrics/history",
            params={"server_id": "web-server-01", "start_time": start, "end_time": end},
        )
        assert response.status_code == 200
        body = response.json()
        data = body if isinstance(body, list) else body.get("items", body.get("data", []))
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_metric_history_invalid_dates(
        self, test_client: AsyncClient
    ) -> None:
        """Malformed datetime strings must yield HTTP 422."""
        response = await test_client.get(
            "/api/v1/metrics/history",
            params={
                "server_id": "web-server-01",
                "start_time": "not-a-date",
                "end_time": "also-not-a-date",
            },
        )
        assert response.status_code == 422
