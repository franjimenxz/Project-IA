import os

from fastapi import FastAPI

from ia_mcp.api.routes.admin_runs import create_admin_runs_router
from ia_mcp.channels.outbox import ChannelOutbox
from ia_mcp.observability.context import CorrelationMiddleware

_NON_PRODUCTION_ENVIRONMENTS = frozenset({"test", "development"})


def _resolve_environment(environment: str | None) -> str:
    if environment is not None:
        return environment.lower()
    return os.environ.get("IA_MCP_ENVIRONMENT", "development").lower()


def create_app(*, environment: str | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    app.state.outbox = ChannelOutbox()

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    app.include_router(create_admin_runs_router())
    # P08-T03 may add create_onboarding_router() here; keep both include_router calls.

    if _resolve_environment(environment) in _NON_PRODUCTION_ENVIRONMENTS:
        from ia_mcp.api.routes.simulated import router as simulated_router

        app.include_router(simulated_router)

    return app
