"""
Guardian Service — SHIVA Compliance & Safety Layer
Evaluates actions and plans against safety policies and runbooks.
"""

import os
import json
import time
import threading
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# === Local Imports ===
from guardian_prompt_safety import analyze_payload
from guardian_rules import deterministic_eval_action, deterministic_eval_plan
from guardian_schemas import ACTION_DECISION_SCHEMA, PLAN_VALIDATION_SCHEMA

# === Config ===
API_KEY = os.getenv("SHIVA_SECRET", os.getenv("SHARED_SECRET", "mysecretapikey"))
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005").rstrip("/")
SERVICE_NAME = os.getenv("SERVICE_NAME", "guardian")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8003))
SERVICE_URL = os.getenv("SELF_URL", f"http://localhost:{SERVICE_PORT}")

AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

# === Globals ===
_policy_cache = {}
_POLICY_TTL = 30
human_overrides = {}

app = FastAPI(title="Guardian Service", description="SHIVA Policy Layer")

# -------------------- Discovery --------------------

def discover(service_name: str) -> str:
    """Directory discovery with variant matching."""
    variants = [
        service_name,
        f"{service_name}-service",
        service_name.replace("_", "-"),
        service_name.replace("-", "_"),
    ]

    for name in dict.fromkeys(variants):
        try:
            r = requests.get(
                f"{DIRECTORY_URL}/discover",
                params={"service_name": name},
                headers=AUTH_HEADER,
                timeout=3,
            )
            if r.status_code == 200 and "url" in r.json():
                return r.json()["url"].rstrip("/")
        except Exception:
            continue

    raise HTTPException(500, f"Could not discover {service_name}")

# -------------------- Logging --------------------

def log_to_overseer(task_id: str, level: str, message: str, context: dict = None):
    """Send structured logs to Overseer."""
    context = context or {}
    try:
        overseer_url = discover("overseer")
        requests.post(
            f"{overseer_url}/log/event",
            json={
                "service": SERVICE_NAME,
                "task_id": task_id,
                "level": level,
                "message": message,
                "context": context,
            },
            headers=AUTH_HEADER,
            timeout=4,
        )
    except Exception as e:
        print(f"[Guardian] Overseer log failed: {e}")

# -------------------- Policy Cache --------------------

def fetch_policies_from_hub(context: str = "global") -> list:
    now = time.time()

    # return cached version if valid
    cached = _policy_cache.get(context)
    if cached and cached["expires_at"] > now:
        return cached["policies"]

    # fetch updated policies
    try:
        hub_url = discover("resource_hub")
        
        # FIX: resource hub uses /policies, not /policy/list
        r = requests.get(
            f"{hub_url}/policies",
            headers=AUTH_HEADER,
            timeout=5
        )
        if r.status_code == 200:
            policies = r.json().get("policies", [])
            _policy_cache[context] = {
                "policies": policies,
                "expires_at": now + _POLICY_TTL
            }
            return policies
        else:
            log_to_overseer("N/A", "WARN", f"Policy fetch failed: {r.status_code}", {"text": r.text})
    except Exception as e:
        log_to_overseer("N/A", "ERROR", f"Policy fetch exception: {e}")

    return []

# -------------------- Registration --------------------

def register_self():
    """Register with Directory."""
    while True:
        try:
            r = requests.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": SERVICE_URL,
                    "ttl_seconds": 60,
                },
                headers=AUTH_HEADER,
                timeout=5,
            )
            if r.status_code == 200:
                print(f"[Guardian] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Guardian] Registration failed: {r.status_code}")
        except Exception:
            print(f"[Guardian] Directory unavailable, retrying...")
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            requests.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": SERVICE_URL,
                    "ttl_seconds": 60,
                },
                headers=AUTH_HEADER,
                timeout=5,
            )
        except Exception:
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

# -------------------- Models --------------------

class ValidateAction(BaseModel):
    task_id: str
    proposed_action: str
    context: dict = {}

class ValidatePlan(BaseModel):
    task_id: str
    plan: dict

# -------------------- Routes --------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

@app.post("/guardian/validate_action")
def validate_action(payload: ValidateAction):
    task_id = payload.task_id
    action = payload.proposed_action

    policies = fetch_policies_from_hub("global")

    try:
        analysis = analyze_payload(
            {
                "task_id": task_id,
                "proposed_action": action,
                "context": payload.context,
            },
            policies=policies,
        )
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Analyzer error: {e}")
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": str(e)})

    decision = analysis.get("decision", "Deny")
    reason = analysis.get("one_liner", "No reason")

    log_to_overseer(task_id, "INFO", f"Guardian decision: {decision}", analysis)

    if decision == "Deny":
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": reason})
    elif decision == "Ambiguous":
        return {"decision": "Ambiguous", "reason": reason, "details": analysis}
    else:
        return {"decision": "Allow", "reason": reason, "details": analysis}

@app.post("/guardian/validate_plan")
def validate_plan(payload: ValidatePlan):
    task_id = payload.task_id
    plan = payload.plan

    if not isinstance(plan, dict) or "steps" not in plan:
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": "Malformed plan"})

    try:
        result = deterministic_eval_plan(plan, fetch_policies_from_hub("global"))
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Plan evaluation error: {e}")
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": str(e)})

    log_to_overseer(task_id, "INFO", f"Plan decision: {result['decision']}", result)
    return result

# -------------------- Entrypoint --------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
