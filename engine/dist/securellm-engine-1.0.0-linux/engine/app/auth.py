"""API key authentication for workspace-scoped requests."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status

from app.config import settings
from app.storage import KVStore, get_store


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return f"slm_{secrets.token_urlsafe(32)}"


async def require_workspace(
    x_api_key: str = Header(..., alias="X-API-Key"),
    store: KVStore = Depends(get_store),
) -> str:
    """Validate the API key and return the workspace_id it belongs to."""
    ws_id = await store.get(f"apikey:{hash_key(x_api_key)}")
    if not ws_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return ws_id


async def require_admin(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> None:
    """Validate admin key for management endpoints."""
    if not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid admin key")
