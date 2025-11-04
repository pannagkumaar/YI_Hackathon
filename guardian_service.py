from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time

app = FastAPI(title="Guardian Service", description="Compliance and safety assistant for SHIVA.")

DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "guardian-service"
SERVICE_PORT = 8003

# --- Mock Agent Function ---
def use_agent(prompt: str, input_data: dict) -> dict:
    """Mock function for AI-based validation logic."""
    print(f"[Guardian] AI Agent called with prompt: {prompt}")
    
    # Simple rule-based mock for demonstration
    proposed_action = input_data.get("proposed_action", "")
    if "delete" in proposed_action.lower() or "shutdown" in proposed_action.lower():
        return {"decision": "Deny", "reason": "Unsafe keyword detected by AI model."}
    
    plan_steps = input_data.get("plan", {}).get("steps", [])
    if len(plan_steps) > 10:
        return {"decision": "Deny", "reason": "AI model flags plan as 'excessively complex' (>10 steps)."}
        
    return {"decision": "Allow", "reason": "AI model validation passed."}
# --- End Mock Agent Function ---

# --- Service Registration ---
def register_self():
    """Registers this service with the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            })
            if r.status_code == 200:
                print(f"[Guardian] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Guardian] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[Guardian] Could not connect to Directory. Retrying in 5s...")
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
            })
            print("[Guardian] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[Guardian] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---

class ValidateAction(BaseModel):
    task_id: str
    proposed_action: str
    context: dict

class ValidatePlan(BaseModel):
    task_id: str
    plan: dict # e.g., {"steps": [...]}

@app.post("/guardian/validate_action", status_code=200)
def validate_action(data: ValidateAction):
    """Validate a single proposed action before execution."""
    print(f"[Guardian] Validating action for task {data.task_id}: {data.proposed_action}")
    
    # Use the mock AI agent for a decision
    validation = use_agent("Validate this single action for safety and compliance", data.dict())
    
    if validation["decision"] != "Allow":
        print(f"[Guardian] Action DENIED: {validation['reason']}")
    else:
        print(f"[Guardian] Action ALLOWED.")
        
    return validation

@app.post("/guardian/validate_plan", status_code=200)
def validate_plan(data: ValidatePlan):
    """Validate a high-level execution plan."""
    print(f"[Guardian] Validating plan for task {data.task_id}")
    
    # Use the mock AI agent for a decision
    validation = use_agent("Validate this multi-step plan for safety and complexity", data.dict())

    if validation["decision"] != "Allow":
        print(f"[Guardian] Plan DENIED: {validation['reason']}")
    else:
        print(f"[Guardian] Plan ALLOWED.")
        
    return validation

if __name__ == "__main__":
    print("Starting Guardian Service on port 8003...")
    uvicorn.run(app, host="0.0.0.0", port=8003)
