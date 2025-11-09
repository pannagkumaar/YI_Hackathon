# partner_service.py (full file; only one line changed vs your original)
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
from gemini_client import get_model, generate_json
import json

PARTNER_SYSTEM_PROMPT = """
You are "Partner," a ReAct-style AI worker agent for the SHIVA system.
...
"""
partner_model = get_model(system_instruction=PARTNER_SYSTEM_PROMPT)

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

def use_agent(prompt: str, goal: str, tools: List[dict], history: List[dict]) -> dict:
    if prompt == "Reason":
        prompt_parts = [
            f"Prompt: {prompt}\n",
            f"Current Step Goal: {goal}\n",
            f"Available Tools: {json.dumps(tools)}\n",
            f"Recent History: {json.dumps(history[-3:])}\n\n",
            "Generate your JSON response (thought, action, action_input)."
        ]
        response = generate_json(partner_model, prompt_parts)
        if "error" in response or "thought" not in response or "action" not in response:
            return {"thought": "AI error, cannot proceed.", "action": "finish_goal", "action_input": {}}
        return response

    if prompt == "Observe":
        action_result = goal
        prompt_parts = [
            f"Prompt: {prompt}\n",
            f"Action Result: {json.dumps(action_result)}\n\n",
            "Generate your JSON observation (observation)."
        ]
        response = generate_json(partner_model, prompt_parts)
        if "error" in response or "observation" not in response:
            return {"observation": f"AI failed to generate observation for: {action_result}"}
        return response
    return {"output": "Mock AI response"}

async def discover_async(client: httpx.AsyncClient, service_name: str) -> str:
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        r.raise_for_status()
        return r.json()["url"]
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise HTTPException(500, detail=f"Could not discover {service_name}")

async def log_to_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context: dict = {}):
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

async def get_tools_from_hub(client: httpx.AsyncClient, task_id: str) -> List[dict]:
    try:
        hub_url = await discover_async(client, "resource-hub-service")
        resp = await client.get(f"{hub_url}/tools/list", headers=AUTH_HEADER)
        resp.raise_for_status()
        await log_to_overseer(client, task_id, "INFO", "Successfully fetched tools from Resource Hub.")
        return resp.json().get("tools", [])
    except Exception as e:
        await log_to_overseer(client, task_id, "ERROR", f"Failed to fetch tools from Resource Hub: {e}")
        return []

async def log_memory_to_hub(client: httpx.AsyncClient, task_id: str, thought: str, action: str, observation: str):
    try:
        hub_url = await discover_async(client, "resource-hub-service")
        await client.post(f"{hub_url}/memory/{task_id}", json={
            "thought": thought,
            "action": action,
            "observation": observation
        }, headers=AUTH_HEADER)
    except Exception as e:
        await log_to_overseer(client, task_id, "WARN", f"Failed to log memory to Resource Hub: {e}")

def register_self():
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            if r.status_code == 200:
                threading.Thread(target=heartbeat, daemon=True).start()
                break
        except requests.exceptions.ConnectionError:
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
        except requests.exceptions.ConnectionError:
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

class ExecuteGoal(BaseModel):
    task_id: str
    current_step_goal: str
    approved_plan: dict
    context: dict

@app.post("/partner/execute_goal", status_code=200)
async def execute_goal(data: ExecuteGoal):
    task_id = data.task_id
    goal = data.current_step_goal
    history = []
    max_loops = 5

    async with httpx.AsyncClient(timeout=30.0) as client:
        await log_to_overseer(client, task_id, "INFO", f"Starting ReAct loop for goal: {goal}")
        tools = await get_tools_from_hub(client, task_id)
        if not tools:
            await log_to_overseer(client, task_id, "ERROR", "No tools found. Cannot execute goal.")
            return {"task_id": task_id, "status": "FAILED", "reason": "No tools available from Resource Hub"}

        for i in range(max_loops):
            reasoning = use_agent("Reason", goal, tools, history)
            thought = reasoning.get("thought")
            action = reasoning.get("action")
            action_input = reasoning.get("action_input")

            await log_to_overseer(client, task_id, "INFO", f"[Loop {i+1}] Thought: {thought}", reasoning)

            if action == "finish_goal":
                await log_memory_to_hub(client, task_id, thought, "finish_goal", "Goal completed successfully.")
                await log_to_overseer(client, task_id, "INFO", f"Goal completed: {goal}")
                return {
                    "task_id": task_id,
                    "status": "STEP_COMPLETED",
                    "output": {"observation": "Goal completed successfully."}
                }

            try:
                guardian_url = await discover_async(client, "guardian-service")
                g_resp = await client.post(f"{guardian_url}/guardian/validate_action", json={
                    "task_id": task_id,
                    # robust: send a JSON-encoded action_input so Guardian can parse reliably
                    "proposed_action": f"{action}:{json.dumps(action_input)}",
                    "context": data.context
                }, headers=AUTH_HEADER)

                if g_resp.status_code == 403:
                    decision_data = g_resp.json()
                    reason = decision_data.get("reason", "Unknown reason")
                    await log_to_overseer(client, task_id, "ERROR", f"Action validation FAILED: {reason}", decision_data)
                    return {"task_id": task_id, "status": "ACTION_REJECTED", "reason": f"Guardian denied action: {reason}"}

                g_resp.raise_for_status()
                decision_data = g_resp.json()
                if decision_data.get("decision") != "Allow":
                    reason = decision_data.get("reason", "Unknown reason")
                    await log_to_overseer(client, task_id, "ERROR", f"Action validation FAILED: {reason}", decision_data)
                    return {"task_id": task_id, "status": "ACTION_REJECTED", "reason": f"Guardian denied action: {reason}"}

                await log_to_overseer(client, task_id, "INFO", f"Action validation PASSED: {action}")

            except httpx.HTTPStatusError as e:
                await log_to_overseer(client, task_id, "ERROR", f"Guardian returned HTTP {e.response.status_code}: {e.response.text[:200]}")
                return {"task_id": task_id, "status": "FAILED", "reason": f"Guardian HTTP error: {e.response.status_code}"}
            except Exception as e:
                await log_to_overseer(client, task_id, "ERROR", f"Failed to validate action with Guardian: {e}")
                return {"task_id": task_id, "status": "FAILED", "reason": "Failed to contact Guardian"}

            await log_to_overseer(client, task_id, "INFO", f"Taking action: {action} with input {action_input}")

            simulated_results = [
                {"status": "success", "output": "Script executed, exit code 0."},
                {"status": "deviation", "error": f"Tool {action} failed: Connection timed out to host."},
                {"status": "success", "output": "Data fetched, 100 rows received."},
                {"status": "deviation", "error": f"Tool {action} failed: File not found '/tmp/data.csv'"}
            ]
            random_result = random.choice(simulated_results)
            action_status = random_result["status"]
            action_result_payload = random_result

            observation = use_agent("Observe", action_result_payload, tools, history)
            observation_text = observation.get('observation', 'No observation.')
            await log_to_overseer(client, task_id, "INFO", f"Observation: {observation_text}", observation)

            history.append({"thought": thought, "action": action, "observation": observation_text})
            await log_memory_to_hub(client, task_id, thought, action, observation_text)

            if action_status == "deviation":
                await log_to_overseer(client, task_id, "WARN", "Deviation detected. Pausing task.")
                return {
                    "task_id": task_id,
                    "status": "DEVIATION_DETECTED",
                    "reason": "Unexpected deviation during tool execution",
                    "details": observation
                }

            if action_status == "success":
                await log_to_overseer(client, task_id, "INFO", "Step completed successfully after action.", action_result_payload)
                return {
                    "task_id": task_id,
                    "status": "STEP_COMPLETED",
                    "output": {"observation": observation_text}
                }

        await log_to_overseer(client, task_id, "ERROR", "Task failed: Max loops exceeded.")
        return {"task_id": task_id, "status": "FAILED", "reason": "Max loops exceeded"}
