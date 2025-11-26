#!/usr/bin/env python3
# =============================================================
#  PARTNER SERVICE — SHIVA ReAct Worker (uses pending_action + approved_once)
#  - Patched: robust discovery retries, non-blocking sleep, clearer errors
# =============================================================

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import requests
import threading
import time
import json
import os
import uvicorn
from typing import Optional, Dict, Any
import asyncio

API_KEY = os.getenv("SHARED_SECRET", "mysecretapikey")
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005").rstrip("/")
SERVICE_NAME = "partner"
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8002))
SERVICE_URL = f"http://127.0.0.1:{SERVICE_PORT}"

app = FastAPI(title="Partner Service")

# -----------------------
# Helpers
# -----------------------
async def discover(client: httpx.AsyncClient, service: str, retries: int = 3, backoff: float = 0.6) -> str:
    """
    Discover a service URL from the directory with non-blocking retries.
    Returns the url (without trailing slash) or raises HTTPException if not found.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            r = await client.get(
                f"{DIRECTORY_URL}/discover",
                params={"service_name": service},
                headers=AUTH_HEADER,
                timeout=5.0
            )
            r.raise_for_status()
            url = r.json().get("url")
            if not url:
                raise HTTPException(500, f"[Partner] Directory returned no url for {service}")
            return str(url).rstrip("/")
        except httpx.HTTPStatusError as hse:
            last_exc = hse
            # don't retry on 4xx except maybe 404 -> break early
            if 400 <= hse.response.status_code < 500:
                break
        except Exception as e:
            last_exc = e

        # backoff before retry (non-blocking)
        await asyncio.sleep(backoff * (attempt + 1))

    # final attempt (one last try)
    try:
        r = await client.get(f"{DIRECTORY_URL}/discover", params={"service_name": service}, headers=AUTH_HEADER, timeout=5.0)
        r.raise_for_status()
        url = r.json().get("url")
        if not url:
            raise HTTPException(500, f"[Partner] Directory returned no url for {service}")
        return str(url).rstrip("/")
    except Exception as e:
        # convert to HTTPException so caller can decide
        raise HTTPException(503, f"[Partner] Could not discover {service}: {e}")

async def log_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context: Optional[dict] = None):
    """Best-effort log to overseer; do not fail main flow for logging errors."""
    context = context or {}
    try:
        overseer = await discover(client, "overseer")
        await client.post(
            f"{overseer}/log/event",
            headers=AUTH_HEADER,
            json={
                "service": SERVICE_NAME,
                "task_id": task_id,
                "level": level,
                "message": message,
                "context": context
            },
            timeout=4
        )
    except Exception:
        # swallow logging errors (best-effort)
        return

async def get_tools(client: httpx.AsyncClient, task_id: str):
    """
    Return list of tools. Raises HTTPException if resource_hub cannot be discovered.
    """
    hub = await discover(client, "resource_hub")
    r = await client.get(f"{hub}/tools/list", headers=AUTH_HEADER, timeout=6)
    r.raise_for_status()
    return r.json().get("tools", [])

async def execute_tool(client: httpx.AsyncClient, task_id: str, tool_name: str, params: Dict[str, Any]):
    """
    Call Resource Hub /tools/execute. Return Resource Hub JSON or structured deviation error dict.
    """
    hub = await discover(client, "resource_hub")
    try:
        r = await client.post(
            f"{hub}/tools/execute",
            headers=AUTH_HEADER,
            json={"tool_name": tool_name, "parameters": params or {}, "task_id": task_id},
            timeout=60
        )
        # accept 200 and parse JSON. If RH returns non-200, raise to be handled below
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as hse:
        # include response text so caller can surface it
        detail_text = None
        try:
            detail_text = hse.response.text
        except Exception:
            detail_text = str(hse)
        return {"status": "deviation", "error": f"HTTP error from Resource Hub: {hse.response.status_code}", "detail": detail_text}
    except Exception as e:
        return {"status": "deviation", "error": f"Connection error to Resource Hub: {e}"}

# -----------------------
# Small LLM placeholder functions (swap for real LLM)
# -----------------------
def llm_reason(goal: str, tools: list, history: list):
    return {"thought": "decide", "action": None, "action_input": {}}

def llm_observe(result):
    try:
        if isinstance(result, dict):
            # prefer 'output' nested fields if present
            return str(result.get("output", result))
        return str(result)
    except Exception:
        return "No observation"

# -----------------------
# Request schemas
# -----------------------
class ExecuteGoal(BaseModel):
    task_id: str
    current_step_goal: str
    approved_plan: dict
    context: dict = {}
    pending_action: Optional[dict] = None  # optional: manager may pass this

# -----------------------
# Endpoint: execute goal
# -----------------------
@app.post("/partner/execute_goal")
async def execute_goal(data: ExecuteGoal):
    task_id = data.task_id
    step_goal = data.current_step_goal
    context = data.context or {}
    pending_action = data.pending_action

    async with httpx.AsyncClient(timeout=120) as client:
        await log_overseer(client, task_id, "INFO", "Starting execution", {"step_goal": step_goal})

        # fetch tools capability (best-effort to validate availability)
        try:
            tools = await get_tools(client, task_id)
        except HTTPException as e:
            # discovery failure -> bubble up informative message
            await log_overseer(client, task_id, "ERROR", "Resource Hub unreachable", {"error": str(e)})
            return {"task_id": task_id, "status": "FAILED", "reason": f"Resource Hub unreachable: {e.detail if hasattr(e, 'detail') else str(e)}"}
        except Exception as e:
            await log_overseer(client, task_id, "ERROR", "Failed to get tools", {"error": str(e)})
            return {"task_id": task_id, "status": "FAILED", "reason": f"Resource Hub error: {e}"}

        # Prefer Manager's pending_action if provided
        action = None
        action_input = {}
        if pending_action and isinstance(pending_action, dict):
            action = pending_action.get("action")
            action_input = pending_action.get("action_input", {}) or {}
            await log_overseer(client, task_id, "DEBUG", "Using pending_action from Manager", pending_action)

        # Otherwise derive a simple action from text
        if not action:
            goal_text = (step_goal or "").lower()
            # crude detection for IPs, ping/http
            if "ping" in goal_text or "icmp" in goal_text or any(part.isdigit() for part in goal_text.split()):
                action = "ping_host"
                import re
                m = re.search(r"((?:\d{1,3}\.){3}\d{1,3})", step_goal)
                action_input = {"host": m.group(1)} if m else {}
            elif "http" in goal_text or "https" in goal_text:
                action = "http_status_check"
                import re
                m = re.search(r"https?://\S+", step_goal)
                action_input = {"url": m.group(0)} if m else {}
            else:
                action = "summarizer"
                action_input = {"text": step_goal[:400]}

        # Normalize context checks (be forgiving about types/keys)
        approved_once = False
        try:
            approved_once = bool(context.get("approved_once")) or str(context.get("approved_once", "")).lower() == "true"
        except Exception:
            approved_once = False

        if approved_once:
            await log_overseer(client, task_id, "INFO", "Manager pre-approved this task — skipping Guardian", {"approved_once": True})

        # If not pre-approved, consult Guardian
        if not approved_once:
            try:
                guardian = await discover(client, "guardian")
                g = await client.post(
                    f"{guardian}/guardian/validate_action",
                    headers=AUTH_HEADER,
                    json={
                        "task_id": task_id,
                        "proposed_action": action,
                        "action_input": action_input,
                        "context": context
                    },
                    timeout=8
                )
                g_json = g.json()
            except HTTPException as e:
                await log_overseer(client, task_id, "ERROR", f"Guardian discovery failed: {e}")
                return {"task_id": task_id, "status": "FAILED", "reason": f"Guardian discovery failed: {e.detail if hasattr(e, 'detail') else str(e)}"}
            except Exception as e:
                # If Guardian unreachable, ask for human approval (fail-safe)
                await log_overseer(client, task_id, "ERROR", f"Guardian unreachable: {e}")
                return {"task_id": task_id, "status": "FAILED", "reason": f"Guardian unreachable: {e}"}

            # Handle explicit Deny
            if g.status_code == 403 or g_json.get("decision") == "Deny":
                await log_overseer(client, task_id, "WARN", "Guardian denied action", g_json)
                return {
                    "task_id": task_id,
                    "status": "ACTION_REJECTED",
                    "reason": g_json.get("reason", "Denied by Guardian"),
                    "details": g_json
                }

            # Ambiguous → ask for human approval, pass back pending action so UI can display it
            if g_json.get("decision") == "Ambiguous":
                await log_overseer(client, task_id, "INFO", "Guardian requires human approval", g_json)
                return {
                    "task_id": task_id,
                    "status": "WAITING_APPROVAL",
                    "reason": "Guardian requires human review",
                    "details": g_json,
                    "pending_action": {"action": action, "action_input": action_input, "step_goal": step_goal}
                }

            # Allowed — proceed
            await log_overseer(client, task_id, "INFO", "Guardian allowed action", g_json)

        # Execute the resolved action using Resource Hub
        tool_result = await execute_tool(client, task_id, action, action_input)

        # If resource hub indicates deviation, bubble it up
        if str(tool_result.get("status", "")).lower() == "deviation" or tool_result.get("status") == "deviation":
            await log_overseer(client, task_id, "WARN", "Tool deviation detected", {"tool_result": tool_result})
            return {"task_id": task_id, "status": "DEVIATION_DETECTED", "reason": "Tool deviation", "details": tool_result}

        # Success path
        observation = llm_observe(tool_result)
        await log_overseer(client, task_id, "INFO", "Action executed successfully", {"tool_result": tool_result, "observation": observation})
        return {"task_id": task_id, "status": "STEP_COMPLETED", "output": {"tool_result": tool_result, "observation": observation}}

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

# -----------------------
# Directory registration (background)
# -----------------------
def register_self():
    while True:
        try:
            r = requests.post(
                f"{DIRECTORY_URL}/register",
                json={"service_name": SERVICE_NAME, "service_url": SERVICE_URL, "ttl_seconds": 60},
                headers=AUTH_HEADER,
                timeout=5
            )
            if r.status_code == 200:
                print("[Partner] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                return
        except Exception:
            # best effort, try again
            pass
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            requests.post(
                f"{DIRECTORY_URL}/register",
                json={"service_name": SERVICE_NAME, "service_url": SERVICE_URL, "ttl_seconds": 60},
                headers=AUTH_HEADER,
                timeout=5
            )
        except Exception:
            # re-register loop
            register_self()
            return

threading.Thread(target=register_self, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
