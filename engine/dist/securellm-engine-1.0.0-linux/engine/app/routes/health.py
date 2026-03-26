"""Health, metrics, and audit endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.config import settings
from app.middleware import metrics
from app.models import HealthResponse
from app.storage import KVStore, get_store

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health():
    redis_status = "disconnected"
    try:
        store = await get_store()
        if await store.ping():
            redis_status = "connected"
    except Exception:
        pass

    presidio_status = "built-in"
    if settings.presidio_external_url:
        presidio_status = f"external ({settings.presidio_external_url})"

    return HealthResponse(
        status="ok",
        version="0.1.0",
        presidio=presidio_status,
        redis=redis_status,
    )


@router.get("/admin/metrics", dependencies=[Depends(require_admin)])
async def get_metrics():
    """System-wide metrics for the SaaS admin."""
    return {
        "requests_total": metrics["requests_total"],
        "errors_total": metrics["errors_total"],
        "avg_response_ms": round(metrics["avg_response_ms"], 1),
        "top_endpoints": dict(sorted(
            metrics["requests_by_endpoint"].items(),
            key=lambda x: x[1], reverse=True
        )[:10]),
        "requests_by_workspace": metrics["requests_by_workspace"],
    }


@router.get("/admin/audit", dependencies=[Depends(require_admin)])
async def get_audit_log(
    store: KVStore = Depends(get_store),
):
    """Recent audit log entries."""
    raw = await store.get("audit:log")
    logs = json.loads(raw) if raw else []
    # Return newest first
    return logs[-50:][::-1]
