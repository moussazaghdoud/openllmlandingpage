"""Async background job system for long-running tasks.

Large document translations run in the background so the API
responds immediately with a job_id. Clients poll for status.

For production: replace with Celery/Redis Queue/BullMQ.
For now: asyncio tasks with status tracking in the KV store.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import datetime, timezone

from app.storage import KVStore

logger = logging.getLogger("securellm.jobs")

JOB_TTL = 86400  # 24 hours


async def create_job(store: KVStore, workspace_id: str, job_type: str, params: dict) -> str:
    """Create a background job and return its ID."""
    import uuid
    job_id = f"job:{workspace_id}:{uuid.uuid4().hex[:10]}"
    job_data = {
        "id": job_id,
        "workspace_id": workspace_id,
        "type": job_type,
        "status": "pending",
        "params": params,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
        "progress": 0,
    }
    await store.set(job_id, json.dumps(job_data), ex=JOB_TTL)
    return job_id


async def update_job(store: KVStore, job_id: str, **updates) -> None:
    """Update job status/progress/result."""
    raw = await store.get(job_id)
    if not raw:
        return
    job = json.loads(raw)
    job.update(updates)
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    await store.set(job_id, json.dumps(job), ex=JOB_TTL)


async def get_job(store: KVStore, job_id: str) -> dict | None:
    """Get job status."""
    raw = await store.get(job_id)
    if not raw:
        return None
    return json.loads(raw)


def run_in_background(store: KVStore, job_id: str, coro):
    """Schedule a coroutine as a background task with error handling."""
    async def wrapper():
        try:
            await update_job(store, job_id, status="running")
            result = await coro
            await update_job(store, job_id, status="completed", result=result, progress=100)
        except Exception as e:
            logger.error("Job %s failed: %s", job_id, e)
            await update_job(store, job_id, status="failed", error=str(e))

    asyncio.create_task(wrapper())
