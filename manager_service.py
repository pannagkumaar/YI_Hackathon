# ============================================================
#  MANAGER SERVICE — SHIVA (Stable, Future-Proof)
# ============================================================

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import httpx
import uvicorn
import threading
import time
import uuid
import json
import os
import requests
from typing import Optional

# -------------------------
# CONFIG
# -------------------------
API_KEY = os.getenv("SHARED_SECRET", "mysecretapikey")
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

raw_dir = os.getenv("DIRECTORY_URL")
DIRECTORY_URL = (raw_dir if raw_dir and raw_dir.strip() else "http://localhost:8005").rstrip("/")

SERVICE_NAME = "manager"
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8001))
SERVICE_URL = f"http://127.0.0.1:{SERVICE_PORT}"

tasks_db = {}

# -------------------------
# SCHEMAS
# -------------------------
class InvokeRequest(BaseModel):
    goal: str
    context: dict = {}

class ReplanRequest(BaseModel):
    goal: str
    context: dict = {}

# -------------------------
# DISCOVERY
# -------------------------
async def discover(client: httpx.AsyncClient, name: str) -> Optional[str]:
    """
    Try discover; return None if not reachable.
    Raise HTTPException only for unexpected errors.
    """
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": name},
            headers=AUTH_HEADER,
            timeout=5
        )
        r.raise_for_status()
        return r.json().get("url", "").rstrip("/") or None
    except httpx.HTTPStatusError as e:
        raise HTTPException(500, f"[Manager] Could not discover {name}: {e}")
    except Exception:
        return None

# -------------------------
# OVERSEER LOGGING
# -------------------------
async def log_to_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context=None):
    context = context or {}
    try:
        overseer = await discover(client, "overseer")
        if not overseer:
            return
        await client.post(
            f"{overseer}/log/event",
            headers=AUTH_HEADER,
            json={
                "service": SERVICE_NAME,
                "task_id": task_id,
                "level": level,
                "message": message,
                "context": context,
            },
            timeout=5
        )
    except Exception:
        return

# -------------------------
# DIRECTORY REGISTRATION
# -------------------------
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
                print("[Manager] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                return
            else:
                print("[Manager] Registration failed:", r.status_code, r.text)
        except Exception as e:
            print("[Manager] Directory unavailable:", e)
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
            register_self()
            return

threading.Thread(target=register_self, daemon=True).start()

# -------------------------
# PLAN GENERATOR
# -------------------------
def generate_plan(goal: str, context: dict):
    return {
        "plan_id": f"plan-{uuid.uuid4().hex[:8]}",
        "steps": [
            {"step_id": 1, "goal": goal}
        ]
    }

async def fetch_expanded_plan(client, goal: str, context: dict):
    """Ask RAG/LLM for expanded multi-step plan"""
    rh = await discover(client, "resource_hub")

    try:
        r = await client.post(
            f"{rh}/rag/plan/expand",
            headers=AUTH_HEADER,
            json={"goal": goal, "context": context},
            timeout=12
        )
        r.raise_for_status()
        data = r.json()
        steps = data.get("steps", [])
        # Normalize step format
        fixed_steps = [{"step_id": i+1, "goal": s} for i, s in enumerate(steps)]
        return {"plan_id": f"plan-{uuid.uuid4().hex[:8]}", "steps": fixed_steps}
    except Exception as e:
        # fallback: original 1-step plan
        return {
            "plan_id": f"plan-{uuid.uuid4().hex[:8]}",
            "steps": [ {"step_id":1, "goal":goal} ]
        }


# -------------------------
# EXECUTE PLAN
# -------------------------
async def execute_plan(task_id: str, start_at: int = 0):
    task = tasks_db.get(task_id)
    if not task:
        return

    plan = task.get("plan", {})
    steps = plan.get("steps", [])

    async with httpx.AsyncClient(timeout=120) as client:

        guardian_url = await discover(client, "guardian")
        partner_url = await discover(client, "partner")

        if not partner_url:
            task["status"] = "FAILED"
            task["reason"] = "Partner service unavailable"
            await log_to_overseer(client, task_id, "ERROR", task["reason"])
            return

        for idx in range(start_at, len(steps)):
            step = steps[idx]
            step_id = step.get("step_id", idx + 1)
            step_goal = step.get("goal", "")

            task["status"] = f"EXECUTING_STEP_{step_id}"
            task["current_step_index"] = idx

            await log_to_overseer(client, task_id, "INFO", f"Executing step {step_id}: {step_goal}")

            # --- Resolve action ---
            if "8.8.8.8" in step_goal:
                action = "ping_host"
                action_input = {"host": "8.8.8.8"}
            elif "http" in step_goal.lower():
                action = "http_status_check"
                action_input = {"url": step_goal}
            else:
                action = "summarizer"
                action_input = {"text": step_goal[:800]}

            task["pending_action"] = {
                "action": action,
                "action_input": action_input,
                "step_goal": step_goal,
                "step_id": step_id
            }

            # --- Guardian check ---
            if not task.get("approved_once", False):
                if guardian_url:
                    try:
                        g = await client.post(
                            f"{guardian_url}/guardian/validate_action",
                            headers=AUTH_HEADER,
                            json={
                                "task_id": task_id,
                                "proposed_action": action,
                                "action_input": action_input,
                                "context": task.get("context", {})
                            },
                            timeout=8
                        )
                        g_json = g.json()
                    except Exception as e:
                        task["status"] = "WAITING_APPROVAL"
                        task["pending_step"] = idx
                        task["pending_action"]["guardian_details"] = {"error": str(e)}
                        task["reason"] = "Guardian unreachable"
                        await log_to_overseer(client, task_id, "WARN", "Guardian unreachable; waiting for human approval")
                        return

                    decision = g_json.get("decision", "")
                    if decision == "Ambiguous":
                        task["status"] = "WAITING_APPROVAL"
                        task["pending_step"] = idx
                        task["pending_action"]["guardian_details"] = g_json
                        await log_to_overseer(client, task_id, "WARN", "Guardian requires approval")
                        return
                    if decision == "Deny":
                        task["status"] = "REJECTED"
                        task["reason"] = g_json.get("reason", "Denied by Guardian")
                        await log_to_overseer(client, task_id, "WARN", "Guardian denied action")
                        return
                    await log_to_overseer(client, task_id, "INFO", "Guardian allowed action")
                else:
                    task["status"] = "WAITING_APPROVAL"
                    task["pending_step"] = idx
                    task["reason"] = "Guardian service not discovered"
                    await log_to_overseer(client, task_id, "WARN", "Guardian not found — waiting for approval")
                    return

            # --- Execute via Partner ---
            payload_context = {**task.get("context", {}), "approved_once": task.get("approved_once", False)}

            try:
                p = await client.post(
                    f"{partner_url}/partner/execute_goal",
                    headers=AUTH_HEADER,
                    json={
                        "task_id": task_id,
                        "current_step_goal": step_goal,
                        "approved_plan": plan,
                        "context": payload_context,
                        "pending_action": task.get("pending_action")
                    },
                    timeout=60
                )
                p_json = p.json()
            except Exception as e:
                task["status"] = "FAILED"
                task["reason"] = f"Partner execution failed: {e}"
                await log_to_overseer(client, task_id, "ERROR", task["reason"])
                return

            partner_status = p_json.get("status")

            if partner_status == "WAITING_APPROVAL":
                task["status"] = "WAITING_APPROVAL"
                task["pending_step"] = idx
                task["pending_action"] = p_json.get("pending_action")
                task["reason"] = p_json.get("reason")
                await log_to_overseer(client, task_id, "INFO", "Partner paused for approval")
                return

            if partner_status == "DEVIATION_DETECTED":
                task["status"] = "PAUSED_DEVIATION"
                task["reason"] = p_json.get("reason")
                task["deviation_details"] = p_json.get("details")
                await log_to_overseer(client, task_id, "WARN", "Deviation detected")
                return

            if partner_status != "STEP_COMPLETED":
                task["status"] = "FAILED"
                task["reason"] = p_json.get("reason", "Partner failure")
                await log_to_overseer(client, task_id, "ERROR", "Partner failed")
                return

            # success
            task.pop("pending_action", None)
            task["last_output"] = p_json.get("output", {})
            await log_to_overseer(client, task_id, "INFO", f"Step {step_id} completed")

        # all steps done
        task["status"] = "COMPLETED"
        task["result"] = "All steps completed successfully"
        await log_to_overseer(client, task_id, "INFO", "Task completed")

# -------------------------
# RUN TASK BACKGROUND WRAPPER
# -------------------------
async def run_task(task_id: str, request: InvokeRequest):
    async with httpx.AsyncClient(timeout=120) as client:

        await log_to_overseer(client, task_id, "INFO", "Task started")

        task = tasks_db.get(task_id)
        if not task:
            return

        task["status"] = "PLANNING"

        plan = await fetch_expanded_plan(client, request.goal, request.context)
        task["plan"] = plan

        guardian_url = await discover(client, "guardian")

        if guardian_url:
            try:
                g = await client.post(
                    f"{guardian_url}/guardian/validate_plan",
                    headers=AUTH_HEADER,
                    json={"task_id": task_id, "plan": plan},
                    timeout=8
                )
                g_json = g.json()
            except Exception as e:
                task["status"] = "REJECTED"
                task["reason"] = f"Guardian plan validation failed: {e}"
                await log_to_overseer(client, task_id, "ERROR", task["reason"])
                return

            if g_json.get("decision") != "Allow":
                task["status"] = "REJECTED"
                task["reason"] = g_json.get("reason", "Plan rejected")
                await log_to_overseer(client, task_id, "WARN", "Plan rejected")
                return

            await log_to_overseer(client, task_id, "INFO", "Plan allowed")
        else:
            # need human approval
            task["status"] = "WAITING_APPROVAL"
            task["pending_step"] = 0
            task["pending_action"] = {"action": "plan_needs_approval", "reason": "guardian_not_found"}
            task["reason"] = "Guardian not discovered"
            await log_to_overseer(client, task_id, "WARN", "Guardian missing — waiting for approval")
            return

        # run plan
        await execute_plan(task_id)

# -------------------------
# FASTAPI APP
# -------------------------
app = FastAPI(title="Manager Service")

# ---- INVOKE ----
@app.post("/invoke", status_code=202)
async def invoke(request: InvokeRequest, background: BackgroundTasks):
    task_id = f"task-{uuid.uuid4()}"
    tasks_db[task_id] = {
        "task_id": task_id,
        "goal": request.goal,
        "context": request.context,
        "status": "PENDING",
        "current_step_index": 0,
        "approved_once": False
    }
    background.add_task(run_task, task_id, request)
    return {"task_id": task_id, "status": "PENDING", "status_url": f"/task/{task_id}/status"}

# ---- STATUS ----
@app.get("/task/{task_id}/status")
def get_status(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(404, "Task not found")
    return tasks_db[task_id]

# ---- APPROVE ----
@app.post("/task/{task_id}/approve")
async def approve(task_id: str, background: BackgroundTasks):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.get("status") != "WAITING_APPROVAL":
        raise HTTPException(400, f"Not waiting for approval. Current status: {task.get('status')}")
    step = int(task.get("pending_step", 0))
    task["approved_once"] = True
    task["status"] = "RESUMING"
    background.add_task(execute_plan, task_id, step)
    return {"task_id": task_id, "status": "RESUMING"}

# ---- NEW: REPLAN ----
@app.post("/task/{task_id}/replan")
async def replan(task_id: str, req: ReplanRequest, background: BackgroundTasks):
    """Regenerate plan + restart execution."""
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # Reset core fields
    task["goal"] = req.goal
    task["context"] = req.context or {}
    task["approved_once"] = False
    task["current_step_index"] = 0
    task.pop("pending_action", None)
    task.pop("pending_step", None)
    task.pop("last_output", None)
    task.pop("deviation_details", None)
    task.pop("reason", None)

    task["status"] = "REPLANNING"

    # Generate fresh plan
    async with httpx.AsyncClient(timeout=12) as client:
        new_plan = await fetch_expanded_plan(client, req.goal, req.context)

    task["plan"] = new_plan
    # Start new execution
    background.add_task(run_task, task_id, InvokeRequest(goal=req.goal, context=req.context))
    return {"task_id": task_id, "status": "REPLANNING"}

# ---- LIST TASKS ----
@app.get("/tasks/list")
def list_tasks():
    return list(tasks_db.values())

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
