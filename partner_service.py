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
# --- NEW: Gemini Client Setup ---
from gemini_client import get_model, generate_json
import json

PARTNER_SYSTEM_PROMPT = """
You are "Partner," a ReAct-style AI worker agent for the SHIVA system.
Your job is to achieve a "current_step_goal."
You are given a "list of tools" and a "history" of your previous (Thought, Action, Observation) steps.

You operate in two modes based on the "Prompt":

1.  When "Prompt: Reason":
    * Analyze the goal, history (if any), and available tools.
    * Formulate a "thought" (your reasoning).
    * If the goal is already met (e.g., history shows success), your action MUST be "finish_goal" and "action_input" must be {}.
    * Otherwise, select the *one* best "action" (a tool name from the list) and the "action_input" (a dictionary of parameters for that tool).
    * You MUST respond ONLY with a JSON object: 
        {"thought": "...", "action": "...", "action_input": {...}}

2.  When "Prompt: Observe":
    * You will be given the "action_result" (e.g., "success", "deviation", or tool output).
    * Summarize this result into a brief, natural language "observation".
    * You MUST respond ONLY with a JSON object: 
        {"observation": "..."}
"""
partner_model = get_model(system_instruction=PARTNER_SYSTEM_PROMPT)
# --- End Gemini Client Setup ---

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
# --- Mock Agent Function (UPDATED for ReAct Loop) ---
def use_agent(prompt: str, goal: str, tools: List[dict], history: List[dict]) -> dict:
    """(UPDATED) AI reasoning and observation using Gemini."""
    print(f"[Partner] AI Agent called with prompt: {prompt}")

    # Note: The original code re-uses the 'goal' variable to pass the 'action_result'
    # when the prompt is "Observe". We will handle this.
    
    if prompt == "Reason":
        prompt_parts = [
            f"Prompt: {prompt}\n",
            f"Current Step Goal: {goal}\n",
            f"Available Tools: {json.dumps(tools)}\n",
            # Send only the last 3 history steps to save tokens and stay relevant
            f"Recent History: {json.dumps(history[-3:])}\n\n",
            "Generate your JSON response (thought, action, action_input)."
        ]
        
        response = generate_json(partner_model, prompt_parts)
        
        if "error" in response or "thought" not in response or "action" not in response:
            print(f"[Partner] AI reasoning failed: {response.get('error', 'Invalid format')}")
            # Fallback to stop the loop
            return {"thought": "AI error, cannot proceed.", "action": "finish_goal", "action_input": {}}
        
        return response

    if prompt == "Observe":
        action_result = goal # 'goal' param is used to pass the result
        prompt_parts = [
            f"Prompt: {prompt}\n",
            f"Action Result: {json.dumps(action_result)}\n\n",
            "Generate your JSON observation (observation)."
        ]
        response = generate_json(partner_model, prompt_parts)

        if "error" in response or "observation" not in response:
            print(f"[Partner] AI observation failed: {response.get('error', 'Invalid format')}")
            return {"observation": f"AI failed to generate observation for: {action_result}"}
        
        return response
    
    return {"output": "Mock AI response"} # Fallback for unknown prompt
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
                
                # API Contract: Guardian returns 403 Forbidden for Deny decisions
                if g_resp.status_code == 403:
                    decision_data = g_resp.json()
                    reason = decision_data.get("reason", "Unknown reason")
                    await log_to_overseer(client, task_id, "ERROR", f"Action validation FAILED: {reason}", decision_data)
                    return {"task_id": task_id, "status": "ACTION_REJECTED", "reason": f"Guardian denied action: {reason}"}
                
                # For 200 OK, check the decision
                g_resp.raise_for_status()
                decision_data = g_resp.json()
                if decision_data.get("decision") != "Allow":
                    reason = decision_data.get("reason", "Unknown reason")
                    await log_to_overseer(client, task_id, "ERROR", f"Action validation FAILED: {reason}", decision_data)
                    return {"task_id": task_id, "status": "ACTION_REJECTED", "reason": f"Guardian denied action: {reason}"}
                
                await log_to_overseer(client, task_id, "INFO", f"Action validation PASSED: {action}")
            
            except httpx.HTTPStatusError as e:
                # Handle other HTTP errors
                await log_to_overseer(client, task_id, "ERROR", f"Guardian returned HTTP {e.response.status_code}: {e.response.text[:200]}")
                return {"task_id": task_id, "status": "FAILED", "reason": f"Guardian HTTP error: {e.response.status_code}"}
            except Exception as e:
                await log_to_overseer(client, task_id, "ERROR", f"Failed to validate action with Guardian: {e}")
                return {"task_id": task_id, "status": "FAILED", "reason": "Failed to contact Guardian"}

            # 3. Act (Simulated) --- !!! THIS SECTION IS UPDATED !!! ---
            await log_to_overseer(client, task_id, "INFO", f"Taking action: {action} with input {action_input}")
            
            # Instead of just a string, create descriptive results
            simulated_results = [
                {"status": "success", "output": "Script executed, exit code 0."},
                {"status": "deviation", "error": f"Tool {action} failed: Connection timed out to host."},
                {"status": "success", "output": "Data fetched, 100 rows received."},
                {"status": "deviation", "error": f"Tool {action} failed: File not found '/tmp/data.csv'"}
            ]
            # Choose a random result
            random_result = random.choice(simulated_results)
            action_status = random_result["status"] # This is "success" or "deviation"
            
            # This is the 'action_result' payload that gets passed to the observation model
            # It's now a useful dictionary, not just a string.
            action_result_payload = random_result 
            # --- END UPDATED SIMULATION ---

            # 4. Observe
            # Pass the rich dictionary (not just a string) to the observation model
            observation = use_agent("Observe", action_result_payload, tools, history)
            observation_text = observation.get('observation', 'No observation.')
            await log_to_overseer(client, task_id, "INFO", f"Observation: {observation_text}", observation)
            
            # 5. Log to Memory
            history.append({"thought": thought, "action": action, "observation": observation_text})
            await log_memory_to_hub(client, task_id, thought, action, observation_text)
            
            # 6. Handle Deviation
            # Check the status from our new simulation
            if action_status == "deviation":
                await log_to_overseer(client, task_id, "WARN", "Deviation detected. Pausing task.")
                return {
                    "task_id": task_id, 
                    "status": "DEVIATION_DETECTED", 
                    "reason": "Unexpected deviation during tool execution",
                    # 'observation' is the AI summary of the *detailed* error
                    "details": observation 
                }

            # 7. If the simulated action succeeded, consider the step completed
            if action_status == "success":
                await log_to_overseer(client, task_id, "INFO", "Step completed successfully after action.", action_result_payload)
                return {
                    "task_id": task_id,
                    "status": "STEP_COMPLETED",
                    "output": {"observation": observation_text}
                }

        # If loop finishes without completion
        await log_to_overseer(client, task_id, "ERROR", "Task failed: Max loops exceeded.")
        return {"task_id": task_id, "status": "FAILED", "reason": "Max loops exceeded"}
# --- End ReAct Loop ---

if __name__ == "__main__":
    print("Starting Partner Service on port 8002...")
    uvicorn.run(app, host="0.0.0.0", port=8002)