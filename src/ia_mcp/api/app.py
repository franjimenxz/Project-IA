from fastapi import FastAPI

from ia_mcp.api.errors import register_error_handlers
from ia_mcp.observability.context import CorrelationMiddleware


def create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    register_error_handlers(app)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    return app
