# resource_hub/core/logging_client.py
"""
Unified SHIVA logging client for the Resource Hub.

- send_log(...) is synchronous (requests) for existing code that expects a blocking call.
- send_log_async(...) is async and discovery-aware for async endpoints.
- Both call Overseer /log/event with X-SHIVA-SECRET header.
"""

import os
import time
from typing import Dict, Any

# sync client
import requests

# async client
import httpx

API_KEY = os.getenv("SHARED_SECRET", os.getenv("SHIVA_SHARED_SECRET", "mysecretapikey"))
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005")
OVERSEER_FALLBACK = os.getenv("OVERSEER_URL", "http://localhost:8004")
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

def _build_payload(service: str, task_id: str | None, level: str, message: str, context: Dict[str, Any] | None = None):
    return {
        "service": service,
        "task_id": task_id,
        "level": (level or "INFO").upper(),
        "message": message,
        "context": context or {}
    }

def send_log(service: str, task_id: str | None, level: str, message: str, context: Dict[str, Any] | None = None):
    """
    Synchronous logging wrapper used by legacy hub code.
    Best-effort (errors are swallowed).
    """
    payload = _build_payload(service, task_id, level, message, context)
    # Try discovery via DIRECTORY, fallback to env var
    try:
        r = requests.get(f"{DIRECTORY_URL}/discover", params={"service_name": "overseer"}, headers=AUTH_HEADER, timeout=2)
        if r.status_code == 200:
            overseer = r.json().get("url", OVERSEER_FALLBACK)
        else:
            overseer = OVERSEER_FALLBACK
    except Exception:
        overseer = OVERSEER_FALLBACK

    try:
        # Overseer expects JSON and returns 200
        requests.post(f"{overseer}/log/event", json=payload, headers=AUTH_HEADER, timeout=3)
    except Exception:
        # best-effort; don't raise
        return

async def discover_overseer(client: httpx.AsyncClient) -> str:
    """Async discover helper; raises on failure."""
    r = await client.get(f"{DIRECTORY_URL}/discover", params={"service_name": "overseer"}, headers=AUTH_HEADER, timeout=4)
    r.raise_for_status()
    return r.json()["url"]

async def send_log_async(service: str, task_id: str | None, level: str, message: str, context: Dict[str, Any] | None = None):
    payload = _build_payload(service, task_id, level, message, context)
    async with httpx.AsyncClient(timeout=6.0) as client:
        try:
            overseer = await discover_overseer(client)
        except Exception:
            overseer = OVERSEER_FALLBACK
        try:
            await client.post(f"{overseer}/log/event", json=payload, headers=AUTH_HEADER, timeout=4)
        except Exception:
            return
