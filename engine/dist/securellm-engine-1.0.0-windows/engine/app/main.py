"""SecureLLM — Multi-tenant Privacy Gateway Service.

ALL data MUST pass through this service before reaching any LLM.
This is the single enforcement point — no bypass is allowed.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.middleware import ObservabilityMiddleware
from app.storage import close_store
from app.routes import anonymize, chat, dashboard, files, health, portal, translate, workspaces

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)

app = FastAPI(
    title="SecureLLM",
    description="Multi-tenant Privacy Gateway — anonymize all data before it reaches any LLM",
    version="0.1.0",
)

# Observability: request tracing, metrics, audit logging
app.add_middleware(ObservabilityMiddleware)

app.include_router(dashboard.router)
app.include_router(health.router)
app.include_router(anonymize.router)
app.include_router(workspaces.router)
app.include_router(portal.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(translate.router)


@app.on_event("shutdown")
async def shutdown():
    await close_store()
