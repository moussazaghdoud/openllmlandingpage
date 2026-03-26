"""Workspace management endpoints (admin-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_admin
from app.models import (
    LLMConfig, LLMConfigResponse,
    WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate,
)
from app.storage import KVStore, get_store
from app import workspace as ws_ops

router = APIRouter(prefix="/admin/workspaces", tags=["admin"])


@router.get("", response_model=list[WorkspaceResponse], dependencies=[Depends(require_admin)])
async def list_workspaces(
    store: KVStore = Depends(get_store),
):
    """List all workspaces."""
    keys = await store.scan_iter("ws:*")
    # Filter to workspace root keys only (exclude :ppi_terms, :llm)
    ws_keys = [k for k in keys if k.count(":") == 1]
    results = []
    for key in ws_keys:
        ws_id = key.split(":")[1]
        ws = await ws_ops.get_workspace(store, ws_id)
        if ws:
            results.append(WorkspaceResponse(**ws))
    return results


@router.post("", response_model=WorkspaceResponse, dependencies=[Depends(require_admin)])
async def create_workspace(
    body: WorkspaceCreate,
    store: KVStore = Depends(get_store),
):
    llm_dict = body.llm.model_dump() if body.llm else None
    result = await ws_ops.create_workspace(store, body.name, body.ppi_terms, llm_dict)
    return WorkspaceResponse(**result)


@router.get("/{ws_id}", response_model=WorkspaceResponse, dependencies=[Depends(require_admin)])
async def get_workspace(
    ws_id: str,
    store: KVStore = Depends(get_store),
):
    ws = await ws_ops.get_workspace(store, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return WorkspaceResponse(**ws)


@router.patch("/{ws_id}", response_model=WorkspaceResponse, dependencies=[Depends(require_admin)])
async def update_workspace(
    ws_id: str,
    body: WorkspaceUpdate,
    store: KVStore = Depends(get_store),
):
    llm_dict = body.llm.model_dump() if body.llm else None
    ws = await ws_ops.update_workspace(store, ws_id, body.name, body.ppi_terms, llm_dict)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return WorkspaceResponse(**ws)


@router.delete("/{ws_id}", dependencies=[Depends(require_admin)])
async def delete_workspace(
    ws_id: str,
    store: KVStore = Depends(get_store),
):
    ok = await ws_ops.delete_workspace(store, ws_id)
    if not ok:
        raise HTTPException(404, "Workspace not found")
    return {"deleted": True}


# ── LLM Config (dedicated endpoint for clarity) ─────────

@router.put("/{ws_id}/llm", response_model=LLMConfigResponse, dependencies=[Depends(require_admin)])
async def set_llm_config(
    ws_id: str,
    body: LLMConfig,
    store: KVStore = Depends(get_store),
):
    """Set or update the LLM upstream configuration for a workspace."""
    ws = await ws_ops.get_workspace(store, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    await ws_ops.update_workspace(store, ws_id, llm=body.model_dump())
    return LLMConfigResponse(
        provider=body.provider,
        upstream_url=body.upstream_url,
        default_model=body.default_model,
        configured=True,
    )


@router.get("/{ws_id}/llm", response_model=LLMConfigResponse, dependencies=[Depends(require_admin)])
async def get_llm_config(
    ws_id: str,
    store: KVStore = Depends(get_store),
):
    """Get LLM config for a workspace (API key is never returned)."""
    ws = await ws_ops.get_workspace(store, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if not ws.get("llm"):
        raise HTTPException(404, "LLM not configured for this workspace")
    return LLMConfigResponse(**ws["llm"])


@router.delete("/{ws_id}/llm", dependencies=[Depends(require_admin)])
async def delete_llm_config(
    ws_id: str,
    store: KVStore = Depends(get_store),
):
    """Remove LLM config from a workspace."""
    ws = await ws_ops.get_workspace(store, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    await store.delete(f"ws:{ws_id}:llm")
    return {"deleted": True}
