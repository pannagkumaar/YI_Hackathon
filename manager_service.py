# manager_service.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import httpx
import threading
import time
import uuid
from security import get_api_key

from gemini_client import get_model, generate_json, generate_json_safe
import json

MANAGER_SYSTEM_PROMPT = """
You are the "Manager," an AI team lead for the SHIVA agent system.
Your job is to take a high-level "goal" from a user and break it down into a 
clear, logical, step-by-step plan.

You must respond ONLY with a JSON object with keys:
1. "plan_id": A unique string
2. "steps": A list of objects, each with "step_id" (int) and "goal" (string)
"""
manager_model = get_model(system_instruction=MANAGER_SYSTEM_PROMPT)

app = FastAPI(
    title="Manager Service",
    description="Orchestrator for SHIVA.",
    dependencies=[Depends(get_api_key)]
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "manager-service"
SERVICE_PORT = 8001

tasks_db = {}

class InvokeRequest(BaseModel):
    goal: str
    context: dict = {}

# Agent planning helper
def use_agent(prompt: str, input_data: dict) -> dict:
    try:
        prompt_parts = [
            f"User Prompt: {prompt}\n",
            f"User Input: {json.dumps(input_data)}\n",
            "Return ONLY JSON: {\"plan_id\":\"...\",\"steps\":[{\"step_id\":1,\"goal\":\"...\"}]}"
        ]
        plan = generate_json(manager_model, prompt_parts, max_retries=1)
        if isinstance(plan, dict) and "steps" in plan and "plan_id" in plan:
            return plan
        # fallback safe
        plan2 = generate_json_safe(manager_model, prompt_parts, max_retries=1)
        if isinstance(plan2, dict) and "steps" in plan2 and "plan_id" in plan2:
            return plan2
        # safe fallback minimal plan
        return {
            "plan_id": f"plan-fallback-{uuid.uuid4().hex[:6]}",
            "steps": [{"step_id": 1, "goal": f"Error: AI failed to generate plan for {input_data.get('goal')}"}]
        }
    except Exception as e:
        print(f"[Manager] use_agent exception: {e}")
        return {
            "plan_id": f"plan-fallback-{uuid.uuid4().hex[:6]}",
            "steps": [{"step_id": 1, "goal": f"Error: AI failed to generate plan for {input_data.get('goal')}"}]
        }

async def discover(client: httpx.AsyncClient, service_name: str) -> str:
    try:
        r = await client.get(f"{DIRECTORY_URL}/discover", params={"service_name": service_name}, headers=AUTH_HEADER)
        r.raise_for_status()
        return r.json()["url"]
    except Exception as e:
        print(f"[Manager] discover failed for {service_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not discover {service_name}: {e}")

async def log_to_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context: dict = {}):
    try:
        overseer_url = await discover(client, "overseer-service")
        await client.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[Manager] Failed to log to Overseer: {e}")

# registration
def register_self():
    while True:
        try:
            r = httpx.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            if r.status_code == 200:
                print("[Manager] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print("[Manager] registration failed, retrying...")
        except Exception:
            print("[Manager] Could not connect to Directory, retrying...")
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            httpx.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
        except Exception:
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

# Execution logic
async def execute_plan_from_step(task_id: str, step_index: int):
    task = tasks_db.get(task_id)
    if not task:
        print(f"[Manager] Task {task_id} not found")
        return
    plan = task.get("plan", {})
    if not plan.get("steps"):
        print(f"[Manager] No steps for {task_id}")
        return

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            for i in range(step_index, len(plan["steps"])):
                task["current_step_index"] = i
                step = plan["steps"][i]
                task["status"] = f"EXECUTING_STEP_{i+1}: {step['goal']}"
                await log_to_overseer(client, task_id, "INFO", f"Executing step {i+1}: {step['goal']}")

                partner_url = await discover(client, "partner-service")
                p_resp = await client.post(f"{partner_url}/partner/execute_goal", json={
                    "task_id": task_id,
                    "current_step_goal": step["goal"],
                    "approved_plan": plan,
                    "context": task.get("context", {})
                }, headers=AUTH_HEADER, timeout=300.0)

                partner_result = p_resp.json()
                await log_to_overseer(client, task_id, "INFO", "Partner result", partner_result)

                partner_status = partner_result.get("status")

                if partner_status == "STEP_COMPLETED":
                    continue
                elif partner_status == "DEVIATION_DETECTED":
                    await log_to_overseer(client, task_id, "WARN", "Deviation detected. Pausing.", partner_result)
                    task["status"] = "PAUSED_DEVIATION"
                    task["reason"] = partner_result.get("reason")
                    task["deviation_details"] = partner_result.get("details", {"observation": "No details"})
                    return
                elif partner_status == "ACTION_REJECTED":
                    await log_to_overseer(client, task_id, "ERROR", "Action rejected by Guardian", partner_result)
                    task["status"] = "REJECTED"
                    task["reason"] = partner_result.get("reason")
                    task["deviation_details"] = {"observation": f"Guardian rejection: {task['reason']}"}
                    return
                else:
                    await log_to_overseer(client, task_id, "ERROR", "Partner failed", partner_result)
                    task["status"] = "FAILED"
                    task["reason"] = partner_result.get("reason", "Unknown")
                    task["deviation_details"] = {"observation": f"Partner failed: {task['reason']}"}
                    return

            await log_to_overseer(client, task_id, "INFO", "All steps completed")
            task["status"] = "COMPLETED"
            task["result"] = "All steps executed successfully."
        except Exception as e:
            print(f"[Manager] execute_plan error: {e}")
            try:
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {e}")
            except:
                pass
            task["status"] = "FAILED"
            task["reason"] = str(e)
            task["deviation_details"] = {"observation": f"Unhandled exception: {str(e)}"}

# Background runner
async def run_task_background(task_id: str, request: InvokeRequest):
    task = tasks_db[task_id]
    task["status"] = "STARTING"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await log_to_overseer(client, task_id, "INFO", f"Task started: {request.goal}")
            
            task["status"] = "CHECKING_HALT"
            overseer_url = await discover(client, "overseer-service")
            status_resp = await client.get(f"{overseer_url}/control/status", headers=AUTH_HEADER)
            
            if status_resp.json().get("status") == "HALT":
                await log_to_overseer(client, task_id, "ERROR", "Task rejected: System is in HALT state.")
                task["status"] = "REJECTED"
                task["reason"] = "System is in HALT state"
                task["deviation_details"] = {"observation": "Task rejected: System is in HALT state"}
                return

            task["status"] = "PLANNING"
            await log_to_overseer(client, task_id, "INFO", "Generating execution plan...")
            plan_input = {"change_id": task_id, "goal": request.goal, "context": request.context}
            plan = use_agent("Create high-level plan for user goal", plan_input)
            task["plan"] = plan
            task["current_step_index"] = 0
            await log_to_overseer(client, task_id, "INFO", f"Plan generated with {len(plan.get('steps', []))} steps.", plan)
            
            task["status"] = "VALIDATING_PLAN"
            await log_to_overseer(client, task_id, "INFO", "Validating plan with Guardian...")
            guardian_url = await discover(client, "guardian-service")

            # --- NEW: tolerant handling of Guardian plan validation responses ---
            try:
                g_resp = await client.post(
                    f"{guardian_url}/guardian/validate_plan",
                    json={"task_id": task_id, "plan": plan},
                    headers=AUTH_HEADER,
                    timeout=20.0
                )
            except Exception as e:
                # Network/connection error to Guardian -> fail-conservative to PAUSED_REVIEW
                await log_to_overseer(client, task_id, "ERROR", f"Failed to call Guardian for plan validation: {e}")
                task["status"] = "PAUSED_REVIEW"
                task["reason"] = "Guardian unreachable; requires human review"
                task["deviation_details"] = {"observation": str(e)}
                return

            # Try to parse JSON body safely, fall back to text for diagnostics
            decision_payload = None
            body_text = ""
            try:
                # httpx Response.json() can raise; handle carefully
                decision_payload = g_resp.json()
            except Exception:
                try:
                    raw = await g_resp.aread()
                    body_text = raw.decode(errors="ignore")
                except Exception:
                    body_text = "<unreadable response body>"
                await log_to_overseer(client, task_id, "WARN", "Guardian returned non-JSON response for plan validation", {"status_code": g_resp.status_code, "body_preview": body_text[:500]})

            # If HTTP 5xx from Guardian => treat as PAUSED_REVIEW (human triage)
            if 500 <= g_resp.status_code < 600:
                task["status"] = "PAUSED_REVIEW"
                task["reason"] = "Guardian service error (5xx); requires human review"
                task["deviation_details"] = {"observation": body_text or "Guardian 5xx response"}
                await log_to_overseer(client, task_id, "ERROR", "Guardian service error (5xx) during plan validation", {"status_code": g_resp.status_code})
                return

            # If we couldn't parse JSON, fail to PAUSED_REVIEW to be safe
            if not isinstance(decision_payload, dict):
                task["status"] = "PAUSED_REVIEW"
                task["reason"] = "Invalid response from Guardian; requires human review"
                task["deviation_details"] = {"observation": (body_text or str(decision_payload))}
                await log_to_overseer(client, task_id, "WARN", "Invalid/empty JSON from Guardian; paused for human review", {"status_code": g_resp.status_code, "body_preview": (body_text or "")[:500]})
                return

            # Now inspect the decision field
            decision = decision_payload.get("decision")
            reason = decision_payload.get("reason", "")
            # Normalize decision names (be permissive)
            if isinstance(decision, str):
                decision_norm = decision.strip().capitalize()
            else:
                decision_norm = None

            # Missing or unknown decision -> PAUSED_REVIEW
            if decision_norm not in ("Allow", "Deny", "Ambiguous"):
                task["status"] = "PAUSED_REVIEW"
                task["reason"] = "Guardian returned unknown decision; requires human review"
                task["deviation_details"] = {"observation": f"Invalid decision: {decision}", "raw": decision_payload}
                await log_to_overseer(client, task_id, "WARN", "Guardian returned unknown decision value", {"decision": decision, "payload": decision_payload})
                return

            # Map decisions to manager states
            if decision_norm == "Allow":
                # Proceed normally
                await log_to_overseer(client, task_id, "INFO", "Plan validation PASSED by Guardian.", {"reason": reason})
            elif decision_norm == "Ambiguous":
                # Pause for explicit human review
                task["status"] = "PAUSED_REVIEW"
                task["reason"] = f"Plan requires human review: {reason}"
                task["deviation_details"] = {"observation": task["reason"], "guardian_payload": decision_payload}
                await log_to_overseer(client, task_id, "WARN", f"Plan requires human review per Guardian: {reason}", decision_payload)
                return
            else:  # "Deny"
                task["status"] = "REJECTED"
                task["reason"] = f"Plan validation failed: {reason}"
                task["deviation_details"] = {"observation": task["reason"], "guardian_payload": decision_payload}
                await log_to_overseer(client, task_id, "ERROR", f"Plan validation DENIED by Guardian: {reason}", decision_payload)
                return
            # --- END tolerant guardian handling ---

            if not plan.get("steps"):
                await log_to_overseer(client, task_id, "WARN", "Plan has no steps. Task considered complete.")
                task["status"] = "COMPLETED"
                task["result"] = "No steps to execute."
                return
                
            await execute_plan_from_step(task_id, 0)

        except Exception as e:
            print(f"[Manager] Unhandled exception in background task {task_id}: {e}")
            try:
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {str(e)}")
            except: pass
            task["status"] = "FAILED"
            task["reason"] = str(e)
            task["deviation_details"] = {"observation": f"Unhandled exception: {str(e)}"}

# Public endpoints
@app.post("/invoke", status_code=202)
async def invoke(request: InvokeRequest, background_tasks: BackgroundTasks):
    task_id = f"task-{uuid.uuid4()}"
    print(f"[Manager] New task {task_id} goal={request.goal}")
    tasks_db[task_id] = {
        "status": "PENDING",
        "goal": request.goal,
        "context": request.context,
        "current_step_index": 0,
        "task_id": task_id
    }
    background_tasks.add_task(run_task_background, task_id, request)
    return {"task_id": task_id, "status": "PENDING", "status_url": f"/task/{task_id}/status"}

@app.get("/task/{task_id}/status", status_code=200)
def get_task_status(task_id: str):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.post("/task/{task_id}/approve", status_code=202)
async def approve_task(task_id: str, background_tasks: BackgroundTasks):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in ["PAUSED_DEVIATION", "ACTION_REJECTED", "REJECTED", "FAILED", "PAUSED_REVIEW"]:
        raise HTTPException(status_code=400, detail=f"Task not pausable/resumable. status={task['status']}")
    step_to_resume = task.get("current_step_index", 0)
    task["status"] = "RESUMING"
    task["reason"] = "Resumed by user"
    background_tasks.add_task(execute_plan_from_step, task_id, step_to_resume)
    return {"task_id": task_id, "status": "RESUMING", "details": f"Resuming from step {step_to_resume+1}"}

@app.post("/task/{task_id}/replan", status_code=202)
async def replan_task(task_id: str, request: InvokeRequest, background_tasks: BackgroundTasks):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task["status"] = "REPLANNING"
    task["goal"] = request.goal
    task["context"] = request.context
    task["plan"] = {}
    task["current_step_index"] = 0
    task["reason"] = "Replanning triggered"
    background_tasks.add_task(run_task_background, task_id, request)
    return {"task_id": task_id, "status": "REPLANNING", "details": "Replanning initiated"}

@app.get("/tasks/list", status_code=200)
def get_all_tasks():
    return list(tasks_db.values())

if __name__ == "__main__":
    print(f"Starting Manager Service on port {SERVICE_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
