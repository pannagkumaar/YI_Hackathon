# ============================================================
#  MANAGER SERVICE — FINAL SHIVA-COMPLIANT VERSION
# ============================================================

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import httpx
import uvicorn
import threading
import time
import uuid
import json
import os
import requests

# --- Authentication ---
from security import get_api_key

# --- Gemini Planner ---
from gemini_client import get_model, generate_json

MANAGER_SYSTEM_PROMPT = """
You are the Manager for the SHIVA multi-agent system.
Your job is to take a user goal and break it into a clear JSON plan.

Respond ONLY with:
{
  "plan_id": "<string>",
  "steps": [
    { "step_id": <int>, "goal": "<string>" }
  ]
}
"""
manager_model = get_model(system_instruction=MANAGER_SYSTEM_PROMPT)

# ============================================================
#  FastAPI Initialization
# ============================================================
app = FastAPI(
    title="Manager Service",
    description="Orchestrator for SHIVA Agents",
    dependencies=[Depends(get_api_key)]
)

API_KEY = os.getenv("SHARED_SECRET", "mysecretapikey")
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

# Fix: Safe fallback if env is empty string
raw_dir = os.getenv("DIRECTORY_URL")
DIRECTORY_URL = (raw_dir if raw_dir and raw_dir.strip() else "http://localhost:8005").rstrip("/")

SERVICE_NAME = "manager"
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8001))
SERVICE_URL = f"http://127.0.0.1:{SERVICE_PORT}"

# ============================================================
#  Task DB
# ============================================================
tasks_db = {}

class InvokeRequest(BaseModel):
    goal: str
    context: dict = {}

# ============================================================
#  Service Discovery (httpx async)
# ============================================================
async def discover(client: httpx.AsyncClient, name: str) -> str:
    """Discover a service via Directory."""
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": name},
            headers=AUTH_HEADER,
            timeout=5
        )
        r.raise_for_status()
        data = r.json()
        return data["url"]
    except Exception as e:
        raise HTTPException(500, f"[Manager] Could not discover {name}: {e}")

# ============================================================
#  Overseer Logging
# ============================================================
async def log_to_overseer(client, task_id, level, message, context=None):
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
                "context": context,
            }
        )
    except Exception:
        pass

# ============================================================
#  Registration (IDENTICAL TO GUARDIAN)
# ============================================================
def register_self():
    """Register Manager with Directory exactly like Guardian."""
    while True:
        try:
            payload = {
                "service_name": SERVICE_NAME,
                "service_url": SERVICE_URL,
                "ttl_seconds": 60
            }
            r = requests.post(
                f"{DIRECTORY_URL}/register",
                json=payload,
                headers=AUTH_HEADER,
                timeout=5
            )
            if r.status_code == 200:
                print(f"[Manager] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                return
            else:
                print(f"[Manager] Registration failed: {r.status_code} → {r.text}")
        except Exception as e:
            print(f"[Manager] Directory unavailable: {e}")

        print("[Manager] Retry in 5s...")
        time.sleep(5)

def heartbeat():
    """Heartbeat identical to Guardian."""
    while True:
        time.sleep(45)
        try:
            requests.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": SERVICE_URL,
                    "ttl_seconds": 60
                },
                headers=AUTH_HEADER,
                timeout=5
            )
        except Exception as e:
            print(f"[Manager] Heartbeat failed: {e}")
            register_self()
            return

@app.on_event("startup")
def startup_event():
    threading.Thread(target=register_self, daemon=True).start()

# ============================================================
#  PLAN GENERATION
# ============================================================
def generate_plan(goal: str, context: dict):
    parts = [
        f"User Goal: {goal}",
        f"Context: {json.dumps(context)}",
        "Generate the plan."
    ]
    plan = generate_json(manager_model, parts)

    if not isinstance(plan, dict) or "steps" not in plan:
        return {
            "plan_id": f"auto-{uuid.uuid4().hex[:5]}",
            "steps": [
                {"step_id": 1, "goal": f"Could not generate plan for '{goal}'"}
            ]
        }
    return plan

# ============================================================
#  EXECUTION LOOP
# ============================================================
async def execute_plan(task_id: str, step_index: int = 0):
    task = tasks_db[task_id]
    plan = task["plan"]

    async with httpx.AsyncClient(timeout=180) as client:
        guardian = await discover(client, "guardian")
        partner = await discover(client, "partner")

        steps = plan["steps"]

        for idx in range(step_index, len(steps)):
            step = steps[idx]
            step_id = step["step_id"]
            step_goal = step["goal"]

            task["current_step_index"] = idx
            task["status"] = f"EXECUTING_STEP_{step_id}"

            await log_to_overseer(client, task_id, "INFO", f"Executing step {step_id}: {step_goal}")

            # Guardian validation
            g = await client.post(
                f"{guardian}/guardian/validate_action",
                headers=AUTH_HEADER,
                json={
                    "task_id": task_id,
                    "proposed_action": step_goal,
                    "context": task.get("context", {})
                }
            )
            g_json = g.json()

            # Hard rejection
            if g.status_code == 403:
                task["status"] = "REJECTED"
                task["reason"] = g_json.get("reason", "Rejected by Guardian")
                return

            # Ambiguous → wait for approval
            if g_json.get("decision") == "Ambiguous":
                task["status"] = "WAITING_APPROVAL"
                task["pending_step"] = idx
                return

            # Partner execution
            p = await client.post(
                f"{partner}/partner/execute_goal",
                headers=AUTH_HEADER,
                json={
                    "task_id": task_id,
                    "current_step_goal": step_goal,
                    "approved_plan": plan,
                    "context": task.get("context", {})
                }
            )
            p_json = p.json()

            if p_json.get("status") == "DEVIATION_DETECTED":
                task["status"] = "PAUSED_DEVIATION"
                task["reason"] = p_json.get("reason")
                task["deviation_details"] = p_json.get("details")
                return

            if p_json.get("status") != "STEP_COMPLETED":
                task["status"] = "FAILED"
                task["reason"] = p_json.get("reason", "Partner failure")
                return

        # All steps done
        task["status"] = "COMPLETED"
        task["result"] = "All steps completed successfully."
        await log_to_overseer(client, task_id, "INFO", "Task completed")

# ============================================================
#  BACKGROUND TASK HANDLER
# ============================================================
async def run_task(task_id: str, request: InvokeRequest):
    task = tasks_db[task_id]

    async with httpx.AsyncClient(timeout=120) as client:
        await log_to_overseer(client, task_id, "INFO", "Task started")

        task["status"] = "PLANNING"
        plan = generate_plan(request.goal, request.context)
        task["plan"] = plan

        await log_to_overseer(client, task_id, "INFO", "Plan generated", plan)

        guardian = await discover(client, "guardian")
        g = await client.post(
            f"{guardian}/guardian/validate_plan",
            headers=AUTH_HEADER,
            json={"task_id": task_id, "plan": plan}
        )

        g_json = g.json()
        if g.status_code != 200 or g_json.get("decision") != "Allow":
            task["status"] = "REJECTED"
            task["reason"] = g_json.get("reason", "Plan rejected")
            return

        # Run full plan
        await execute_plan(task_id)

# ============================================================
#  PUBLIC ENDPOINTS
# ============================================================
@app.post("/invoke", status_code=202)
async def invoke(request: InvokeRequest, background: BackgroundTasks):
    task_id = f"task-{uuid.uuid4()}"
    tasks_db[task_id] = {
        "task_id": task_id,
        "goal": request.goal,
        "context": request.context,
        "status": "PENDING",
        "current_step_index": 0
    }

    background.add_task(run_task, task_id, request)

    return {
        "task_id": task_id,
        "status": "PENDING",
        "status_url": f"/task/{task_id}/status"
    }

@app.get("/task/{task_id}/status")
def get_status(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(404, "Task not found")
    return tasks_db[task_id]

@app.post("/task/{task_id}/approve")
async def approve(task_id: str, background: BackgroundTasks):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    if task["status"] != "WAITING_APPROVAL":
        raise HTTPException(400, f"Task is not waiting for approval (current: {task['status']})")

    step = task["pending_step"]
    task["status"] = "RESUMING"

    background.add_task(execute_plan, task_id, step)
    return {"task_id": task_id, "status": "RESUMING"}

@app.get("/tasks/list")
def list_tasks():
    return list(tasks_db.values())

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

# ============================================================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
