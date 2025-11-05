# 📄 partner_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests  # Keep for synchronous registration
import httpx     # Use for async calls
import threading
import time
import random
from security import get_api_key
from typing import List

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Partner Service",
    description="ReAct Runtime worker for SHIVA.",
    dependencies=[Depends(get_api_key)]
)
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "partner-service"
SERVICE_PORT = 8002
# --- End Authentication & Service Constants ---


# --- Mock Agent Function (UPDATED for ReAct Loop) ---
def use_agent(prompt: str, goal: str, tools: List[dict], history: List[dict]) -> dict:
    """Mock function for AI reasoning and observation."""
    print(f"[Partner] AI Agent called with prompt: {prompt}")
    
    if prompt == "Reason":
        # Check if goal is already met based on history
        if history and "success" in history[-1].get("observation", ""):
            return {
                "thought": "The last observation indicates success. The goal is complete.",
                "action": "finish_goal",
                "action_input": {}
            }

        # If not, pick a tool
        tool_to_use = random.choice(tools)
        return {
            "thought": f"I need to achieve the goal: '{goal}'. I will use the tool '{tool_to_use['name']}'.",
            "action": tool_to_use['name'],
            "action_input": {"goal": goal, "params": "mock_params"}
        }
    
    if prompt == "Observe":
        observation_text = f"The tool execution resulted in: {goal}"
        return {
            "observation": observation_text
        }
    
    return {"output": "Mock AI response"}
# --- End Mock Agent Function ---


# --- Service Discovery & Logging (UPDATED with Async) ---
async def discover_async(client: httpx.AsyncClient, service_name: str) -> str:
    """Finds a service's URL from the Directory (async)."""
    print(f"[Partner] Discovering: {service_name}")
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        r.raise_for_status()
        url = r.json()["url"]
        print(f"[Partner] Discovered {service_name} at {url}")
        return url
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"[Partner] FAILED to discover {service_name}: {e}")
        raise HTTPException(500, detail=f"Could not discover {service_name}")

async def log_to_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service (async)."""
    try:
        overseer_url = await discover_async(client, "overseer-service")
        await client.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[Partner] FAILED to log to Overseer: {e}")
# --- End Service Discovery & Logging ---


# --- NEW: Resource Hub Helpers (Point 3) ---
async def get_tools_from_hub(client: httpx.AsyncClient, task_id: str) -> List[dict]:
    """Fetches the list of available tools from the Resource Hub."""
    try:
        hub_url = await discover_async(client, "resource-hub-service")
        resp = await client.get(f"{hub_url}/tools/list", headers=AUTH_HEADER)
        resp.raise_for_status()
        await log_to_overseer(client, task_id, "INFO", "Successfully fetched tools from Resource Hub.")
        return resp.json().get("tools", [])
    except Exception as e:
        await log_to_overseer(client, task_id, "ERROR", f"Failed to fetch tools from Resource Hub: {e}")
        return [] # Return empty list on failure

async def log_memory_to_hub(client: httpx.AsyncClient, task_id: str, thought: str, action: str, observation: str):
    """Logs a (T, A, O) entry to the Resource Hub's short-term memory."""
    try:
        hub_url = await discover_async(client, "resource-hub-service")
        await client.post(f"{hub_url}/memory/{task_id}", json={
            "thought": thought,
            "action": action,
            "observation": observation
        }, headers=AUTH_HEADER)
    except Exception as e:
        # Log to overseer to report the failure, but don't crash the loop
        await log_to_overseer(client, task_id, "WARN", f"Failed to log memory to Resource Hub: {e}")
# --- END: Resource Hub Helpers ---


# --- Service Registration (No change, uses synchronous requests) ---
def register_self():
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
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
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            print("[Partner] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[Partner] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---

class ExecuteGoal(BaseModel):
    task_id: str
    current_step_goal: str
    approved_plan: dict
    context: dict

# --- UPDATED: Main ReAct Loop Endpoint (Point 1) ---
@app.post("/partner/execute_goal", status_code=200)
async def execute_goal(data: ExecuteGoal):
    """Execute a full ReAct loop until the goal is completed or fails."""
    
    task_id = data.task_id
    goal = data.current_step_goal
    history = []
    max_loops = 5 # Safety break

    async with httpx.AsyncClient(timeout=30.0) as client:
        await log_to_overseer(client, task_id, "INFO", f"Starting ReAct loop for goal: {goal}")
        
        # Point 3: Get tools from Resource Hub
        tools = await get_tools_from_hub(client, task_id)
        if not tools:
            await log_to_overseer(client, task_id, "ERROR", "No tools found. Cannot execute goal.")
            return {"task_id": task_id, "status": "FAILED", "reason": "No tools available from Resource Hub"}

        for i in range(max_loops):
            # 1. Reason
            reasoning = use_agent("Reason", goal, tools, history)
            thought = reasoning.get("thought")
            action = reasoning.get("action")
            action_input = reasoning.get("action_input")
            
            await log_to_overseer(client, task_id, "INFO", f"[Loop {i+1}] Thought: {thought}", reasoning)

            # Check for goal completion
            if action == "finish_goal":
                await log_memory_to_hub(client, task_id, thought, "finish_goal", "Goal completed successfully.")
                await log_to_overseer(client, task_id, "INFO", f"Goal completed: {goal}")
                return {
                    "task_id": task_id, 
                    "status": "STEP_COMPLETED", 
                    "output": {"observation": "Goal completed successfully."}
                }
            
            # 2. Validate Action with Guardian
            try:
                guardian_url = await discover_async(client, "guardian-service")
                g_resp = await client.post(f"{guardian_url}/guardian/validate_action", json={
                    "task_id": task_id,
                    "proposed_action": f"{action}:{action_input}",
                    "context": data.context
                }, headers=AUTH_HEADER)
                g_resp.raise_for_status()

                if g_resp.json()["decision"] != "Allow":
                    reason = g_resp.json().get("reason", "Unknown reason")
                    await log_to_overseer(client, task_id, "ERROR", f"Action validation FAILED: {reason}", g_resp.json())
                    return {"task_id": task_id, "status": "ACTION_REJECTED", "reason": f"Guardian denied action: {reason}"}
                
                await log_to_overseer(client, task_id, "INFO", f"Action validation PASSED: {action}")
            
            except Exception as e:
                await log_to_overseer(client, task_id, "ERROR", f"Failed to validate action with Guardian: {e}")
                return {"task_id": task_id, "status": "FAILED", "reason": "Failed to contact Guardian"}

            # 3. Act (Simulated)
            await log_to_overseer(client, task_id, "INFO", f"Taking action: {action} with input {action_input}")
            action_result = random.choice(["success", "deviation", "success", "success"])
            
            # 4. Observe
            observation = use_agent("Observe", action_result, tools, history)
            observation_text = observation.get('observation', 'No observation.')
            await log_to_overseer(client, task_id, "INFO", f"Observation: {observation_text}", observation)
            
            # 5. Log to Memory (Point 3)
            history.append({"thought": thought, "action": action, "observation": observation_text})
            await log_memory_to_hub(client, task_id, thought, action, observation_text)
            
            # 6. Handle Deviation
            if action_result == "deviation":
                await log_to_overseer(client, task_id, "WARN", "Deviation detected. Pausing task.")
                return {
                    "task_id": task_id, 
                    "status": "DEVIATION_DETECTED", 
                    "reason": "Unexpected deviation during tool execution",
                    "details": observation
                }

        # If loop finishes without completion
        await log_to_overseer(client, task_id, "ERROR", "Task failed: Max loops exceeded.")
        return {"task_id": task_id, "status": "FAILED", "reason": "Max loops exceeded"}
# --- End ReAct Loop ---

if __name__ == "__main__":
    print("Starting Partner Service on port 8002...")
    uvicorn.run(app, host="0.0.0.0", port=8002)