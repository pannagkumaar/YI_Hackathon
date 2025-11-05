# 📄 manager_service.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import httpx
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

# --- In-memory Task Database (UPDATED) ---
# Now stores more state for pausing and replanning
tasks_db = {}
# tasks_db[task_id] = {
#     "status": "PENDING",
#     "goal": "...",
#     "context": {...},
#     "plan": {...},
#     "current_step_index": 0,
#     "reason": "..."
# }
# ---

class InvokeRequest(BaseModel):
    goal: str
    context: dict = {}

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

# --- Service Discovery & Logging (No change) ---
async def discover(client: httpx.AsyncClient, service_name: str) -> str:
    """Finds a service's URL from the Directory (async)."""
    print(f"[Manager] Discovering: {service_name}")
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        r.raise_for_status()
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

# --- Service Registration (No change) ---
def register_self():
    while True:
        try:
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


# --- NEW: Multi-Step Execution Logic (Point 4) ---
async def execute_plan_from_step(task_id: str, step_index: int):
    """
    This function executes a plan step-by-step, starting from step_index.
    It's designed to be resumable.
    """
    task = tasks_db.get(task_id)
    if not task:
        print(f"[Manager] Task {task_id} not found for execution.")
        return

    plan = task.get("plan")
    if not plan or not plan.get("steps"):
        print(f"[Manager] No plan for task {task_id}.")
        return

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            for i in range(step_index, len(plan["steps"])):
                task["current_step_index"] = i
                step = plan["steps"][i]
                
                task["status"] = f"EXECUTING_STEP_{i+1}: {step['goal']}"
                await log_to_overseer(client, task_id, "INFO", f"Executing step {i+1}: {step['goal']}")

                # Call Partner to execute the *goal* (full ReAct loop)
                partner_url = await discover(client, "partner-service")
                p_resp = await client.post(f"{partner_url}/partner/execute_goal", json={
                    "task_id": task_id,
                    "current_step_goal": step["goal"],
                    "approved_plan": plan,
                    "context": task.get("context", {})
                }, headers=AUTH_HEADER) # UPDATED: /execute_goal
                
                partner_result = p_resp.json()
                await log_to_overseer(client, task_id, "INFO", f"Partner result: {partner_result.get('status')}", partner_result)

                # Handle Partner's response
                partner_status = partner_result.get("status")

                if partner_status == "STEP_COMPLETED":
                    # Good, continue to the next step in the loop
                    continue
                
                elif partner_status == "DEVIATION_DETECTED":
                    await log_to_overseer(client, task_id, "WARN", "Deviation detected. Pausing task for manual review.")
                    task["status"] = "PAUSED_DEVIATION"
                    task["reason"] = partner_result.get("reason")
                    return # Stop execution
                
                elif partner_status == "ACTION_REJECTED":
                    await log_to_overseer(client, task_id, "ERROR", "Task REJECTED: Guardian denied a critical step.")
                    task["status"] = "REJECTED"
                    task["reason"] = partner_result.get("reason")
                    return # Stop execution
                
                else: # FAILED or other
                    await log_to_overseer(client, task_id, "ERROR", "Task FAILED during partner execution.")
                    task["status"] = "FAILED"
                    task["reason"] = partner_result.get("reason", "Unknown partner failure")
                    return # Stop execution

            # If the loop completes without returning, the task is done
            await log_to_overseer(client, task_id, "INFO", "All steps completed. Task finished.")
            task["status"] = "COMPLETED"
            task["result"] = "All plan steps executed successfully."

        except Exception as e:
            print(f"[Manager] Unhandled exception in execute_plan {task_id}: {e}")
            try:
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {str(e)}")
            except: pass
            task["status"] = "FAILED"
            task["reason"] = str(e)
# --- END: Multi-Step Execution Logic ---


# --- Background Task Entry Point (UPDATED) ---
async def run_task_background(task_id: str, request: InvokeRequest):
    """
    This is the main entry point for a task.
    It generates the plan, validates it, and then hands off to execute_plan_from_step.
    """
    task = tasks_db[task_id]
    task["status"] = "STARTING"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await log_to_overseer(client, task_id, "INFO", f"Task started: {request.goal}")
            
            # Check Overseer status first
            task["status"] = "CHECKING_HALT"
            overseer_url = await discover(client, "overseer-service")
            status_resp = await client.get(f"{overseer_url}/control/status", headers=AUTH_HEADER)
            
            if status_resp.json().get("status") == "HALT":
                await log_to_overseer(client, task_id, "ERROR", "Task rejected: System is in HALT state.")
                task["status"] = "REJECTED"
                task["reason"] = "System is in HALT state"
                return

            # 1. Generate plan
            task["status"] = "PLANNING"
            await log_to_overseer(client, task_id, "INFO", "Generating execution plan...")
            plan_input = {"change_id": task_id, "goal": request.goal, "context": request.context}
            plan = use_agent("Create high-level plan for user goal", plan_input)
            task["plan"] = plan
            task["current_step_index"] = 0
            await log_to_overseer(client, task_id, "INFO", f"Plan generated with {len(plan.get('steps', []))} steps.", plan)
            
            # 2. Validate plan with Guardian
            task["status"] = "VALIDATING_PLAN"
            await log_to_overseer(client, task_id, "INFO", "Validating plan with Guardian...")
            guardian_url = await discover(client, "guardian-service")
            g_resp = await client.post(f"{guardian_url}/guardian/validate_plan", json={
                "task_id": task_id, "plan": plan
            }, headers=AUTH_HEADER)
            
            if g_resp.status_code != 200 or g_resp.json()["decision"] != "Allow":
                reason = g_resp.json().get("reason", "Unknown reason")
                await log_to_overseer(client, task_id, "ERROR", f"Plan validation FAILED: {reason}", g_resp.json())
                task["status"] = "REJECTED"
                task["reason"] = f"Plan validation failed: {reason}"
                return
            
            await log_to_overseer(client, task_id, "INFO", "Plan validation PASSED.")
            
            # 3. Execute plan (from step 0)
            if not plan.get("steps"):
                await log_to_overseer(client, task_id, "WARN", "Plan has no steps. Task considered complete.")
                task["status"] = "COMPLETED"
                task["result"] = "No steps to execute."
                return
                
            # Hand off to the resumable executor
            await execute_plan_from_step(task_id, 0)

        except Exception as e:
            # Catch-all for any unhandled exception during planning/validation
            print(f"[Manager] Unhandled exception in background task {task_id}: {e}")
            try:
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {str(e)}")
            except: pass
            task["status"] = "FAILED"
            task["reason"] = str(e)
# --- END: Background Task Entry Point ---


@app.post("/invoke", status_code=202)
async def invoke(request: InvokeRequest, background_tasks: BackgroundTasks):
    """Start a new high-level task in the background."""
    task_id = f"task-{uuid.uuid4()}"
    print(f"\n[Manager] === New Task Received ===\nTask ID: {task_id}\nGoal: {request.goal}\n")
    
    # Create initial task entry in DB
    tasks_db[task_id] = {
        "status": "PENDING", 
        "goal": request.goal, 
        "context": request.context,
        "current_step_index": 0
    }
    
    # Add the long-running job to the background
    background_tasks.add_task(run_task_background, task_id, request)
    
    return {
        "task_id": task_id, 
        "status": "PENDING", 
        "details": "Task accepted and is running in the background.",
        "status_url": f"/task/{task_id}/status"
    }

@app.get("/task/{task_id}/status", status_code=200)
def get_task_status(task_id: str):
    """Check the status of a background task."""
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return task

# --- UPDATED: Endpoints for Approval and Replanning (Point 4) ---

@app.post("/task/{task_id}/approve", status_code=202)
async def approve_task(task_id: str, background_tasks: BackgroundTasks):
    """Approve a paused task to resume execution."""
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
        
    if task["status"] not in ["PAUSED_DEVIATION", "ACTION_REJECTED"]:
        raise HTTPException(400, detail=f"Task is not in a pausable state. Current status: {task['status']}")

    step_to_resume = task.get("current_step_index", 0)
    
    print(f"[Manager] Resuming task {task_id} from step {step_to_resume + 1}")
    
    # Set status and add the *resumable* function to background
    task["status"] = "RESUMING"
    task["reason"] = "Resumed by user approval."
    
    background_tasks.add_task(execute_plan_from_step, task_id, step_to_resume)
    
    return {
        "task_id": task_id, 
        "status": "RESUMING",
        "details": f"Task resuming execution from step {step_to_resume + 1}."
    }

@app.post("/task/{task_id}/replan", status_code=202)
async def replan_task(task_id: str, request: InvokeRequest, background_tasks: BackgroundTasks):
    """Trigger a full replan of a task, optionally with a new goal/context."""
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")

    print(f"[Manager] Replanning task {task_id} with new goal: {request.goal}")

    # Update the task's core goal and context
    task["status"] = "REPLANNING"
    task["goal"] = request.goal
    task["context"] = request.context
    task["plan"] = {} # Clear the old plan
    task["current_step_index"] = 0
    task["reason"] = "Replanning triggered by user."
    
    # Add the *original* entry point function to background
    # This will generate a new plan, validate it, and execute it
    background_tasks.add_task(run_task_background, task_id, request)

    return {
        "task_id": task_id, 
        "status": "REPLANNING",
        "details": "Task replanning initiated with new goal."
    }
# --- End UPDATED Endpoints ---


if __name__ == "__main__":
    print("Starting Manager Service on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)