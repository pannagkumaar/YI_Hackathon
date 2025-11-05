# 📄 manager_service.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import httpx  # Use httpx for async requests
import threading
import time
import uuid
from security import get_api_key

# --- Authentication & Service Constants ---
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
# --- End Authentication & Service Constants ---

# --- NEW: In-memory Task Database ---
# This will store the state of all tasks
tasks_db = {}
# ---

# --- Mock Agent Function (No change) ---
def use_agent(prompt: str, input_data: dict) -> dict:
    print(f"[Manager] AI Agent called with prompt: {prompt}")
    if "Create high-level plan" in prompt:
        return {
            "plan_id": f"plan-{uuid.uuid4().hex[:8]}",
            "steps": [
                {"step_id": 1, "goal": "Analyze user request for change_id: " + input_data.get("change_id")},
                {"step_id": 2, "goal": "Fetch relevant data from Resource Hub"},
                {"step_id": 3, "goal": "Generate deployment script"},
                {"step_id": 4, "goal": "Finalize and report completion"}
            ]
        }
    return {"output": "Mock AI response"}
# --- End Mock Agent Function ---

# --- Service Discovery & Logging (UPDATED to be async) ---
async def discover(client: httpx.AsyncClient, service_name: str) -> str:
    """Finds a service's URL from the Directory (async)."""
    print(f"[Manager] Discovering: {service_name}")
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        r.raise_for_status() # Raise exception for 4xx/5xx
        url = r.json()["url"]
        print(f"[Manager] Discovered {service_name} at {url}")
        return url
    except httpx.RequestError as e:
        print(f"[Manager] FAILED to connect to Directory at {DIRECTORY_URL}: {e}")
        raise HTTPException(500, detail=f"Could not connect to Directory Service: {e}")
    except httpx.HTTPStatusError as e:
        print(f"[Manager] FAILED to discover {service_name}. Directory response: {e.response.text}")
        raise HTTPException(500, detail=f"Could not discover {service_name}: {e.response.text}")


async def log_to_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service (async)."""
    try:
        overseer_url = await discover(client, "overseer-service")
        await client.post(f"{overseer_url}/log/event", json={
            "service": "manager-service",
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[Manager] FAILED to log to Overseer: {e}")
# --- End Service Discovery & Logging ---

# --- Service Registration (Still synchronous, runs in separate thread) ---
def register_self():
    while True:
        try:
            # Use synchronous requests for initial registration
            r = httpx.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            
            if r.status_code == 200:
                print(f"[Manager] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Manager] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except httpx.RequestError:
            print(f"[Manager] Could not connect to Directory. Retrying in 5s...")
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
            print("[Manager] Heartbeat sent to Directory.")
        except httpx.RequestError:
            print("[Manager] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---

class InvokeRequest(BaseModel):
    goal: str
    context: dict = {}

# --- NEW: Background Task Logic ---
async def run_task_background(task_id: str, request: InvokeRequest):
    """This is the main logic that runs in the background."""
    
    tasks_db[task_id]["status"] = "STARTING"
    
    # Use an async client for all operations in this task
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await log_to_overseer(client, task_id, "INFO", f"Task started: {request.goal}")
            
            # Check Overseer status first
            tasks_db[task_id]["status"] = "CHECKING_HALT"
            overseer_url = await discover(client, "overseer-service")
            status_resp = await client.get(f"{overseer_url}/control/status", headers=AUTH_HEADER)
            
            if status_resp.json().get("status") == "HALT":
                await log_to_overseer(client, task_id, "ERROR", "Task rejected: System is in HALT state.")
                tasks_db[task_id]["status"] = "REJECTED"
                tasks_db[task_id]["reason"] = "System is in HALT state"
                return

            # 1. Generate plan
            tasks_db[task_id]["status"] = "PLANNING"
            await log_to_overseer(client, task_id, "INFO", "Generating execution plan...")
            plan_input = {"change_id": task_id, "goal": request.goal, "context": request.context}
            plan = use_agent("Create high-level plan for user goal", plan_input)
            tasks_db[task_id]["plan"] = plan
            await log_to_overseer(client, task_id, "INFO", f"Plan generated with {len(plan.get('steps', []))} steps.", plan)
            
            # 2. Validate plan with Guardian
            tasks_db[task_id]["status"] = "VALIDATING_PLAN"
            await log_to_overseer(client, task_id, "INFO", "Validating plan with Guardian...")
            guardian_url = await discover(client, "guardian-service")
            g_resp = await client.post(f"{guardian_url}/guardian/validate_plan", json={
                "task_id": task_id, "plan": plan
            }, headers=AUTH_HEADER)
            
            if g_resp.status_code != 200 or g_resp.json()["decision"] != "Allow":
                reason = g_resp.json().get("reason", "Unknown reason")
                await log_to_overseer(client, task_id, "ERROR", f"Plan validation FAILED: {reason}", g_resp.json())
                tasks_db[task_id]["status"] = "REJECTED"
                tasks_db[task_id]["reason"] = f"Plan validation failed: {reason}"
                return
            
            await log_to_overseer(client, task_id, "INFO", "Plan validation PASSED.")
            
            # 3. Execute plan with Partner
            if not plan.get("steps"):
                await log_to_overseer(client, task_id, "WARN", "Plan has no steps. Task considered complete.")
                tasks_db[task_id]["status"] = "COMPLETED"
                tasks_db[task_id]["result"] = "No steps to execute."
                return
                
            first_step = plan["steps"][0]
            tasks_db[task_id]["status"] = f"EXECUTING_STEP_1: {first_step['goal']}"
            await log_to_overseer(client, task_id, "INFO", f"Executing first step: {first_step['goal']}")
            
            partner_url = await discover(client, "partner-service")
            p_resp = await client.post(f"{partner_url}/partner/execute_step", json={
                "task_id": task_id,
                "current_step_goal": first_step["goal"],
                "approved_plan": plan,
                "context": request.context
            }, headers=AUTH_HEADER)
            
            partner_result = p_resp.json()
            await log_to_overseer(client, task_id, "INFO", f"Partner execution result: {partner_result.get('status')}", partner_result)
            
            # 4. Handle result
            if partner_result.get("status") == "DEVIATION_DETECTED":
                await log_to_overseer(client, task_id, "WARN", "Deviation detected. Stopping task for manual review.")
                tasks_db[task_id]["status"] = "PAUSED_DEVIATION"
                tasks_db[task_id]["details"] = partner_result
            elif partner_result.get("status") == "ACTION_REJECTED":
                await log_to_overseer(client, task_id, "ERROR", "Task REJECTED: Guardian denied a critical step.")
                tasks_db[task_id]["status"] = "REJECTED"
                tasks_db[task_id]["details"] = partner_result
            else:
                await log_to_overseer(client, task_id, "INFO", "Task completed (mock: only first step).")
                tasks_db[task_id]["status"] = "COMPLETED"
                tasks_db[task_id]["result"] = partner_result

        except Exception as e:
            # Catch-all for any unhandled exception during the background task
            print(f"[Manager] Unhandled exception in background task {task_id}: {e}")
            try:
                # Try to log the failure
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {str(e)}")
            except:
                pass # Logging itself might fail
            tasks_db[task_id]["status"] = "FAILED"
            tasks_db[task_id]["reason"] = str(e)
# --- END: Background Task Logic ---


# UPDATED: /invoke is now async and returns 202
@app.post("/invoke", status_code=202)
async def invoke(request: InvokeRequest, background_tasks: BackgroundTasks):
    """Start a new high-level task in the background."""
    task_id = f"task-{uuid.uuid4()}"
    print(f"\n[Manager] === New Task Received ===\nTask ID: {task_id}\nGoal: {request.goal}\n")
    
    # Create initial task entry in DB
    tasks_db[task_id] = {"status": "PENDING", "goal": request.goal}
    
    # Add the long-running job to the background
    background_tasks.add_task(run_task_background, task_id, request)
    
    # Immediately return 202 Accepted
    return {
        "task_id": task_id, 
        "status": "PENDING", 
        "details": "Task accepted and is running in the background.",
        "status_url": f"/task/{task_id}/status"
    }

# NEW: Endpoint to check task status
@app.get("/task/{task_id}/status", status_code=200)
def get_task_status(task_id: str):
    """Check the status of a background task."""
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return task

# Stub endpoints (no change)
@app.post("/task/{task_id}/approve")
def approve_task(task_id: str):
    # This logic would need to be updated to interact with the tasks_db
    return {"task_id": task_id, "status": "Resuming (Not Implemented)"}

@app.post("/task/{task_id}/replan")
def replan_task(task_id: str):
    # This logic would need to be updated to trigger a new background task
    return {"task_id": task_id, "status": "Replanning (Not Implemented)"}


if __name__ == "__main__":
    print("Starting Manager Service on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)