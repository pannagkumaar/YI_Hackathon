# 📄 partner_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
import random
from security import get_api_key # Import our new auth function

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Partner Service",
    description="ReAct Runtime worker for SHIVA.",
    dependencies=[Depends(get_api_key)] # Apply auth to all endpoints
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "partner-service"
SERVICE_PORT = 8002
# --- End Authentication & Service Constants ---


# --- Mock Agent Function ---
def use_agent(prompt: str, input_data: dict) -> dict:
    """Mock function for AI reasoning and observation."""
    print(f"[Partner] AI Agent called with prompt: {prompt}")
    
    if "Reason" in prompt:
        return {
            "thought": "I need to execute the approved step. My goal is to achieve the current step goal.",
            "action": "execute_tool",
            "action_input": {"tool_name": "mock_tool", "params": {"goal": input_data.get("current_step_goal")}}
        }
    if "Observe" in prompt:
        return {
            "observation": f"The tool execution resulted in: {input_data.get('result')}"
        }
    return {"output": "Mock AI response"}
# --- End Mock Agent Function ---


# --- Service Discovery & Logging (Copied from Manager, with Auth) ---
def discover(service_name: str) -> str:
    """Finds a service's URL from the Directory."""
    print(f"[Partner] Discovering: {service_name}")
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        if r.status_code != 200:
            print(f"[Partner] FAILED to discover {service_name}.")
            raise HTTPException(500, detail=f"Could not discover {service_name}")
        url = r.json()["url"]
        print(f"[Partner] Discovered {service_name} at {url}")
        return url
    except requests.exceptions.ConnectionError:
        print(f"[Partner] FAILED to connect to Directory at {DIRECTORY_URL}")
        raise HTTPException(500, detail="Could not connect to Directory Service")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service."""
    try:
        overseer_url = discover("overseer-service")
        requests.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[Partner] FAILED to log to Overseer: {e}")
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
                print(f"[Partner] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Partner] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[Partner] Could not connect to Directory. Retrying in 5s...")
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
            print("[Partner] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[Partner] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---

class ExecuteStep(BaseModel):
    task_id: str
    current_step_goal: str
    approved_plan: dict
    context: dict

@app.post("/partner/execute_step", status_code=200)
def execute_step(data: ExecuteStep):
    """Execute one step of the ReAct loop."""
    log_to_overseer(data.task_id, "INFO", f"Executing step: {data.current_step_goal}")
    
    # 1. Reason
    reasoning = use_agent("Reason about next step", data.dict())
    log_to_overseer(data.task_id, "INFO", f"Reasoning: {reasoning.get('thought')}", reasoning)
    
    # 2. NEW: Validate Action with Guardian
    try:
        guardian_url = discover("guardian-service")
        action_to_validate = f"{reasoning.get('action')}:{reasoning.get('action_input')}"
        
        g_resp = requests.post(f"{guardian_url}/guardian/validate_action", json={
            "task_id": data.task_id,
            "proposed_action": str(reasoning.get('action_input', {})), # Pass AI's intended action
            "context": data.context
        }, headers=AUTH_HEADER)

        if g_resp.status_code != 200 or g_resp.json()["decision"] != "Allow":
            reason = g_resp.json().get("reason", "Unknown reason")
            log_to_overseer(data.task_id, "ERROR", f"Action validation FAILED: {reason}", g_resp.json())
            return {"task_id": data.task_id, "status": "ACTION_REJECTED", "reason": f"Guardian denied action: {reason}"}
        
        log_to_overseer(data.task_id, "INFO", "Action validation PASSED.")
    
    except Exception as e:
        log_to_overseer(data.task_id, "ERROR", f"Failed to validate action with Guardian: {e}")
        raise HTTPException(500, "Failed to contact Guardian")

    # 3. Act (Simulated)
    log_to_overseer(data.task_id, "INFO", f"Taking action: {reasoning.get('action')} with input {reasoning.get('action_input')}")
    action_result = random.choice(["success", "deviation", "success", "success"])
    
    # 4. Observe
    observation = use_agent("Observe result", {"result": action_result})
    log_to_overseer(data.task_id, "INFO", f"Observation: {observation.get('observation')}", observation)
    
    if action_result == "success":
        return {
            "task_id": data.task_id, 
            "status": "STEP_COMPLETED", 
            "output": observation,
            "next_step_suggestion": "Proceed to next step"
        }
    else:
        return {
            "task_id": data.task_id, 
            "status": "DEVIATION_DETECTED", 
            "reason": "Unexpected deviation during tool execution",
            "details": observation
        }

if __name__ == "__main__":
    print("Starting Partner Service on port 8002...")
    uvicorn.run(app, host="0.0.0.0", port=8002)