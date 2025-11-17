# =============================================================
#  PARTNER SERVICE — CLEAN, CORRECT, SHIVA-COMPLIANT VERSION
# =============================================================

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import httpx
import requests
import threading
import time
import json
import os
from typing import List, Dict, Any
import uvicorn
from security import get_api_key
from gemini_client import get_model, generate_json

# -------------------------------------------------------------
#  GEMINI LLM SETUP (ReAct Worker Model)
# -------------------------------------------------------------
PARTNER_SYSTEM_PROMPT = """
You are Partner, a ReAct-style worker agent in the SHIVA system.

You must respond ONLY in JSON.

When prompt = "Reason":
{
  "thought": "<reasoning>",
  "action": "<tool-name or 'finish_goal'>",
  "action_input": {...}
}

When prompt = "Observe":
{
  "observation": "<short summary>"
}
"""
partner_model = get_model(system_instruction=PARTNER_SYSTEM_PROMPT)

# -------------------------------------------------------------
#  FastAPI Initialization
# -------------------------------------------------------------
app = FastAPI(
    title="Partner Service",
    description="ReAct Runtime Worker for SHIVA.",
    dependencies=[Depends(get_api_key)]
)

API_KEY = os.getenv("SHARED_SECRET", "mysecretapikey")
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005")

SERVICE_NAME = "partner"
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8002))

# -------------------------------------------------------------
#  DATA MODELS
# -------------------------------------------------------------
class ExecuteGoal(BaseModel):
    task_id: str
    current_step_goal: str
    approved_plan: dict
    context: dict = {}

# -------------------------------------------------------------
#  DISCOVERY + LOGGING
# -------------------------------------------------------------
async def discover(client: httpx.AsyncClient, service: str) -> str:
    """Find service URL via Directory."""
    r = await client.get(
        f"{DIRECTORY_URL}/discover",
        params={"service_name": service},
        headers=AUTH_HEADER
    )
    if r.status_code != 200:
        raise HTTPException(500, f"Failed to discover {service}: {r.text}")
    return r.json()["url"]

async def log_overseer(client, task_id, level, message, context=None):
    context = context or {}
    try:
        overseer = await discover(client, "overseer")
        await client.post(
            f"{overseer}/log/event",
            json={
                "service": SERVICE_NAME,
                "task_id": task_id,
                "level": level,
                "message": message,
                "context": context
            },
            headers=AUTH_HEADER
        )
    except Exception:
        # Do not block execution if Overseer is down
        pass

# -------------------------------------------------------------
#  RESOURCE HUB HELPERS
# -------------------------------------------------------------
async def get_tools(client, task_id) -> List[Dict[str, Any]]:
    hub = await discover(client, "resource_hub")
    r = await client.get(f"{hub}/tools/list", headers=AUTH_HEADER)
    if r.status_code != 200:
        await log_overseer(client, task_id, "ERROR", "Failed to fetch tools from Resource Hub")
        return []
    return r.json().get("tools", [])

async def execute_tool(client, task_id, action: str, params: dict):
    hub = await discover(client, "resource_hub")
    try:
        r = await client.post(
            f"{hub}/tools/execute",
            json={"tool_name": action, "parameters": params, "task_id": task_id},
            headers=AUTH_HEADER,
            timeout=60
        )
        # If resource hub returns non-json, this will raise — handle below
        return r.json()
    except Exception as e:
        return {"status": "deviation", "error": f"Tool failed: {str(e)}"}

# -------------------------------------------------------------
#  LLM Reasoning Helpers
# -------------------------------------------------------------
def llm_reason(goal, tools, history) -> dict:
    response = generate_json(
        partner_model,
        [
            "Prompt: Reason",
            f"Current Step Goal: {goal}",
            f"Available Tools: {json.dumps(tools)}",
            f"History: {json.dumps(history[-3:])}",
        ]
    )
    if not isinstance(response, dict) or "thought" not in response or "action" not in response:
        return {"thought": "LLM error", "action": "finish_goal", "action_input": {}}
    return response

def llm_observe(action_result) -> str:
    response = generate_json(
        partner_model,
        [
            "Prompt: Observe",
            f"Action Result: {json.dumps(action_result)}",
        ]
    )
    if not isinstance(response, dict):
        return "No observation available."
    return response.get("observation", "No observation available.")

# -------------------------------------------------------------
#  MAIN EXECUTION LOOP
# -------------------------------------------------------------
@app.post("/partner/execute_goal")
async def execute_goal(data: ExecuteGoal):
    task_id = data.task_id
    goal = data.current_step_goal
    history = []
    MAX_LOOPS = 6

    async with httpx.AsyncClient(timeout=200) as client:
        await log_overseer(client, task_id, "INFO", f"Executing goal: {goal}")

        # Get tools
        tools = await get_tools(client, task_id)
        if not tools:
            return {"task_id": task_id, "status": "FAILED", "reason": "No tools available"}

        # ReAct Loop
        for loop in range(MAX_LOOPS):

            # 1. Reasoning
            agent_step = llm_reason(goal, tools, history)
            thought = agent_step.get("thought", "No thought")
            action = agent_step.get("action", "finish_goal")
            params = agent_step.get("action_input", {})

            await log_overseer(client, task_id, "INFO", f"[Loop {loop+1}] Thought: {thought}", agent_step)

            # FINISH GOAL
            if action == "finish_goal":
                observation = "Goal completed successfully."
                history.append({"thought": thought, "action": "finish_goal", "observation": observation})
                await log_overseer(client, task_id, "INFO", "Goal completed.")
                return {"task_id": task_id, "status": "STEP_COMPLETED", "output": {"observation": observation}}

            # 2. Guardian validation
            guardian = await discover(client, "guardian")
            try:
                g_resp = await client.post(
                    f"{guardian}/guardian/validate_action",
                    json={
                        "task_id": task_id,
                        "proposed_action": action,
                        "action_input": params,
                        "context": data.context
                    },
                    headers=AUTH_HEADER,
                    timeout=10
                )
            except Exception as e:
                await log_overseer(client, task_id, "ERROR", f"Guardian contact failed: {e}")
                return {"task_id": task_id, "status": "FAILED", "reason": "Guardian unreachable"}

            # Handle guardian responses robustly
            try:
                g_json = g_resp.json()
            except Exception:
                await log_overseer(client, task_id, "ERROR", "Invalid response from Guardian")
                return {"task_id": task_id, "status": "FAILED", "reason": "Invalid response from Guardian"}

            if g_resp.status_code == 403 or g_json.get("decision") == "Deny":
                await log_overseer(client, task_id, "WARN", "Guardian denied action", g_json)
                return {
                    "task_id": task_id,
                    "status": "ACTION_REJECTED",
                    "reason": g_json.get("reason", "Guardian denied action"),
                    "details": g_json
                }

            if g_json.get("decision") == "Ambiguous":
                await log_overseer(client, task_id, "INFO", "Guardian requested human approval", g_json)
                return {
                    "task_id": task_id,
                    "status": "WAITING_APPROVAL",
                    "reason": "Guardian requires human review",
                    "details": g_json
                }

            await log_overseer(client, task_id, "INFO", "Guardian allowed action", g_json)

            # 3. Execute Tool
            tool_result = await execute_tool(client, task_id, action, params)

            # Deviation check
            if str(tool_result.get("status", "")).lower() == "deviation":
                observation = llm_observe(tool_result)
                history.append({
                    "thought": thought,
                    "action": action,
                    "observation": observation
                })
                await log_overseer(client, task_id, "WARN", "Tool deviation detected", tool_result)
                return {
                    "task_id": task_id,
                    "status": "DEVIATION_DETECTED",
                    "reason": "Tool deviation",
                    "details": tool_result
                }

            # 4. Observation
            observation = llm_observe(tool_result)
            history.append({
                "thought": thought,
                "action": action,
                "observation": observation
            })

            # log success and continue to next loop
            await log_overseer(client, task_id, "INFO", "Action executed successfully", {"tool_result": tool_result, "observation": observation})

        # If we exit loop without finishing
        await log_overseer(client, task_id, "ERROR", "Max loops exceeded without completion")
        return {"task_id": task_id, "status": "FAILED", "reason": "Max loops exceeded"}

# -------------------------------------------------------------
#  HEALTH + REGISTRATION
# -------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

def register_self():
    while True:
        try:
            r = requests.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": f"http://localhost:{SERVICE_PORT}",
                    "ttl_seconds": 60
                },
                headers=AUTH_HEADER,
                timeout=5
            )
            if r.status_code == 200:
                print("[Partner] Registered with Directory.")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
        except Exception:
            pass
        print("[Partner] Directory unavailable. Retrying...")
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            requests.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": f"http://localhost:{SERVICE_PORT}",
                    "ttl_seconds": 60
                },
                headers=AUTH_HEADER,
                timeout=5
            )
        except Exception:
            # If heartbeat fails, attempt to re-register
            register_self()
            return

@app.on_event("startup")
def on_start():
    threading.Thread(target=register_self, daemon=True).start()

# -------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
