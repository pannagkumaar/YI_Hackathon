# 📄 resource_hub_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key
from typing import List

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Resource Hub Service",
    description="Provides tools, policies, and memory for SHIVA agents.",
    dependencies=[Depends(get_api_key)]
)
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "resource-hub-service"
SERVICE_PORT = 8006
# --- End Authentication & Service Constants ---

# --- MODIFIED: Mock Database ---
# MOCK_POLICIES is now POLICY_DB to show it's dynamic
POLICY_DB = {
    "global": [
        "Disallow: delete",
        "Disallow: shutdown",
        "Disallow: rm -rf"
    ]
}
# --- END MODIFICATION ---

MOCK_TOOLS = {
    "tools": [
        {"name": "run_script", "description": "Executes a python script."},
        {"name": "fetch_data", "description": "Fetches data from an API."}
    ]
}

# --- Short-Term Memory Database ---
# Stores { "task_id": [ { "thought": "...", "action": "...", "observation": "..." } ] }
tasks_memory = {}
# --- End Mock Database ---

# --- Pydantic Model for Memory ---
class MemoryEntry(BaseModel):
    thought: str
    action: str
    observation: str
# ---

# --- NEW: Pydantic Model for Policy ---
class PolicyEntry(BaseModel):
    context: str = "global"
    policy_rule: str # e.g., "Disallow: curl"
# ---

# --- Service Discovery & Logging (No change) ---
def discover(service_name: str) -> str:
    """Finds a service's URL from the Directory."""
    print(f"[ResourceHub] Discovering: {service_name}")
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        if r.status_code != 200:
            print(f"[ResourceHub] FAILED to discover {service_name}.")
            raise HTTPException(500, detail=f"Could not discover {service_name}")
        url = r.json()["url"]
        print(f"[ResourceHub] Discovered {service_name} at {url}")
        return url
    except requests.exceptions.ConnectionError:
        print(f"[ResourceHub] FAILED to connect to Directory at {DIRECTORY_URL}")
        raise HTTPException(500, detail="Could not connect to Directory Service")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service."""
    try:
        overseer_url = discover("overseer-service") # Corrected: 'overseer-service'
        requests.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[ResourceHub] FAILED to log to Overseer: {e}")
# --- End Service Discovery & Logging ---

# --- Service Registration (No change) ---
def register_self():
    """Registers this service with the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            if r.status_code == 200:
                print(f"[ResourceHub] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[ResourceHub] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[ResourceHub] Could not connect to Directory. Retrying in 5s...")
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
            }, headers=AUTH_HEADER)
            print("[ResourceHub] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[ResourceHub] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---


# --- API Endpoints (UPDATED) ---

# --- MODIFIED: Policy Endpoints ---
@app.get("/policy/list", status_code=200)
def get_policies(context: str = "global"):
    """Fetch compliance policies."""
    log_to_overseer("N/A", "INFO", f"Policy list requested for context: {context}")
    # Read from the dynamic DB instead of the static MOCK
    return {"policies": POLICY_DB.get(context, [])}

@app.post("/policy/add", status_code=201)
def add_policy(entry: PolicyEntry):
    """Add a new policy rule to a context."""
    context = entry.context
    rule = entry.policy_rule
    
    if context not in POLICY_DB:
        POLICY_DB[context] = []
        
    if rule not in POLICY_DB[context]:
        POLICY_DB[context].append(rule)
        log_to_overseer("N/A", "INFO", f"Policy added to '{context}': {rule}")
        return {"status": "Policy added", "context": context, "rule": rule}
    
    log_to_overseer("N/A", "WARN", f"Policy already exists in '{context}': {rule}")
    return {"status": "Policy already exists", "context": context, "rule": rule}

@app.post("/policy/delete", status_code=200)
def delete_policy(entry: PolicyEntry):
    """Remove a policy rule from a context."""
    context = entry.context
    rule = entry.policy_rule
    
    if context in POLICY_DB and rule in POLICY_DB[context]:
        POLICY_DB[context].remove(rule)
        log_to_overseer("N/A", "INFO", f"Policy removed from '{context}': {rule}")
        return {"status": "Policy removed", "context": context, "rule": rule}

    log_to_overseer("N/A", "WARN", f"Policy not found in '{context}': {rule}")
    raise HTTPException(404, detail="Policy not found")
# --- END MODIFICATION ---


@app.get("/tools/list", status_code=200)
def get_tools():
    """Fetch available tools for agents."""
    log_to_overseer("N/A", "INFO", "Tool list requested.")
    return MOCK_TOOLS

# --- Memory Endpoints (No change) ---

@app.post("/memory/{task_id}", status_code=201)
def add_memory(task_id: str, entry: MemoryEntry):
    """Add a (Thought, Action, Observation) entry to short-term memory."""
    if task_id not in tasks_memory:
        tasks_memory[task_id] = []
    
    tasks_memory[task_id].append(entry.dict())
    log_to_overseer(task_id, "INFO", f"Memory entry added for task {task_id}")
    return {"status": "Memory added", "entries": len(tasks_memory[task_id])}

@app.get("/memory/{task_id}", status_code=200, response_model=List[MemoryEntry])
def get_memory(task_id: str):
    """Retrieve the full short-term memory history for a task."""
    if task_id not in tasks_memory:
        log_to_overseer(task_id, "WARN", f"No memory found for task {task_id}")
        return []
    
    log_to_overseer(task_id, "INFO", f"Memory retrieved for task {task_id}")
    return tasks_memory[task_id]

@app.get("/memory/query/{task_id}", status_code=200)
def query_rag(task_id: str, query: str):
    """(Mock RAG) Query the task's memory for insights."""
    
    memory_history = tasks_memory.get(task_id, [])
    log_to_overseer(task_id, "INFO", f"RAG query received: {query}")
    
    # Mock RAG: A real implementation would use LangChain + ChromaDB
    # This mock just looks for keywords in the memory
    
    if not memory_history:
        return {"insight": "No memory to analyze, but I'll try my best."}

    history_str = str(memory_history)
    insight = f"Mock RAG insight based on {len(memory_history)} entries. "
    if "error" in history_str.lower():
        insight += "Analysis of memory shows a previous error was encountered."
    elif "success" in history_str.lower():
        insight += "Analysis of memory shows previous steps were successful."
    else:
        insight += "Memory seems nominal."
        
    return {"insight": insight}

# --- End NEW Memory Endpoints ---

if __name__ == "__main__":
    print(f"Starting Resource Hub Service on port {SERVICE_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)