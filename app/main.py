"""App factory. Serve with:

    granian --interface asgi --factory app.main:create_app
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from .api.routes import router
from .config import get_config
from .pipeline import build_pipelines
from .pipeline.steps.matching import validate_questions
from .services import Services

logging.basicConfig(level=logging.INFO)


def create_app(config: dict[str, Any] | None = None,
               services: Services | None = None) -> FastAPI:
    cfg = config or get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Fail fast on a bad config before serving anything.
        for section in ("matching", "alignment"):
            validate_questions(cfg[section]["questions"], cfg[section]["rank_by"], section)
        # Built inside the lifespan so each Granian worker gets its own HTTP client.
        svc = services or Services.from_config(cfg)
        app.state.services = svc
        app.state.pipelines = build_pipelines(cfg)  # validates step names at startup
        app.state.api_keys = {k.strip() for k in str(cfg["server"].get("api_keys") or "").split(",")
                              if k.strip()}
        yield
        await svc.aclose()

    app = FastAPI(title="literenare", version="0.1.0", lifespan=lifespan,
                  description="JeV-based grant matching and application alignment for it42.")
    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
