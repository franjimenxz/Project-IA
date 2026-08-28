import os

from fastapi import FastAPI

_NON_PRODUCTION_ENVIRONMENTS = frozenset({"test", "development"})


def _resolve_environment(environment: str | None) -> str:
    if environment is not None:
        return environment.lower()
    return os.environ.get("IA_MCP_ENVIRONMENT", "development").lower()


def create_app(*, environment: str | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    if _resolve_environment(environment) in _NON_PRODUCTION_ENVIRONMENTS:
        from ia_mcp.api.routes.simulated import router as simulated_router

        app.include_router(simulated_router)

    return app
