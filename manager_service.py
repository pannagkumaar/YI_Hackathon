# 📄 manager_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
import uuid
from security import get_api_key # Import our new auth function

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Manager Service",
    description="Orchestrator for SHIVA.",
    dependencies=[Depends(get_api_key)] # Apply auth to all endpoints
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "manager-service"
SERVICE_PORT = 8001
# --- End Authentication & Service Constants ---


# --- Mock Agent Function ---
def use_agent(prompt: str, input_data: dict) -> dict:
    """Mock function for AI-based planning."""
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

# --- Service Discovery & Logging (UPDATED with Auth) ---
def discover(service_name: str) -> str:
    """Finds a service's URL from the Directory."""
    print(f"[Manager] Discovering: {service_name}")
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER # Auth
        )
        if r.status_code != 200:
            print(f"[Manager] FAILED to discover {service_name}. Directory response: {r.text}")
            raise HTTPException(500, detail=f"Could not discover {service_name}: {r.text}")
        url = r.json()["url"]
        print(f"[Manager] Discovered {service_name} at {url}")
        return url
    except requests.exceptions.ConnectionError:
        print(f"[Manager] FAILED to connect to Directory at {DIRECTORY_URL}")
        raise HTTPException(500, detail="Could not connect to Directory Service")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service."""
    try:
        overseer_url = discover("overseer-service")
        requests.post(f"{overseer_url}/log/event", json={
            "service": "manager-service",
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER) # Auth
    except Exception as e:
        print(f"[Manager] FAILED to log to Overseer: {e}")
        # Don't fail the whole request, just print the error
# --- End Service Discovery & Logging ---

# --- Service Registration (UPDATED with Auth) ---
def register_self():
    """Registers this service with the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER) # Auth
            if r.status_code == 200:
                print(f"[Manager] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Manager] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[Manager] Could not connect to Directory. Retrying in 5s...")
        time.sleep(5)

def heartbeat():
    """Sends a periodic heartbeat to the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER) # Auth
            print("[Manager] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
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

@app.post("/invoke", status_code=202)
def invoke(request: InvokeRequest):
    """Start a new high-level task."""
    task_id = f"task-{uuid.uuid4()}"
    print(f"\n[Manager] === New Task Received ===\nTask ID: {task_id}\nGoal: {request.goal}\n")
    log_to_overseer(task_id, "INFO", f"Task started: {request.goal}")

    try:
        # Check Overseer status first
        overseer_url = discover("overseer-service")
        status_resp = requests.get(f"{overseer_url}/control/status", headers=AUTH_HEADER) # Auth
        if status_resp.json().get("status") == "HALT":
            log_to_overseer(task_id, "ERROR", "Task rejected: System is in HALT state.")
            raise HTTPException(503, "System is in HALT state")
        
        # 1. Generate plan
        log_to_overseer(task_id, "INFO", "Generating execution plan...")
        plan_input = {"change_id": task_id, "goal": request.goal, "context": request.context}
        plan = use_agent("Create high-level plan for user goal", plan_input)
        log_to_overseer(task_id, "INFO", f"Plan generated with {len(plan.get('steps', []))} steps.", plan)
        
        # 2. Validate plan with Guardian
        log_to_overseer(task_id, "INFO", "Validating plan with Guardian...")
        guardian_url = discover("guardian-service")
        g_resp = requests.post(f"{guardian_url}/guardian/validate_plan", json={
            "task_id": task_id,
            "plan": plan
        }, headers=AUTH_HEADER) # Auth
        
        if g_resp.status_code != 200 or g_resp.json()["decision"] != "Allow":
            reason = g_resp.json().get("reason", "Unknown reason")
            log_to_overseer(task_id, "ERROR", f"Plan validation FAILED: {reason}", g_resp.json())
            return {"task_id": task_id, "status": "REJECTED", "reason": f"Plan validation failed: {reason}"}
        
        log_to_overseer(task_id, "INFO", "Plan validation PASSED.")
        
        # 3. Execute plan with Partner (simplified: just run first step)
        if not plan.get("steps"):
            log_to_overseer(task_id, "WARN", "Plan has no steps. Task considered complete.")
            return {"task_id": task_id, "status": "COMPLETED", "result": "No steps to execute."}
            
        first_step = plan["steps"][0]
        log_to_overseer(task_id, "INFO", f"Executing first step: {first_step['goal']}")
        
        partner_url = discover("partner-service")
        p_resp = requests.post(f"{partner_url}/partner/execute_step", json={
            "task_id": task_id,
            "current_step_goal": first_step["goal"],
            "approved_plan": plan,
            "context": request.context
        }, headers=AUTH_HEADER) # Auth
        
        partner_result = p_resp.json()
        log_to_overseer(task_id, "INFO", f"Partner execution result: {partner_result.get('status')}", partner_result)
        
        # 4. Handle result
        if partner_result.get("status") == "DEVIATION_DETECTED":
            log_to_overseer(task_id, "WARN", "Deviation detected. Stopping task for manual review.")
            return {"task_id": task_id, "status": "PAUSED_DEVIATION", "details": partner_result}
        
        if partner_result.get("status") == "ACTION_REJECTED":
            log_to_overseer(task_id, "ERROR", "Task REJECTED: Guardian denied a critical step.")
            return {"task_id": task_id, "status": "REJECTED", "details": partner_result}

        log_to_overseer(task_id, "INFO", "Task completed (mock: only first step).")
        return {"task_id": task_id, "status": "COMPLETED", "result": partner_result}

    except HTTPException as e:
        log_to_overseer(task_id, "ERROR", f"HTTPException occurred: {e.detail}")
        raise e
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Unhandled exception: {str(e)}")
        raise HTTPException(500, detail=f"Internal server error: {str(e)}")

# Add stub endpoints from your prompt
@app.post("/task/{task_id}/approve")
def approve_task(task_id: str):
    log_to_overseer(task_id, "INFO", "Task manually approved. Resuming...")
    # TODO: Add logic to re-trigger partner
    return {"task_id": task_id, "status": "Resuming (Not Implemented)"}

@app.post("/task/{task_id}/replan")
def replan_task(task_id: str):
    log_to_overseer(task_id, "INFO", "Task replan triggered...")
    # TODO: Add logic to call use_agent and restart the loop
    return {"task_id": task_id, "status": "Replanning (Not Implemented)"}


if __name__ == "__main__":
    print("Starting Manager Service on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)