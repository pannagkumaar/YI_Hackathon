# 📄 resource_hub_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key
from typing import List, Any # --- NEW ---

# --- NEW: Imports for tool execution ---
import subprocess
import sys
# --- END NEW ---

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
POLICY_DB = {
    "global": [
        "Disallow: delete",
        "Disallow: shutdown",
        "Disallow: rm -rf"
    ]
}

# --- UPDATED: MOCK_TOOLS now includes the new deploy_model tool ---
MOCK_TOOLS = {
    "tools": [
        {
            "name": "deploy_model",
            "description": "Deploys a specific model version to the production environment.",
            "parameters": {
                "model_version": "string (e.g., '1.2.3')",
                "environment": "string (default: 'production')"
            }
        },
        {
            "name": "run_script",
            "description": "Executes a pre-defined, safe script. (e.g., a deployment script).",
            "parameters": {
                "script_name": "string (e.g., 'deploy_model.py')",
                "args": "list[string] (e.g., ['--version', '1.2.3'])"
            }
        },
        {
            "name": "fetch_data",
            "description": "Fetches data from a given URL.",
            "parameters": {
                "url": "string (e.g., 'https://api.example.com/data')"
            }
        }
    ]
}
# --- END UPDATED ---

# --- Short-Term Memory Database ---
tasks_memory = {}
# --- End Mock Database ---

# --- Pydantic Model for Memory ---
class MemoryEntry(BaseModel):
    thought: str
    action: str
    observation: str

class PolicyEntry(BaseModel):
    context: str = "global"
    policy_rule: str 

# --- NEW: Pydantic Model for Tool Execution ---
class ToolExecution(BaseModel):
    tool_name: str
    parameters: dict
    task_id: str
# --- END NEW ---

# --- Service Discovery & Logging (No change) ---
def discover(service_name: str) -> str:
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
        print(f"[ResourceHub] FAILED to log to Overseer: {e}")
# --- End Service Discovery & Logging ---

# --- Service Registration (No change) ---
def register_self():
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

# --- Policy Endpoints (No change) ---
@app.get("/policy/list", status_code=200)
def get_policies(context: str = "global"):
    log_to_overseer("N/A", "INFO", f"Policy list requested for context: {context}")
    return {"policies": POLICY_DB.get(context, [])}

@app.post("/policy/add", status_code=201)
def add_policy(entry: PolicyEntry):
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
    context = entry.context
    rule = entry.policy_rule
    
    if context in POLICY_DB and rule in POLICY_DB[context]:
        POLICY_DB[context].remove(rule)
        log_to_overseer("N/A", "INFO", f"Policy removed from '{context}': {rule}")
        return {"status": "Policy removed", "context": context, "rule": rule}

    log_to_overseer("N/A", "WARN", f"Policy not found in '{context}': {rule}")
    raise HTTPException(404, detail="Policy not found")
# --- End Policy Endpoints ---


@app.get("/tools/list", status_code=200)
def get_tools():
    """Fetch available tools for agents."""
    log_to_overseer("N/A", "INFO", "Tool list requested.")
    return MOCK_TOOLS

# --- UPDATED: Tool Execution Endpoint (The "Armory") ---
@app.post("/tools/execute", status_code=200)
def execute_tool(exec_data: ToolExecution):
    """(The Armory) Securely execute a given tool."""
    
    tool_name = exec_data.tool_name
    params = exec_data.parameters
    task_id = exec_data.task_id
    
    log_to_overseer(task_id, "INFO", f"Armory: Executing tool '{tool_name}'", params)
    
    try:
        if tool_name == "run_script":
            # --- Sandboxed Execution ---
            # This is a *safe* demonstration. It runs 'echo' instead of 
            # a real script, preventing any harm.
            # A real implementation would run `[sys.executable, script_name, *args]`
            # inside a Docker container or with tighter permissions.
            script_name = params.get("script_name", "unknown_script.py")
            args = params.get("args", [])
            
            # Safe command: just echo the script name and args
            cmd = ["echo", f"Simulating run of script '{script_name}' with args: {args}"]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=10, 
                check=False # Don't raise error on non-zero exit
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                log_to_overseer(task_id, "INFO", f"Tool '{tool_name}' success: {output}")
                return {"status": "success", "output": output}
            else:
                error = result.stderr.strip()
                log_to_overseer(task_id, "WARN", f"Tool '{tool_name}' deviation: {error}")
                return {"status": "deviation", "error": error}

        # --- THIS IS THE NEWLY ADDED BLOCK ---
        elif tool_name == "deploy_model":
            # This is a safe, simulated deployment
            model_version = params.get("model_version")
            env = params.get("environment", "production") # Default to production
            
            if not model_version:
                # If the AI forgot the version, return a deviation
                log_to_overseer(task_id, "WARN", "Tool 'deploy_model' deviation: Missing 'model_version'")
                return {"status": "deviation", "error": "Missing 'model_version' parameter"}

            # Simulate the deployment work (e.g., 1 second delay)
            time.sleep(1) 
            
            output = f"Successfully simulated deployment of model v{model_version} to {env}."
            log_to_overseer(task_id, "INFO", f"Tool '{tool_name}' success: {output}")
            return {"status": "success", "output": output}
        # --- END OF NEW BLOCK ---

        elif tool_name == "fetch_data":
            # --- Real Network Tool ---
            url = params.get("url")
            if not url:
                raise ValueError("Missing 'url' parameter for fetch_data")
            
            r = requests.get(url, timeout=10)
            r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            
            # Return first 500 chars of output
            output = r.text[:500] + "..." if len(r.text) > 500 else r.text
            log_to_overseer(task_id, "INFO", f"Tool '{tool_name}' success: Fetched data from {url}")
            return {"status": "success", "output": f"Fetched {len(r.text)} bytes. Content: {output}"}
            
        else:
            raise HTTPException(404, detail=f"Tool '{tool_name}' not found in Armory.")

    except Exception as e:
        # Catch-all for subprocess timeouts, requests errors, etc.
        log_to_overseer(task_id, "ERROR", f"Tool '{tool_name}' failed: {e}", params)
        return {"status": "deviation", "error": f"Tool failed to execute: {str(e)}"}
# --- END UPDATED ---


# --- Memory Endpoints (No change) ---
@app.post("/memory/{task_id}", status_code=201)
def add_memory(task_id: str, entry: MemoryEntry):
    if task_id not in tasks_memory:
        tasks_memory[task_id] = []
    
    tasks_memory[task_id].append(entry.dict())
    log_to_overseer(task_id, "INFO", f"Memory entry added for task {task_id}")
    return {"status": "Memory added", "entries": len(tasks_memory[task_id])}

@app.get("/memory/{task_id}", status_code=200, response_model=List[MemoryEntry])
def get_memory(task_id: str):
    if task_id not in tasks_memory:
        log_to_overseer(task_id, "WARN", f"No memory found for task {task_id}")
        return []
    
    log_to_overseer(task_id, "INFO", f"Memory retrieved for task {task_id}")
    return tasks_memory[task_id]

@app.get("/memory/query/{task_id}", status_code=200)
def query_rag(task_id: str, query: str):
    memory_history = tasks_memory.get(task_id, [])
    log_to_overseer(task_id, "INFO", f"RAG query received: {query}")
    
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
# --- End Memory Endpoints ---

if __name__ == "__main__":
    print(f"Starting Resource Hub Service on port {SERVICE_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)