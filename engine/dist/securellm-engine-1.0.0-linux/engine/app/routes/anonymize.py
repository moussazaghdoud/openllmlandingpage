"""Privacy Gateway endpoints — anonymize / deanonymize / LLM proxy."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_workspace
from app.engine.pipeline import PrivacyPipeline
from app.models import (
    AnonymizeRequest,
    AnonymizeResponse,
    DeanonymizeRequest,
    DeanonymizeResponse,
    LLMProxyRequest,
    LLMProxyResponse,
)
from app.storage import KVStore, get_store
from app import workspace as ws_ops

logger = logging.getLogger("securellm.routes.anonymize")

router = APIRouter(prefix="/v1", tags=["privacy-gateway"])


@router.post("/anonymize", response_model=AnonymizeResponse)
async def anonymize(
    req: AnonymizeRequest,
    workspace_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    if req.workspace_id != workspace_id:
        raise HTTPException(403, "Workspace ID mismatch")

    pipeline = await PrivacyPipeline.for_workspace(store, workspace_id)
    anonymized_text, mapping_id = await pipeline.anonymize(req.text)

    await ws_ops.increment_stats(store, workspace_id)

    return AnonymizeResponse(anonymized_text=anonymized_text, mapping_id=mapping_id)


@router.post("/deanonymize", response_model=DeanonymizeResponse)
async def deanonymize(
    req: DeanonymizeRequest,
    workspace_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    if not req.mapping_id.startswith(f"map:{workspace_id}:"):
        raise HTTPException(403, "Mapping does not belong to this workspace")

    pipeline = await PrivacyPipeline.for_workspace(store, workspace_id)
    text = await pipeline.deanonymize(req.text, req.mapping_id)

    return DeanonymizeResponse(text=text)


@router.post("/chat/completions", response_model=LLMProxyResponse)
async def llm_proxy(
    req: LLMProxyRequest,
    workspace_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    """Privacy-first LLM proxy — anonymize -> LLM -> deanonymize.

    LLM upstream is configured per-workspace via /admin/workspaces/{id}/llm.
    NO raw data ever reaches the LLM.
    """
    if req.workspace_id != workspace_id:
        raise HTTPException(403, "Workspace ID mismatch")

    # Load per-workspace LLM config
    llm_config = await ws_ops.get_llm_config(store, workspace_id)
    if not llm_config:
        raise HTTPException(503, "LLM not configured for this workspace. Use PUT /admin/workspaces/{id}/llm")

    upstream_url = llm_config["upstream_url"].rstrip("/")
    upstream_key = llm_config["api_key"]
    model = req.model if req.model != "default" else llm_config.get("default_model", "")
    if not model:
        raise HTTPException(400, "No model specified and no default_model configured")

    pipeline = await PrivacyPipeline.for_workspace(store, workspace_id)

    # Step 0: Load attached file contexts (already anonymized at upload time)
    file_context = ""
    file_mapping_ids: list[str] = []
    for fid in req.file_ids:
        if not fid.startswith(f"file:{workspace_id}:"):
            continue
        raw = await store.get(fid)
        if raw:
            import json as _json
            fdata = _json.loads(raw)
            file_context += f"\n\n--- Document: {fdata['filename']} ---\n{fdata['anonymized_text']}\n"
            file_mapping_ids.append(fdata["mapping_id"])

    # Step 1: Anonymize user/system messages
    anonymized_messages = []
    mapping_ids: list[str] = list(file_mapping_ids)

    # Inject file context as a system message if files are attached
    if file_context:
        anonymized_messages.append({
            "role": "system",
            "content": f"The user has attached the following documents. Use them to answer questions.\n{file_context}"
        })

    for msg in req.messages:
        content = msg.get("content", "")
        if not content or msg.get("role") == "assistant":
            anonymized_messages.append(msg)
            continue

        anon_text, mapping_id = await pipeline.anonymize(content)
        mapping_ids.append(mapping_id)
        anonymized_messages.append({**msg, "content": anon_text})

    # Step 2: Forward to upstream LLM
    provider = llm_config.get("provider", "custom")

    if provider == "anthropic":
        # Anthropic uses /v1/messages with a different format
        upstream_payload = {
            "model": model,
            "messages": anonymized_messages,
            "max_tokens": req.max_tokens,
        }
        headers = {
            "x-api-key": upstream_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        url = f"{upstream_url}/v1/messages"
    else:
        # OpenAI-compatible (openai, openclaw, custom)
        upstream_payload = {
            "model": model,
            "messages": anonymized_messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        headers = {
            "Authorization": f"Bearer {upstream_key}",
            "Content-Type": "application/json",
        }
        url = f"{upstream_url}/v1/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=upstream_payload)
            resp.raise_for_status()
            llm_data = resp.json()
    except httpx.HTTPError as e:
        logger.error("LLM upstream error: %s", e)
        raise HTTPException(502, f"LLM upstream error: {e}")

    # Step 3: Normalize response and deanonymize
    if provider == "anthropic":
        # Convert Anthropic response to OpenAI format
        content = ""
        for block in llm_data.get("content", []):
            if block.get("type") == "text":
                content += block["text"]
        choices = [{"message": {"role": "assistant", "content": content}}]
        usage = llm_data.get("usage")
    else:
        choices = llm_data.get("choices", [])
        usage = llm_data.get("usage")

    # Step 4: Deanonymize and sanitize output
    from app.engine.sanitizer import sanitize_response
    for choice in choices:
        content = choice.get("message", {}).get("content", "")
        if content:
            for mid in mapping_ids:
                content = await pipeline.deanonymize(content, mid)
            content, sanitize_warnings = sanitize_response(content)
            if sanitize_warnings:
                logger.warning("Sanitization warnings for ws=%s: %s", workspace_id, sanitize_warnings)
            choice["message"]["content"] = content

    return LLMProxyResponse(
        choices=choices,
        model=llm_data.get("model", model),
        usage=usage,
    )
