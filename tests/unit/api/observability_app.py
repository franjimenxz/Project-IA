from fastapi import FastAPI

from ia_mcp.api.app import create_app
from ia_mcp.api.errors import register_error_handlers
from ia_mcp.observability.context import CorrelationMiddleware


def app_with_observability() -> FastAPI:
    app = create_app()
    app.add_middleware(CorrelationMiddleware)
    register_error_handlers(app)
    return app
