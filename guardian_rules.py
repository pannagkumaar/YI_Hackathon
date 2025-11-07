# guardian_rules.py
"""
Deterministic + lightweight-semantic Guardian rule engine.

Provides deterministic evaluation helpers that the guardian service uses before
falling back to the LLM. The functions return dictionaries with the fields:
    {
      "decision": "Allow" | "Deny" | "Ambiguous",
      "reason": str,
      "evidence": str,
      "policy_score": float,
      "requires_human_review": bool (optional)
    }
"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Configuration (tuneable)
# ---------------------------------------------------------------------------

ALLOWED_TOOLS = {"run_script", "fetch_data", "restart_service"}

# Per-tool parameter restrictions (example)
PER_TOOL_RULES = {
    "run_script": {
        "path_prefix": "/srv/",  # required prefix for any path param
    },
    "fetch_data": {
        "allowed_hosts": ["api.mycompany.com", "localhost"],
    },
}

# Hard deterministic deny regexes (high severity)
HARD_DENY_REGEX = [
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\bformat\s+disk\b", re.I),
    re.compile(r"\b:/dev/sda\b", re.I),
]

# Prompt-injection indicative patterns (deny or require review)
INJECTION_PATTERNS = [
    r"ignore (previous|earlier) instructions",
    r"forget (previous|earlier) instructions",
    r"role\s*:\s*system",
    r"you are now",
    r"do anything now",
    r"`{3}\s*system",
    r"<script",
]
INJECTION_RX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

# Synonym map for light canonicalization (small & deterministic)
SYNONYMS = {
    "wipe": "delete",
    "purge": "delete",
    "bring down": "shutdown",
    "bring-up": "start",
    "reboot": "restart",
    "remove": "delete",
    "erase": "delete",
    "drop": "delete",
}

# Semantic thresholds (deterministic constants)
SEMANTIC_DENY_THRESHOLD = 0.90  # >= -> automatic deny (very similar to disallow phrase)
SEMANTIC_REVIEW_THRESHOLD = 0.70  # review band

# ---------------------------------------------------------------------------
# Optional: jsonschema usage (kept optional)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - optional dependency
    from jsonschema import ValidationError as JSValidationError
    from jsonschema import validate as js_validate

    JSONSCHEMA_AVAILABLE = True
except Exception:  # pragma: no cover - if jsonschema not installed
    JSONSCHEMA_AVAILABLE = False

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "action_input": {"type": "object"},
    },
    "required": ["action", "action_input"],
    "additionalProperties": True,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_id": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "integer"},
                    "goal": {"type": "string"},
                },
                "required": ["step_id", "goal"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": True,
}


def _try_jsonschema(obj: dict, schema: dict) -> Tuple[bool, str]:
    """Validate using jsonschema if available. Fail-closed on validation error."""

    if not JSONSCHEMA_AVAILABLE:
        return True, ""
    try:
        js_validate(obj, schema)
        return True, ""
    except JSValidationError as exc:  # pragma: no cover - only when jsonschema present
        return False, f"JSON schema validation failed: {exc.message}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def canonicalize_text(text: str) -> str:
    """Lowercase, replace synonyms, collapse whitespace deterministically."""

    if not text:
        return ""
    t = text.lower()
    for src, dst in SYNONYMS.items():
        t = t.replace(src, dst)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_interrogative(text: str) -> bool:
    """Return True if the text looks like a question (interrogative phrasing)."""

    if not text:
        return False
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    starters = (
        "should ",
        "can ",
        "may ",
        "would ",
        "could ",
        "is ",
        "are ",
        "do ",
        "does ",
        "did ",
        "will ",
        "shall ",
        "might ",
        "must ",
    )
    return any(t.startswith(s) for s in starters)


def detect_injection(text: str) -> Tuple[bool, List[str]]:
    """Return True + hits list if injection-like phrases exist."""

    if not text:
        return False, []
    hits: List[str] = []
    match = INJECTION_RX.search(text)
    if match:
        hits.append(match.group(0))
    lower_text = text.lower()
    if "<script" in lower_text or "```system" in lower_text:
        hits.append("code_fence_or_html")
    return (len(hits) > 0), hits


def hard_deny_match(text: str) -> Tuple[bool, List[str]]:
    """High-confidence destructive patterns."""

    if not text:
        return False, []
    hits: List[str] = []
    for rx in HARD_DENY_REGEX:
        if rx.search(text):
            hits.append(rx.pattern)
    return (len(hits) > 0), hits


def normalize_policies(policies: List[str]) -> Dict[str, List[str]]:
    """Convert simple 'Disallow: token' lines into buckets."""

    buckets = {"disallow": []}
    for policy in policies or []:
        parts = policy.split(":", 1)
        if len(parts) == 2:
            key = parts[0].strip().lower()
            val = parts[1].strip()
            if key == "disallow" and val:
                buckets["disallow"].append(val.lower())
    return buckets


def policy_disallow_substring(text: str, policy_buckets: Dict[str, List[str]]) -> Tuple[bool, List[str]]:
    """Simple deterministic substring match against policy list."""

    if not text:
        return False, []
    hits: List[str] = []
    lowered = text.lower()
    for needle in policy_buckets.get("disallow", []):
        if needle in lowered:
            hits.append(needle)
    return (len(hits) > 0), hits


def token_overlap_score(a: str, b: str) -> float:
    """Deterministic similarity score between two strings using token overlap."""

    if not a or not b:
        return 0.0

    def _tokens(s: str) -> List[str]:
        s2 = re.sub(r"[^\w\s]", " ", canonicalize_text(s))
        return [tok for tok in s2.split() if tok]

    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    intersection = ta.intersection(tb)
    union = ta.union(tb)
    return len(intersection) / len(union)


def semantic_policy_score(text: str, policy_buckets: Dict[str, List[str]]) -> float:
    """Return the max token-overlap score between text and any disallow policy phrase."""

    max_score = 0.0
    for policy_str in policy_buckets.get("disallow", []):
        score = token_overlap_score(text, policy_str)
        if score > max_score:
            max_score = score
    return max_score


# ---------------------------------------------------------------------------
# Parsing proposed actions
# ---------------------------------------------------------------------------

def parse_proposed_action(proposed_action: str) -> Tuple[bool, Dict[str, Any], str]:
    """Parse proposed_action string into structured {action, action_input}."""

    if not isinstance(proposed_action, str) or not proposed_action.strip():
        return False, {}, "proposed_action must be a non-empty string"

    snippet = proposed_action.strip()

    # Attempt literal dict parsing first
    try:
        if snippet.startswith("{"):
            obj = ast.literal_eval(snippet)
            if not isinstance(obj, dict):
                return False, {}, "Parsed proposed_action is not an object"
            if "action" in obj and "action_input" in obj:
                return True, {"action": obj["action"], "action_input": obj["action_input"]}, ""
            if "tool" in obj and "action_input" in obj:
                return True, {"action": obj["tool"], "action_input": obj["action_input"]}, ""
            return False, {}, "Object must contain 'action' and 'action_input'"
    except Exception as exc:
        return False, {}, f"Failed to parse object: {exc}"

    # Fallback: "tool: { ... }"
    parts = snippet.split(":", 1)
    if len(parts) != 2:
        return False, {}, "Expected format 'tool: {...}' or a JSON-like object"
    tool_name = parts[0].strip()
    remainder = parts[1].strip()
    try:
        payload = ast.literal_eval(remainder)
        if not isinstance(payload, dict):
            return False, {}, "action_input must be an object"
    except Exception as exc:
        return False, {}, f"Failed to parse action_input: {exc}"

    return True, {"action": tool_name, "action_input": payload}, ""


# ---------------------------------------------------------------------------
# Deterministic evaluators
# ---------------------------------------------------------------------------

def deterministic_eval_action(
    proposed_action: str,
    context: Dict[str, Any],
    policies: List[str],
) -> Dict[str, Any]:
    """Deterministically evaluate a proposed action before LLM fallback."""

    # 1. Malformed -> Deny
    ok, parsed_action, err = parse_proposed_action(proposed_action)
    if not ok:
        return {
            "decision": "Deny",
            "reason": f"Malformed action: {err}",
            "evidence": proposed_action,
            "policy_score": 0.0,
        }

    # 2. Hard deny patterns -> Deny
    hd, hd_hits = hard_deny_match(proposed_action)
    if hd:
        return {
            "decision": "Deny",
            "reason": f"Hard deny pattern: {hd_hits}",
            "evidence": hd_hits,
            "policy_score": 1.0,
        }

    # 3. Injection patterns -> Deny
    inj, inj_hits = detect_injection(proposed_action)
    if inj:
        return {
            "decision": "Deny",
            "reason": f"Prompt-injection detected: {inj_hits}",
            "evidence": inj_hits,
            "policy_score": 1.0,
        }

    # 4. Tool allowlist -> if unknown tool -> Ambiguous (ask LLM)
    action_name = parsed_action["action"]
    if action_name not in ALLOWED_TOOLS:
        return {
            "decision": "Ambiguous",
            "reason": f"Unsupported tool '{action_name}', require LLM/human review",
            "evidence": action_name,
            "policy_score": 0.0,
        }

    # 5. Policy substring match -> Deny
    for policy in policies or []:
        if policy.lower().startswith("disallow:"):
            token = policy.split(":", 1)[1].strip().lower()
            if token and token in proposed_action.lower():
                return {
                    "decision": "Deny",
                    "reason": f"Policy matched: {token}",
                    "evidence": token,
                    "policy_score": 1.0,
                }

    # 6. Parameter checks -> if suspicious -> Ambiguous (LLM review), else Allow
    if action_name == "run_script":
        path = str(parsed_action["action_input"].get("path", ""))
        if not path.startswith(PER_TOOL_RULES["run_script"]["path_prefix"]):
            return {
                "decision": "Ambiguous",
                "reason": "run_script path outside safe prefix",
                "evidence": path,
                "policy_score": 0.4,
            }

    if action_name == "fetch_data":
        url = str(parsed_action["action_input"].get("url", ""))
        allowed = PER_TOOL_RULES["fetch_data"]["allowed_hosts"]
        if not any(host in url for host in allowed):
            return {
                "decision": "Ambiguous",
                "reason": "fetch_data target not in allowed hosts",
                "evidence": url,
                "policy_score": 0.4,
            }

    # no issues -> Allow
    return {
        "decision": "Allow",
        "reason": "Passes deterministic checks",
        "evidence": "",
        "policy_score": 0.0,
    }


def deterministic_eval_plan(plan: Dict[str, Any], policies: List[str]) -> Dict[str, Any]:
    """Deterministically evaluate a high-level execution plan."""

    if not isinstance(plan, dict) or "steps" not in plan:
        return {
            "decision": "Deny",
            "reason": "Malformed plan",
            "evidence": str(plan),
            "policy_score": 1.0,
        }

    ok, err = _try_jsonschema(plan, PLAN_SCHEMA)
    if not ok:
        return {
            "decision": "Deny",
            "reason": err,
            "evidence": str(plan),
            "policy_score": 1.0,
        }

    steps = plan.get("steps", [])
    if len(steps) > 10:
        return {
            "decision": "Deny",
            "reason": "Plan too complex (>10 steps)",
            "evidence": str(len(steps)),
            "policy_score": 1.0,
        }

    policy_buckets = normalize_policies(policies)

    for step in steps:
        goal = step.get("goal", "")
        sid = step.get("step_id", "?")

        hd, hd_hits = hard_deny_match(goal)
        if hd:
            # Planning text with restricted terms should trigger human review
            return {
                "decision": "Ambiguous",
                "reason": f"Restricted term present in plan step {sid}",
                "evidence": str(hd_hits),
                "policy_score": 0.9,
            }

        inj, inj_hits = detect_injection(goal)
        if inj:
            return {
                "decision": "Ambiguous",
                "reason": f"Injection-like text detected in plan step {sid}",
                "evidence": str(inj_hits),
                "policy_score": 0.9,
            }

        policy_hit, policy_terms = policy_disallow_substring(goal, policy_buckets)
        if policy_hit:
            return {
                "decision": "Ambiguous",
                "reason": f"Policy term {policy_terms} found in plan step {sid}",
                "evidence": goal,
                "policy_score": 0.9,
            }

        # Lightweight semantic similarity for policy terms
        sem_score = semantic_policy_score(goal, policy_buckets)
        if sem_score >= SEMANTIC_DENY_THRESHOLD:
            return {
                "decision": "Ambiguous",
                "reason": f"Plan step {sid} semantically similar to restricted policy",
                "evidence": goal,
                "policy_score": sem_score,
            }

    return {
        "decision": "Allow",
        "reason": "Plan passes deterministic checks",
        "evidence": "",
        "policy_score": 0.0,
    }

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
            
            # Handle plan decision outcomes
            if g_resp.status_code != 200:
                await log_to_overseer(client, task_id, "ERROR", f"Plan validation FAILED: HTTP {g_resp.status_code}")
                task["status"] = "REJECTED"
                task["reason"] = f"Plan validation failed: HTTP {g_resp.status_code}"
                task["deviation_details"] = {"observation": task["reason"]}
                return

            decision_payload = g_resp.json()
            decision = decision_payload.get("decision")
            reason = decision_payload.get("reason", "Unknown reason")

            if decision == "Allow":
                pass
            elif decision == "Ambiguous":
                await log_to_overseer(client, task_id, "WARN", f"Plan requires human review: {reason}", decision_payload)
                task["status"] = "PAUSED_REVIEW"
                task["reason"] = f"Plan requires human review: {reason}"
                task["deviation_details"] = {"observation": task["reason"]}
                return
            else:
                await log_to_overseer(client, task_id, "ERROR", f"Plan validation FAILED: {reason}", decision_payload)
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



def action_matches_plan_score(action_text: str, plan: dict) -> Tuple[float, int]:
    """
    Return (best_score, best_step_id) matching action_text to any plan goal.
    Score uses token_overlap_score (0.0-1.0). If no plan or steps, returns (0.0, -1).
    """
    if not isinstance(plan, dict):
        return 0.0, -1
    steps = plan.get("steps", []) or []
    best_score = 0.0
    best_step_id = -1
    for s in steps:
        goal = s.get("goal", "")
        sid = s.get("step_id", -1)
        score = token_overlap_score(action_text, goal)
        if score > best_score:
            best_score = score
            best_step_id = sid
    return best_score, best_step_id



if __name__ == "__main__":
    print("Starting Manager Service on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)