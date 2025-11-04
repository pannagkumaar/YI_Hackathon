from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
import random

app = FastAPI(title="Partner Service", description="ReAct Runtime worker for SHIVA.")

DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "partner-service"
SERVICE_PORT = 8002

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
            })
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
    print(f"[Partner] Executing step for task {data.task_id}: {data.current_step_goal}")
    
    # 1. Reason
    reasoning = use_agent("Reason about next step", data.dict())
    print(f"[Partner] Reasoning: {reasoning.get('thought')}")
    
    # 2. Act (Simulated)
    # Here you would call Guardian to validate the 'reasoning.get('action')'
    # Skipping for this mock, as Manager already validated the high-level plan
    print(f"[Partner] Taking action: {reasoning.get('action')} with input {reasoning.get('action_input')}")
    action_result = random.choice(["success", "deviation", "success", "success"]) # Skew towards success
    
    # 3. Observe
    observation = use_agent("Observe result", {"result": action_result})
    print(f"[Partner] Observation: {observation.get('observation')}")
    
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
