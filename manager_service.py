# 📄 manager_service.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import httpx
import threading
import time
import uuid
from security import get_api_key

# --- NEW: Gemini Client Setup ---
from gemini_client import get_model, generate_json
import json

MANAGER_SYSTEM_PROMPT = """
You are the "Manager," an AI team lead for the SHIVA agent system.
Your job is to take a high-level "goal" from a user and break it down into a 
clear, logical, step-by-step plan.

You must respond ONLY with a JSON object with two keys:
1. "plan_id": A unique string, (e.g., "plan-" + a few random chars).
2. "steps": A list of objects. Each object must have:
    - "step_id": An integer (1, 2, 3...).
    - "goal": A string describing the specific, actionable goal for that step.

The plan should be detailed and actionable for a worker agent.
"""
manager_model = get_model(system_instruction=MANAGER_SYSTEM_PROMPT)
# --- End Gemini Client Setup ---

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Manager Service",
    description="Orchestrator for SHIVA.",
    dependencies=[Depends(get_api_key)]
)
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "manager-service"
SERVICE_PORT = 8001
# --- End Authentication & Service Constants ---

# --- In-memory Task Database ---
tasks_db = {}
# ---

class InvokeRequest(BaseModel):
    goal: str
    context: dict = {}

# --- Mock Agent Function (No change) ---
def use_agent(prompt: str, input_data: dict) -> dict:
    """(UPDATED) AI-based planning using Gemini."""
    print(f"[Manager] AI Agent called with prompt: {prompt}")

    prompt_parts = [
        f"User Prompt: {prompt}\n",
        f"User Input: {json.dumps(input_data)}\n\n",
        "Generate the JSON plan (plan_id, steps) for this goal."
    ]
    
    plan = generate_json(manager_model, prompt_parts)

    # Fallback in case of JSON error or unexpected output
    if "error" in plan or "steps" not in plan or "plan_id" not in plan:
        print(f"[Manager] AI planning failed: {plan.get('error', 'Invalid format')}")
        # Return a safe, empty plan
        return {
            "plan_id": f"plan-fallback-{uuid.uuid4().hex[:4]}",
            "steps": [{"step_id": 1, "goal": f"Error: AI failed to generate plan for {input_data.get('goal')}"}]
        }
    
    return plan     

# --- Service Discovery & Logging (No change) ---
async def discover(client: httpx.AsyncClient, service_name: str) -> str:
    print(f"[Manager] Discovering: {service_name}")
    try:
        r = await client.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        r.raise_for_status()
        url = r.json()["url"]
        print(f"[Manager] Discovered {service_name} at {url}")
        return url
    except httpx.RequestError as e:
        print(f"[Manager] FAILED to connect to Directory at {DIRECTORY_URL}: {e}")
        raise HTTPException(500, detail=f"Could not connect to Directory Service: {e}")
    except httpx.HTTPStatusError as e:
        print(f"[Manager] FAILED to discover {service_name}. Directory response: {e.response.text}")
        raise HTTPException(500, detail=f"Could not discover {service_name}: {e.response.text}")

async def log_to_overseer(client: httpx.AsyncClient, task_id: str, level: str, message: str, context: dict = {}):
    try:
        overseer_url = await discover(client, "overseer-service")
        await client.post(f"{overseer_url}/log/event", json={
            "service": "manager-service",
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[Manager] FAILED to log to Overseer: {e}")

# --- Service Registration (No change) ---
def register_self():
    while True:
        try:
            r = httpx.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            
            if r.status_code == 200:
                print(f"[Manager] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Manager] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except httpx.RequestError:
            print(f"[Manager] Could not connect to Directory. Retrying in 5s...")
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            httpx.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            print("[Manager] Heartbeat sent to Directory.")
        except httpx.RequestError:
            print("[Manager] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

# --- Multi-Step Execution Logic (!!! UPDATED !!!) ---
async def execute_plan_from_step(task_id: str, step_index: int):
    task = tasks_db.get(task_id)
    if not task:
        print(f"[Manager] Task {task_id} not found for execution.")
        return

    plan = task.get("plan")
    if not plan or not plan.get("steps"):
        print(f"[Manager] No plan for task {task_id}.")
        return

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            for i in range(step_index, len(plan["steps"])):
                task["current_step_index"] = i
                step = plan["steps"][i]
                
                task["status"] = f"EXECUTING_STEP_{i+1}: {step['goal']}"
                await log_to_overseer(client, task_id, "INFO", f"Executing step {i+1}: {step['goal']}")

                partner_url = await discover(client, "partner-service")
                p_resp = await client.post(f"{partner_url}/partner/execute_goal", json={
                    "task_id": task_id,
                    "current_step_goal": step["goal"],
                    "approved_plan": plan,
                    "context": task.get("context", {})
                }, headers=AUTH_HEADER)
                
                partner_result = p_resp.json()
                await log_to_overseer(client, task_id, "INFO", f"Partner result: {partner_result.get('status')}", partner_result)

                partner_status = partner_result.get("status")

                if partner_status == "STEP_COMPLETED":
                    continue
                
                elif partner_status == "DEVIATION_DETECTED":
                    await log_to_overseer(client, task_id, "WARN", "Deviation detected. Pausing task for manual review.")
                    task["status"] = "PAUSED_DEVIATION"
                    task["reason"] = partner_result.get("reason")
                    # Save the detailed observation from the partner for the UI
                    task["deviation_details"] = partner_result.get("details", {"observation": "No details provided."}) 
                    return
                
                elif partner_status == "ACTION_REJECTED":
                    await log_to_overseer(client, task_id, "ERROR", "Task REJECTED: Guardian denied a critical step.")
                    task["status"] = "REJECTED"
                    task["reason"] = partner_result.get("reason")
                    # Save context for the UI
                    task["deviation_details"] = {"observation": f"Guardian rejection: {task['reason']}"}
                    return
                
                else:
                    await log_to_overseer(client, task_id, "ERROR", "Task FAILED during partner execution.")
                    task["status"] = "FAILED"
                    task["reason"] = partner_result.get("reason", "Unknown partner failure")
                    # Save context for the UI
                    task["deviation_details"] = {"observation": f"Partner failed: {task['reason']}"}
                    return

            await log_to_overseer(client, task_id, "INFO", "All steps completed. Task finished.")
            task["status"] = "COMPLETED"
            task["result"] = "All plan steps executed successfully."

        except Exception as e:
            print(f"[Manager] Unhandled exception in execute_plan {task_id}: {e}")
            try:
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {str(e)}")
            except: pass
            task["status"] = "FAILED"
            task["reason"] = str(e)
            task["deviation_details"] = {"observation": f"Unhandled exception: {str(e)}"}
# --- END UPDATED SECTION ---


# --- Background Task Entry Point (No change) ---
async def run_task_background(task_id: str, request: InvokeRequest):
    task = tasks_db[task_id]
    task["status"] = "STARTING"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await log_to_overseer(client, task_id, "INFO", f"Task started: {request.goal}")
            
            task["status"] = "CHECKING_HALT"
            overseer_url = await discover(client, "overseer-service")
            status_resp = await client.get(f"{overseer_url}/control/status", headers=AUTH_HEADER)
            
            if status_resp.json().get("status") == "HALT":
                await log_to_overseer(client, task_id, "ERROR", "Task rejected: System is in HALT state.")
                task["status"] = "REJECTED"
                task["reason"] = "System is in HALT state"
                task["deviation_details"] = {"observation": "Task rejected: System is in HALT state"}
                return

            task["status"] = "PLANNING"
            await log_to_overseer(client, task_id, "INFO", "Generating execution plan...")
            plan_input = {"change_id": task_id, "goal": request.goal, "context": request.context}
            plan = use_agent("Create high-level plan for user goal", plan_input)
            task["plan"] = plan
            task["current_step_index"] = 0
            await log_to_overseer(client, task_id, "INFO", f"Plan generated with {len(plan.get('steps', []))} steps.", plan)
            
            task["status"] = "VALIDATING_PLAN"
            await log_to_overseer(client, task_id, "INFO", "Validating plan with Guardian...")
            guardian_url = await discover(client, "guardian-service")
            g_resp = await client.post(f"{guardian_url}/guardian/validate_plan", json={
                "task_id": task_id, "plan": plan
            }, headers=AUTH_HEADER)
            
            if g_resp.status_code != 200 or g_resp.json()["decision"] != "Allow":
                reason = g_resp.json().get("reason", "Unknown reason")
                await log_to_overseer(client, task_id, "ERROR", f"Plan validation FAILED: {reason}", g_resp.json())
                task["status"] = "REJECTED"
                task["reason"] = f"Plan validation failed: {reason}"
                task["deviation_details"] = {"observation": f"Plan validation failed: {reason}"}
                return
            
            await log_to_overseer(client, task_id, "INFO", "Plan validation PASSED.")
            
            if not plan.get("steps"):
                await log_to_overseer(client, task_id, "WARN", "Plan has no steps. Task considered complete.")
                task["status"] = "COMPLETED"
                task["result"] = "No steps to execute."
                return
                
            await execute_plan_from_step(task_id, 0)

        except Exception as e:
            print(f"[Manager] Unhandled exception in background task {task_id}: {e}")
            try:
                await log_to_overseer(client, task_id, "ERROR", f"Unhandled exception: {str(e)}")
            except: pass
            task["status"] = "FAILED"
            task["reason"] = str(e)
            task["deviation_details"] = {"observation": f"Unhandled exception: {str(e)}"}

# --- Public API Endpoints ---

@app.post("/invoke", status_code=202)
async def invoke(request: InvokeRequest, background_tasks: BackgroundTasks):
    task_id = f"task-{uuid.uuid4()}"
    print(f"\n[Manager] === New Task Received ===\nTask ID: {task_id}\nGoal: {request.goal}\n")
    
    tasks_db[task_id] = {
        "status": "PENDING", 
        "goal": request.goal, 
        "context": request.context,
        "current_step_index": 0,
        "task_id": task_id # Add task_id to the object for easy reference
    }
    
    background_tasks.add_task(run_task_background, task_id, request)
    
    return {
        "task_id": task_id, 
        "status": "PENDING", 
        "details": "Task accepted and is running in the background.",
        "status_url": f"/task/{task_id}/status"
    }

@app.get("/task/{task_id}/status", status_code=200)
def get_task_status(task_id: str):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return task

@app.post("/task/{task_id}/approve", status_code=202)
async def approve_task(task_id: str, background_tasks: BackgroundTasks):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
        
    if task["status"] not in ["PAUSED_DEVIATION", "ACTION_REJECTED", "REJECTED", "FAILED"]:
        raise HTTPException(400, detail=f"Task is not in a pausable/resumable state. Current status: {task['status']}")

    step_to_resume = task.get("current_step_index", 0)
    
    print(f"[Manager] Resuming task {task_id} from step {step_to_resume + 1}")
    
    task["status"] = "RESUMING"
    task["reason"] = "Resumed by user approval."
    
    background_tasks.add_task(execute_plan_from_step, task_id, step_to_resume)
    
    return {
        "task_id": task_id, 
        "status": "RESUMING",
        "details": f"Task resuming execution from step {step_to_resume + 1}."
    }

@app.post("/task/{task_id}/replan", status_code=202)
async def replan_task(task_id: str, request: InvokeRequest, background_tasks: BackgroundTasks):
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")

    print(f"[Manager] Replanning task {task_id} with new goal: {request.goal}")

    task["status"] = "REPLANNING"
    task["goal"] = request.goal
    task["context"] = request.context
    task["plan"] = {}
    task["current_step_index"] = 0
    task["reason"] = "Replanning triggered by user."
    
    background_tasks.add_task(run_task_background, task_id, request)

    return {
        "task_id": task_id, 
        "status": "REPLANNING",
        "details": "Task replanning initiated with new goal."
    }

# --- NEW: Endpoint for UI ---
@app.get("/tasks/list", status_code=200)
def get_all_tasks():
    """Get the full list of all task objects in the DB."""
    # Convert dict to a list of its values
    return list(tasks_db.values())
# --- END NEW Endpoint ---


if __name__ == "__main__":
    print("Starting Manager Service on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)