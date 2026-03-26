"""Observability middleware — request tracing, metrics, audit logging."""

from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.storage import get_store

logger = logging.getLogger("securellm.audit")

# In-memory metrics (production: use Prometheus/StatsD)
metrics = {
    "requests_total": 0,
    "requests_by_endpoint": {},
    "requests_by_workspace": {},
    "errors_total": 0,
    "anonymizations_total": 0,
    "avg_response_ms": 0,
    "_response_times": [],
}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        start = time.time()

        # Add request ID to headers
        request.state.request_id = request_id

        response: Response = await call_next(request)

        duration_ms = (time.time() - start) * 1000
        path = request.url.path
        method = request.method
        status = response.status_code

        # Update metrics
        metrics["requests_total"] += 1
        endpoint_key = f"{method} {path.split('?')[0]}"
        metrics["requests_by_endpoint"][endpoint_key] = metrics["requests_by_endpoint"].get(endpoint_key, 0) + 1

        if status >= 400:
            metrics["errors_total"] += 1

        # Track response times (keep last 1000)
        metrics["_response_times"].append(duration_ms)
        if len(metrics["_response_times"]) > 1000:
            metrics["_response_times"] = metrics["_response_times"][-1000:]
        metrics["avg_response_ms"] = sum(metrics["_response_times"]) / len(metrics["_response_times"])

        # Track per-workspace usage
        ws_id = response.headers.get("X-Workspace-ID", "")
        if ws_id:
            metrics["requests_by_workspace"][ws_id] = metrics["requests_by_workspace"].get(ws_id, 0) + 1

        # Log request
        if not path.startswith("/health"):
            logger.info(
                "rid=%s method=%s path=%s status=%d duration=%.0fms",
                request_id, method, path, status, duration_ms,
            )

        # Add tracing headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.0f}ms"

        # Audit log for sensitive operations
        if path.startswith("/v1/") and method == "POST":
            await _audit_log(request_id, method, path, status, duration_ms, request)

        return response


async def _audit_log(request_id: str, method: str, path: str, status: int, duration_ms: float, request: Request):
    """Write audit entry for anonymization/LLM operations."""
    try:
        store = await get_store()
        entry = json.dumps({
            "rid": request_id,
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": round(duration_ms),
            "ts": time.time(),
            "ip": request.client.host if request.client else "unknown",
        })
        # Append to audit log (capped list)
        existing = await store.get("audit:log")
        logs = json.loads(existing) if existing else []
        logs.append(json.loads(entry))
        # Keep last 500 entries
        if len(logs) > 500:
            logs = logs[-500:]
        await store.set("audit:log", json.dumps(logs))
    except Exception:
        pass  # Don't let audit logging break requests
