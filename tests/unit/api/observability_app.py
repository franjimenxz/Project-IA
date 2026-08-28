from fastapi import FastAPI

from ia_mcp.api.app import create_app
from ia_mcp.api.errors import register_error_handlers


def app_with_observability() -> FastAPI:
    app = create_app()
    register_error_handlers(app)
    return app
