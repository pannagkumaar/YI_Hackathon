# 📄 guardian_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key # Import our new auth function
from gemini_client import get_model, generate_json
import json
from typing import List # Import List

# --- MODIFIED: System Prompt ---
GUARDIAN_SYSTEM_PROMPT = """
You are the "Guardian," a compliance and safety assistant for the SHIVA agent system.
Your sole purpose is to evaluate a "proposed_action" or "plan" against a set of "policies."
You will also be given "Task Memory" (a history of recent T-A-O).

Use this memory to inform your decision. For example, if an action failed 
or was denied recently, you should be more cautious about allowing a similar action.

You must respond ONLY with a JSON object with two keys:
1. "decision": Must be either "Allow" or "Deny".
2. "reason": A brief, clear explanation for your decision.

Evaluate strictly. If a policy is "Disallow: <keyword>" and the <keyword> is in the 
proposed_action, you must "Deny" it. Also deny any plan with > 10 steps 
as "excessively complex".
"""
# --- END MODIFICATION ---
guardian_model = get_model(system_instruction=GUARDIAN_SYSTEM_PROMPT)
# --- Authentication & Service Constants ---
app = FastAPI(
    title="Guardian Service",
    description="Compliance and safety assistant for SHIVA.",
    dependencies=[Depends(get_api_key)] # Apply auth to all endpoints
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "guardian-service"
SERVICE_PORT = 8003
# --- End Authentication & Service Constants ---


# --- MODIFIED: Mock Agent Function ---
def use_agent(prompt: str, input_data: dict, policies: list, memory: list) -> dict:
    """(UPDATED) AI-based validation logic using Gemini."""
    print(f"[Guardian] AI Agent called with prompt: {prompt}")

    # Construct the prompt for the model
    prompt_parts = [
        f"User Prompt: {prompt}\n",
        f"Policies: {json.dumps(policies)}\n",
        f"Task Memory (Recent): {json.dumps(memory[-5:])}\n", # Pass only recent memory
        f"Input Data: {json.dumps(input_data)}\n\n",
        "Evaluate the input and return your JSON decision (decision, reason)."
    ]
    
    # Call the helper
    validation = generate_json(guardian_model, prompt_parts)
    
    # Fallback in case of JSON error
    if "error" in validation or "decision" not in validation:
        print(f"[Guardian] AI validation failed: {validation.get('error', 'Invalid format')}")
        return {"decision": "Deny", "reason": f"AI model error: {validation.get('error', 'Invalid format')}"}

    return validation
# --- END MODIFICATION ---


# --- Service Discovery & Logging (Copied from Manager, with Auth) ---
def discover(service_name: str) -> str:
    """Finds a service's URL from the Directory."""
    print(f"[Guardian] Discovering: {service_name}")
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        if r.status_code != 200:
            print(f"[Guardian] FAILED to discover {service_name}.")
            raise HTTPException(500, detail=f"Could not discover {service_name}")
        url = r.json()["url"]
        print(f"[Guardian] Discovered {service_name} at {url}")
        return url
    except requests.exceptions.ConnectionError:
        print(f"[Guardian] FAILED to connect to Directory at {DIRECTORY_URL}")
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
        print(f"[Guardian] FAILED to log to Overseer: {e}")
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
            }, headers=AUTH_HEADER) # Auth
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


# --- Utility Function to Fetch Policies ---
def get_policies_from_hub(task_id: str) -> list:
    """Fetches the latest policies from the Resource Hub."""
    try:
        hub_url = discover("resource-hub-service")
        resp = requests.get(f"{hub_url}/policy/list", params={"context": "global"}, headers=AUTH_HEADER)
        if resp.status_code == 200:
            policies = resp.json().get("policies", [])
            log_to_overseer(task_id, "INFO", f"Fetched {len(policies)} policies from Resource Hub.")
            return policies
        log_to_overseer(task_id, "WARN", f"Failed to fetch policies from Resource Hub: {resp.text}")
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Error fetching policies: {e}")
    return [] # Default to empty list on failure
# --- End Utility Function ---

# --- NEW: Utility Function to Fetch Memory ---
def get_memory_from_hub(task_id: str) -> list:
    """Fetches the latest task memory from the Resource Hub."""
    try:
        hub_url = discover("resource-hub-service")
        resp = requests.get(f"{hub_url}/memory/{task_id}", headers=AUTH_HEADER)
        if resp.status_code == 200:
            memory = resp.json() # This returns a List[MemoryEntry]
            log_to_overseer(task_id, "INFO", f"Fetched {len(memory)} memory entries from Resource Hub.")
            return memory
        log_to_overseer(task_id, "WARN", f"Failed to fetch memory from Resource Hub: {resp.text}")
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Error fetching memory: {e}")
    return [] # Default to empty list on failure
# --- END NEW Utility Function ---


# --- MODIFIED: validate_action ---
@app.post("/guardian/validate_action", status_code=200)
def validate_action(data: ValidateAction):
    """Validate a single proposed action before execution."""
    log_to_overseer(data.task_id, "INFO", f"Validating action: {data.proposed_action}")
    
    # Fetch dynamic policies
    policies = get_policies_from_hub(data.task_id)
    # NEW: Fetch task memory
    memory = get_memory_from_hub(data.task_id)
    
    # Use the mock AI agent for a decision
    validation = use_agent(
        "Validate this single action for safety and compliance",
        data.dict(),
        policies,
        memory # Pass memory
    )
    
    if validation["decision"] != "Allow":
        log_to_overseer(data.task_id, "WARN", f"Action DENIED: {validation['reason']}", validation)
    else:
        log_to_overseer(data.task_id, "INFO", "Action ALLOWED.")
        
    return validation
# --- END MODIFICATION ---

# --- MODIFIED: validate_plan ---
@app.post("/guardian/validate_plan", status_code=200)
def validate_plan(data: ValidatePlan):
    """Validate a high-level execution plan."""
    log_to_overseer(data.task_id, "INFO", f"Validating plan with {len(data.plan.get('steps',[]))} steps.")
    
    # Fetch dynamic policies
    policies = get_policies_from_hub(data.task_id)
    # NEW: Fetch task memory
    memory = get_memory_from_hub(data.task_id)

    # Use the mock AI agent for a decision
    validation = use_agent(
        "Validate this multi-step plan for safety and complexity",
        data.dict(),
        policies,
        memory # Pass memory
    )

    if validation["decision"] != "Allow":
        log_to_overseer(data.task_id, "WARN", f"Plan DENIED: {validation['reason']}", validation)
    else:
        log_to_overseer(data.task_id, "INFO", "Plan ALLOWED.")
        
    return validation
# --- END MODIFICATION ---

if __name__ == "__main__":
    print("Starting Guardian Service on port 8003...")
    uvicorn.run(app, host="0.0.0.0", port=8003)