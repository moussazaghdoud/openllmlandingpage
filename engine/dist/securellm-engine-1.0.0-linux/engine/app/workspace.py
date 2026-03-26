"""Workspace (tenant) management — CRUD operations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.auth import generate_api_key, hash_key
from app.storage import KVStore


# ── Workspace CRUD ───────────────────────────────────────

async def create_workspace(
    store: KVStore, name: str, ppi_terms: list[str] | None = None, llm: dict | None = None
) -> dict:
    ws_id = uuid.uuid4().hex[:12]
    api_key = generate_api_key()

    ws_data = {"id": ws_id, "name": name}
    await store.set(f"ws:{ws_id}", json.dumps(ws_data))
    await store.set(f"apikey:{hash_key(api_key)}", ws_id)

    if ppi_terms:
        await store.set(f"ws:{ws_id}:ppi_terms", json.dumps(ppi_terms))

    if llm:
        await store.set(f"ws:{ws_id}:llm", json.dumps(llm))

    # Init stats
    await store.set(f"ws:{ws_id}:stats", json.dumps({"anon_count": 0, "last_used": None}))

    result = await get_workspace(store, ws_id)
    result["api_key"] = api_key
    return result


async def get_workspace(store: KVStore, ws_id: str) -> dict | None:
    raw = await store.get(f"ws:{ws_id}")
    if not raw:
        return None
    ws = json.loads(raw)

    raw_terms = await store.get(f"ws:{ws_id}:ppi_terms")
    ws["ppi_term_count"] = len(json.loads(raw_terms)) if raw_terms else 0

    raw_llm = await store.get(f"ws:{ws_id}:llm")
    if raw_llm:
        llm = json.loads(raw_llm)
        ws["llm"] = {
            "provider": llm["provider"],
            "upstream_url": llm["upstream_url"],
            "default_model": llm.get("default_model", ""),
            "configured": True,
        }
    else:
        ws["llm"] = None

    return ws


async def get_llm_config(store: KVStore, ws_id: str) -> dict | None:
    raw = await store.get(f"ws:{ws_id}:llm")
    if not raw:
        return None
    return json.loads(raw)


async def update_workspace(
    store: KVStore, ws_id: str, name: str | None = None,
    ppi_terms: list[str] | None = None, llm: dict | None = None
) -> dict | None:
    raw = await store.get(f"ws:{ws_id}")
    if not raw:
        return None

    ws = json.loads(raw)
    if name is not None:
        ws["name"] = name
        await store.set(f"ws:{ws_id}", json.dumps(ws))

    if ppi_terms is not None:
        await store.set(f"ws:{ws_id}:ppi_terms", json.dumps(ppi_terms))

    if llm is not None:
        await store.set(f"ws:{ws_id}:llm", json.dumps(llm))

    return await get_workspace(store, ws_id)


async def delete_workspace(store: KVStore, ws_id: str) -> bool:
    raw = await store.get(f"ws:{ws_id}")
    if not raw:
        return False

    await store.delete(
        f"ws:{ws_id}", f"ws:{ws_id}:ppi_terms", f"ws:{ws_id}:llm",
        f"ws:{ws_id}:stats", f"ws:{ws_id}:apikeys",
    )

    keys = await store.scan_iter("apikey:*")
    for key in keys:
        val = await store.get(key)
        if val == ws_id:
            await store.delete(key)

    return True


# ── PPI Terms ────────────────────────────────────────────

async def get_ppi_terms(store: KVStore, ws_id: str) -> list[str]:
    raw = await store.get(f"ws:{ws_id}:ppi_terms")
    return json.loads(raw) if raw else []


async def set_ppi_terms(store: KVStore, ws_id: str, terms: list[str]) -> list[str]:
    await store.set(f"ws:{ws_id}:ppi_terms", json.dumps(terms))
    return terms


# ── Usage Stats ──────────────────────────────────────────

async def get_stats(store: KVStore, ws_id: str) -> dict:
    raw = await store.get(f"ws:{ws_id}:stats")
    return json.loads(raw) if raw else {"anon_count": 0, "last_used": None}


async def increment_stats(store: KVStore, ws_id: str) -> None:
    stats = await get_stats(store, ws_id)
    stats["anon_count"] += 1
    stats["last_used"] = datetime.now(timezone.utc).isoformat()
    await store.set(f"ws:{ws_id}:stats", json.dumps(stats))


# ── Sub-API-Keys ─────────────────────────────────────────

async def list_api_keys(store: KVStore, ws_id: str) -> list[dict]:
    raw = await store.get(f"ws:{ws_id}:apikeys")
    return json.loads(raw) if raw else []


async def create_sub_api_key(store: KVStore, ws_id: str, label: str) -> dict:
    api_key = generate_api_key()
    key_hash = hash_key(api_key)
    prefix = api_key[:12] + "..."

    # Register in global lookup
    await store.set(f"apikey:{key_hash}", ws_id)

    # Add to workspace key list
    keys = await list_api_keys(store, ws_id)
    entry = {
        "hash": key_hash,
        "label": label,
        "prefix": prefix,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    keys.append(entry)
    await store.set(f"ws:{ws_id}:apikeys", json.dumps(keys))

    return {"label": label, "api_key": api_key, "created_at": entry["created_at"]}


async def revoke_api_key(store: KVStore, ws_id: str, prefix: str) -> bool:
    keys = await list_api_keys(store, ws_id)
    found = None
    for k in keys:
        if k["prefix"] == prefix:
            found = k
            break
    if not found:
        return False

    # Remove from global lookup
    await store.delete(f"apikey:{found['hash']}")

    # Remove from workspace list
    keys = [k for k in keys if k["prefix"] != prefix]
    await store.set(f"ws:{ws_id}:apikeys", json.dumps(keys))

    return True
