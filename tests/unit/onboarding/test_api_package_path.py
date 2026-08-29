"""`package_path` containment at the onboarding HTTP boundary.

No PostgreSQL is required: the service is a stub, so no endpoint reaches a
database. The containment rule belongs to the HTTP boundary and not to
`load_tenant_package`, which the CLI calls with operator-supplied local paths.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ia_mcp.onboarding.api import create_onboarding_router
from ia_mcp.onboarding.commands import Principal, ProvisionedTenant
from ia_mcp.onboarding.models import TenantPackage
from ia_mcp.onboarding.preflight import PreflightReport
from ia_mcp.onboarding.service import TenantOnboardingService
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.fixtures.admin_auth import admin_authenticator, bearer
from tests.unit.onboarding.helpers import write_package

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)
TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")
SLUG = "tenant-b"
TOKEN = "svctest-package-path-token"
ZERO_HASH = "0" * 64
ONE_HASH = "1" * 64


def _tenant(slug: str) -> ProvisionedTenant:
    return ProvisionedTenant(
        identity=TenantIdentity(tenant_id=TENANT_ID, tenant_slug=slug),
        status="disabled",
        config_version=1,
        config_status="draft",
    )


class StubOnboardingService(TenantOnboardingService):
    """Records what crossed the boundary; never opens a database session."""

    def __init__(self) -> None:
        self.packages: list[TenantPackage] = []
        self.content_hashes: list[str] = []

    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None:
        return _tenant(slug)

    async def provision(
        self, package: TenantPackage, actor: Principal
    ) -> ProvisionedTenant:
        self.packages.append(package)
        return _tenant(package.tenant.slug)

    async def preflight(
        self, tenant: TenantContext, *, content_hash: str
    ) -> PreflightReport:
        self.content_hashes.append(content_hash)
        return PreflightReport(
            report_hash=ZERO_HASH,
            tenant_id=tenant.tenant_id,
            content_hash=content_hash,
            config_hash=ONE_HASH,
            passed=True,
            checks=(),
        )


def _client(
    service: TenantOnboardingService | None,
    *,
    packages_dir: Path | None = None,
    principal: Principal | None = PLATFORM,
) -> TestClient:
    """A client that presents `TOKEN`, authenticated as `principal`."""
    app = FastAPI()
    app.include_router(create_onboarding_router())
    if service is not None:
        app.state.onboarding_service = service
    if packages_dir is not None:
        app.state.tenant_packages_dir = packages_dir
    if principal is not None:
        app.state.admin_authenticator = admin_authenticator({TOKEN: principal})
    return TestClient(app, headers=bearer(TOKEN))


def _escaping_symlink(tmp_path: Path) -> tuple[Path, str]:
    """A valid package outside the root, reachable through a link inside it."""
    root = tmp_path / "packages"
    root.mkdir()
    outside = write_package(tmp_path / "outside")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    return root, "linked"


def test_provision_without_a_configured_root_is_refused(tmp_path: Path) -> None:
    service = StubOnboardingService()
    package = write_package(tmp_path / "b")
    response = _client(service).post(
        "/v1/admin/tenants/provision",
        json={"package_path": str(package)},
    )
    assert response.status_code == 503
    assert service.packages == []
    assert str(tmp_path) not in response.text


def test_provision_accepts_a_package_inside_the_root(tmp_path: Path) -> None:
    service = StubOnboardingService()
    write_package(tmp_path / "b")
    response = _client(service, packages_dir=tmp_path).post(
        "/v1/admin/tenants/provision",
        json={"package_path": "b"},
    )
    assert response.status_code == 200
    assert response.json()["slug"] == SLUG
    assert [item.tenant.slug for item in service.packages] == [SLUG]


def test_provision_accepts_an_absolute_path_inside_the_root(tmp_path: Path) -> None:
    service = StubOnboardingService()
    package = write_package(tmp_path / "b")
    response = _client(service, packages_dir=tmp_path).post(
        "/v1/admin/tenants/provision",
        json={"package_path": str(package)},
    )
    assert response.status_code == 200
    assert [item.tenant.slug for item in service.packages] == [SLUG]


@pytest.mark.parametrize("shape", ["absolute", "parent", "embedded_parent"])
def test_provision_rejects_a_valid_package_outside_the_root(
    tmp_path: Path, shape: str
) -> None:
    """A readable package elsewhere on the host must not cross the boundary."""
    service = StubOnboardingService()
    root = tmp_path / "packages"
    root.mkdir()
    outside = write_package(tmp_path / "outside")
    requested = {
        "absolute": str(outside),
        "parent": "../outside",
        "embedded_parent": "b/../../outside",
    }[shape]
    response = _client(service, packages_dir=root).post(
        "/v1/admin/tenants/provision",
        json={"package_path": requested},
    )
    assert response.status_code == 400
    assert service.packages == []
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("shape", ["absolute", "relative"])
def test_provision_rejects_a_symlink_that_escapes_the_root(
    tmp_path: Path, shape: str
) -> None:
    """A textual `..` check would accept this; the resolved path must not."""
    service = StubOnboardingService()
    root, name = _escaping_symlink(tmp_path)
    requested = str(root / name) if shape == "absolute" else name
    response = _client(service, packages_dir=root).post(
        "/v1/admin/tenants/provision",
        json={"package_path": requested},
    )
    assert response.status_code == 400
    assert service.packages == []
    assert str(tmp_path) not in response.text


def test_the_same_package_provisions_once_it_lives_inside_the_root(
    tmp_path: Path,
) -> None:
    """Control for the symlink case: the rejection is containment, not validity."""
    service = StubOnboardingService()
    root, requested = _escaping_symlink(tmp_path)
    write_package(root / requested.replace("linked", "copied"))
    response = _client(service, packages_dir=root).post(
        "/v1/admin/tenants/provision",
        json={"package_path": "copied"},
    )
    assert response.status_code == 200
    assert [item.tenant.slug for item in service.packages] == [SLUG]


@pytest.mark.parametrize("requested", ["a\x00b", "~/secrets", "/proc/self/environ"])
def test_provision_refuses_malformed_paths_without_failing(
    tmp_path: Path, requested: str
) -> None:
    """A rejected path never becomes a 500, and `~` is not expanded."""
    service = StubOnboardingService()
    response = _client(service, packages_dir=tmp_path).post(
        "/v1/admin/tenants/provision",
        json={"package_path": requested},
    )
    assert response.status_code == 400
    assert service.packages == []


def test_provision_rejects_a_root_that_is_not_a_directory(tmp_path: Path) -> None:
    service = StubOnboardingService()
    missing = tmp_path / "absent"
    write_package(tmp_path / "b")
    response = _client(service, packages_dir=missing).post(
        "/v1/admin/tenants/provision",
        json={"package_path": "b"},
    )
    assert response.status_code == 503
    assert service.packages == []
    assert str(tmp_path) not in response.text


def test_preflight_without_a_configured_root_is_refused(tmp_path: Path) -> None:
    service = StubOnboardingService()
    package = write_package(tmp_path / "b")
    response = _client(service).post(
        f"/v1/admin/tenants/{SLUG}/preflight",
        json={"package_path": str(package)},
    )
    assert response.status_code == 503
    assert service.content_hashes == []
    assert str(tmp_path) not in response.text


def test_preflight_rejects_a_symlink_that_escapes_the_root(tmp_path: Path) -> None:
    service = StubOnboardingService()
    root, name = _escaping_symlink(tmp_path)
    response = _client(service, packages_dir=root).post(
        f"/v1/admin/tenants/{SLUG}/preflight",
        json={"package_path": str(root / name)},
    )
    assert response.status_code == 400
    assert service.content_hashes == []
    assert str(tmp_path) not in response.text


def test_preflight_accepts_a_package_inside_the_root(tmp_path: Path) -> None:
    service = StubOnboardingService()
    write_package(tmp_path / "b")
    response = _client(service, packages_dir=tmp_path).post(
        f"/v1/admin/tenants/{SLUG}/preflight",
        json={"package_path": "b"},
    )
    assert response.status_code == 200
    assert response.json()["report_hash"] == ZERO_HASH
    assert len(service.content_hashes) == 1


def test_missing_identity_is_refused_before_the_wiring_is_reported(
    tmp_path: Path,
) -> None:
    """Mounting must not tell an anonymous caller how the process is wired."""
    del tmp_path
    response = _client(None, principal=None).post(
        "/v1/admin/tenants/provision",
        json={"package_path": "b"},
    )
    assert response.status_code == 401


def test_a_token_the_process_does_not_know_is_refused(tmp_path: Path) -> None:
    """The root is configured and the package is valid; only the token is not."""
    service = StubOnboardingService()
    write_package(tmp_path / "b")
    response = _client(service, packages_dir=tmp_path).post(
        "/v1/admin/tenants/provision",
        json={"package_path": "b"},
        headers=bearer("svctest-not-the-configured-one"),
    )
    assert response.status_code == 401
    assert service.packages == []


def test_non_platform_admin_is_refused_before_the_root_is_read(tmp_path: Path) -> None:
    service = StubOnboardingService()
    write_package(tmp_path / "b")
    response = _client(
        service,
        principal=Principal(principal_id=uuid4(), roles=frozenset({"operator"})),
    ).post(
        "/v1/admin/tenants/provision",
        json={"package_path": "b"},
    )
    assert response.status_code == 403
    assert service.packages == []
