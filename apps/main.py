"""
FastAPI application entry point.

Startup:
- Configures logging
- Warms the ADK Runner singleton (so first request doesn't cold-start the agent)
- Registers the webhook router
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from apps.config import settings
from apps.webhook import router as webhook_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Configure logging, pre-warm the ADK Runner, then serve."""
    # Configure logging inside lifespan so it runs after uvicorn has set up
    # its own log handlers — basicConfig is a no-op if handlers already exist.
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        )
    else:
        root_logger.setLevel(logging.INFO)

    import apps.runner  # noqa: F401 — triggers Runner + session service init
    logger.info("ADK Runner initialised. KHIND sales agent ready.")
    yield
    logger.info("Shutting down KHIND sales agent.")


app = FastAPI(
    title="KHIND Sales Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check used by load balancers and Cloud Run health probes."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )
