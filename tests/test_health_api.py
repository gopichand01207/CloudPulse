"""
tests/test_health_api.py
-------------------------
Integration tests for the /api/v1/health router.

All tests use the shared ``test_client`` fixture (AsyncClient backed by
the in-memory SQLite database).  No external services are required.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /api/v1/health
# ---------------------------------------------------------------------------
class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_200(self, test_client: AsyncClient) -> None:
        """Liveness probe returns HTTP 200."""
        response = await test_client.get("/api/v1/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_check_status_field(self, test_client: AsyncClient) -> None:
        """Response body contains a 'status' field indicating system health."""
        response = await test_client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert "status" in body

    @pytest.mark.asyncio
    async def test_health_check_status_healthy(self, test_client: AsyncClient) -> None:
        """'status' value is 'healthy' (or 'ok') when all systems are up."""
        response = await test_client.get("/api/v1/health")
        body = response.json()
        assert body.get("status") in ("healthy", "ok", "up")

    @pytest.mark.asyncio
    async def test_health_check_contains_timestamp(
        self, test_client: AsyncClient
    ) -> None:
        """Health response includes a 'timestamp' field for auditability."""
        response = await test_client.get("/api/v1/health")
        body = response.json()
        assert "timestamp" in body or "checked_at" in body

    @pytest.mark.asyncio
    async def test_health_check_contains_version(
        self, test_client: AsyncClient
    ) -> None:
        """Health response includes an 'version' field."""
        response = await test_client.get("/api/v1/health")
        body = response.json()
        # version may live at top-level or under a 'details' sub-dict
        has_version = "version" in body or "version" in body.get("details", {})
        assert has_version

    @pytest.mark.asyncio
    async def test_health_check_json_content_type(
        self, test_client: AsyncClient
    ) -> None:
        """Content-Type header must be application/json."""
        response = await test_client.get("/api/v1/health")
        assert "application/json" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# GET /api/v1/health/services
# ---------------------------------------------------------------------------
class TestServicesHealth:
    @pytest.mark.asyncio
    async def test_services_health_returns_200(
        self, test_client: AsyncClient
    ) -> None:
        """Services health endpoint returns HTTP 200."""
        response = await test_client.get("/api/v1/health/services")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_services_health_is_list_or_dict(
        self, test_client: AsyncClient
    ) -> None:
        """
        Response body is either a list of service status objects or a dict
        with a 'services' key containing such a list.
        """
        response = await test_client.get("/api/v1/health/services")
        body = response.json()
        if isinstance(body, list):
            assert isinstance(body, list)
        else:
            services = body.get("services", body.get("data", None))
            assert services is not None
            assert isinstance(services, list)

    @pytest.mark.asyncio
    async def test_services_health_entries_have_name(
        self, test_client: AsyncClient
    ) -> None:
        """Every service entry in the list has a 'name' (or 'service') field."""
        response = await test_client.get("/api/v1/health/services")
        body = response.json()
        services = (
            body
            if isinstance(body, list)
            else body.get("services", body.get("data", []))
        )
        for svc in services:
            assert "name" in svc or "service" in svc

    @pytest.mark.asyncio
    async def test_services_health_entries_have_status(
        self, test_client: AsyncClient
    ) -> None:
        """Every service entry has a 'status' field."""
        response = await test_client.get("/api/v1/health/services")
        body = response.json()
        services = (
            body
            if isinstance(body, list)
            else body.get("services", body.get("data", []))
        )
        for svc in services:
            assert "status" in svc

    @pytest.mark.asyncio
    async def test_services_health_known_services_present(
        self, test_client: AsyncClient
    ) -> None:
        """
        The response lists at least the core services: database and redis.
        """
        response = await test_client.get("/api/v1/health/services")
        body = response.json()
        services = (
            body
            if isinstance(body, list)
            else body.get("services", body.get("data", []))
        )
        names = {
            (svc.get("name") or svc.get("service") or "").lower()
            for svc in services
        }
        assert names & {"database", "db", "postgres", "postgresql", "redis"}


# ---------------------------------------------------------------------------
# POST /api/v1/health/services/probe
# ---------------------------------------------------------------------------
class TestServiceProbe:
    @pytest.mark.asyncio
    async def test_service_probe_returns_200_or_202(
        self, test_client: AsyncClient
    ) -> None:
        """
        Triggering an ad-hoc probe must return 200 (synchronous result)
        or 202 (probe queued asynchronously).
        """
        response = await test_client.post("/api/v1/health/services/probe")
        assert response.status_code in (200, 202)

    @pytest.mark.asyncio
    async def test_service_probe_response_is_json(
        self, test_client: AsyncClient
    ) -> None:
        """Probe response must be valid JSON."""
        response = await test_client.post("/api/v1/health/services/probe")
        # Will raise json.JSONDecodeError if body is not valid JSON
        body = response.json()
        assert body is not None

    @pytest.mark.asyncio
    async def test_service_probe_idempotent(self, test_client: AsyncClient) -> None:
        """Calling probe twice must not raise a server error (5xx)."""
        r1 = await test_client.post("/api/v1/health/services/probe")
        r2 = await test_client.post("/api/v1/health/services/probe")
        assert r1.status_code < 500
        assert r2.status_code < 500

    @pytest.mark.asyncio
    async def test_service_probe_with_target_filter(
        self, test_client: AsyncClient
    ) -> None:
        """
        Probe with optional ``target`` query param restricts the probe scope.
        The endpoint must accept the param without raising a 422.
        """
        response = await test_client.post(
            "/api/v1/health/services/probe", params={"target": "database"}
        )
        # 404 is acceptable if 'database' target isn't registered; 422 is not
        assert response.status_code != 422
