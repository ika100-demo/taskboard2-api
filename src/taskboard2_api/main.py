"""FastAPI entry point for taskboard2-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import tasks_api
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .postgres_task_store import PostgresTaskStore
from .task_store import InMemoryTaskStore, TaskStoreUnavailable
from .tracing import configure_tracing, tracing_enabled

logger = structlog.get_logger(__name__)

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    """Build a new app; the task store is selected from DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "")
    store: Any
    if url:
        store = PostgresTaskStore(url)
        backend = "postgres"
    else:
        store = InMemoryTaskStore()
        backend = "memory"
    logger.info("task_store_selected", backend=backend)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(store, "close", None)
        if close is not None:
            close()

    app = FastAPI(title="taskboard2-api", version="0.1.0", lifespan=lifespan)
    app.add_middleware(MetricsMiddleware)
    app.state.task_store = store

    async def _unavailable(_request: Request, exc: Exception) -> JSONResponse:
        cause = exc.__cause__
        logger.warning(
            "task_store_unavailable",
            error=type(cause).__name__ if cause is not None else None,
        )
        return JSONResponse(status_code=503, content={"detail": "Task store unavailable"})

    app.add_exception_handler(TaskStoreUnavailable, _unavailable)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        """Readiness probe — returns 200 when the service is ready to accept traffic."""
        return HealthResponse(status="ready")

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard2-api"}

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(tasks_api.router)
    return app


app = create_app()
