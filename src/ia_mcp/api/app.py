from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    return app
