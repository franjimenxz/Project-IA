"""Routers `create_app` mounts.

Included routers are not flattened into `app.routes` on this FastAPI version,
so the mounted surface is read from the OpenAPI document and confirmed with a
request.
"""

from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app

ONBOARDING_PATHS = frozenset(
    {
        "/v1/admin/tenants/provision",
        "/v1/admin/tenants/{slug}",
        "/v1/admin/tenants/{slug}/disable",
        "/v1/admin/tenants/{slug}/preflight",
        "/v1/admin/tenants/{slug}/activate",
    }
)


def test_liveness_does_not_require_dependencies():
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_onboarding_router_is_mounted():
    assert ONBOARDING_PATHS <= set(create_app().openapi()["paths"])


def test_onboarding_router_is_mounted_in_production():
    paths = set(create_app(environment="production").openapi()["paths"])
    assert ONBOARDING_PATHS <= paths
    assert "/v1/simulated/messages" not in paths


def test_mounted_onboarding_refuses_an_anonymous_caller():
    """No process identity is published, so the tenant surface stays closed."""
    response = TestClient(create_app(environment="production")).get(
        "/v1/admin/tenants/tenant-b"
    )
    assert response.status_code == 401
