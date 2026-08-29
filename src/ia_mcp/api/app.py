import os

from fastapi import FastAPI

from ia_mcp.api.composition import attach_runtime, build_runtime, runtime_lifespan
from ia_mcp.api.routes.admin_runs import create_admin_runs_router
from ia_mcp.channels.outbox import ChannelOutbox
from ia_mcp.observability.context import CorrelationMiddleware
from ia_mcp.onboarding.api import create_onboarding_router

_NON_PRODUCTION_ENVIRONMENTS = frozenset({"test", "development"})


def _resolve_environment(environment: str | None) -> str:
    if environment is not None:
        return environment.lower()
    return os.environ.get("IA_MCP_ENVIRONMENT", "development").lower()


def create_app(*, environment: str | None = None) -> FastAPI:
    resolved = _resolve_environment(environment)
    runtime = build_runtime(environment=resolved, environ=os.environ)
    app = FastAPI() if runtime is None else FastAPI(lifespan=runtime_lifespan(runtime))
    app.add_middleware(CorrelationMiddleware)
    app.state.outbox = ChannelOutbox()
    if runtime is not None:
        attach_runtime(app, runtime)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    app.include_router(create_admin_runs_router())
    app.include_router(create_onboarding_router())

    if resolved in _NON_PRODUCTION_ENVIRONMENTS:
        from ia_mcp.api.routes.simulated import router as simulated_router

        app.include_router(simulated_router)

    return app
