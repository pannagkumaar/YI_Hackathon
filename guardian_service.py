"""
Guardian Service — SHIVA Compliance & Safety Layer
--------------------------------------------------
Evaluates actions and plans against safety policies and runbooks,
using deterministic + LLM-based reasoning, with audit logs to Overseer.
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
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://directory:8005").rstrip("/")
SERVICE_NAME = os.getenv("SERVICE_NAME", "guardian")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8003))
SERVICE_URL = os.getenv("SELF_URL", f"http://{SERVICE_NAME}:{SERVICE_PORT}")
IN_DOCKER = os.getenv("IN_DOCKER", "false").lower() == "true"

AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

# === Globals ===
_policy_cache = {}
_POLICY_TTL = 30
human_overrides = {}

app = FastAPI(
    title="Guardian Service",
    description="Compliance & Policy Enforcement Layer for SHIVA"
)

# -------------------- Utility --------------------

def discover(service_name: str) -> str:
    """
    Robust Directory discovery: tries multiple name variants.
    Works both inside and outside Docker.
    """
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
                url = r.json()["url"].rstrip("/")
                if IN_DOCKER and ("localhost" in url or "127.0.0.1" in url):
                    url = url.replace("http://127.0.0.1", f"http://{name}").replace("http://localhost", f"http://{name}")
                print(f"[Guardian] Discovered {name}: {url}")
                return url
        except Exception as e:
            continue
    raise HTTPException(status_code=500, detail=f"Could not discover {service_name}")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = None):
    """Send structured logs to Overseer."""
    context = context or {}
    try:
        overseer_url = discover("overseer")
        r = requests.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER, timeout=5)
        if r.status_code >= 400:
            print(f"[Guardian] Overseer log returned {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Guardian] Overseer log failed: {e}")

# -------------------- Policy Cache --------------------

def fetch_policies_from_hub(context: str = "global") -> list:
    now = time.time()
    cache = _policy_cache.get(context)
    if cache and cache.get("expires_at", 0) > now:
        return cache["policies"]

    try:
        hub_url = discover("resource_hub")
        r = requests.get(f"{hub_url}/policy/list",
                         params={"context": context},
                         headers=AUTH_HEADER, timeout=5)
        if r.status_code == 200:
            policies = r.json().get("policies", [])
            _policy_cache[context] = {"policies": policies, "expires_at": now + _POLICY_TTL}
            print(f"[Guardian] Cached {len(policies)} policies.")
            return policies
        else:
            log_to_overseer("N/A", "WARN", f"Hub policy fetch failed {r.status_code}", {"text": r.text})
    except Exception as e:
        log_to_overseer("N/A", "ERROR", f"Policy fetch error: {e}")
    return []

# -------------------- Registration --------------------

def register_self():
    """Register Guardian with Directory and refresh periodically."""
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": SERVICE_URL,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER, timeout=5)
            if r.status_code == 200:
                print(f"[Guardian] Registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Guardian] Registration failed ({r.status_code}). Retrying...")
        except Exception:
            print(f"[Guardian] Directory unavailable. Retry in 5s.")
        time.sleep(5)

def heartbeat():
    """Send periodic TTL updates."""
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": SERVICE_URL,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER, timeout=5)
            print("[Guardian] Heartbeat sent.")
        except Exception:
            print("[Guardian] Heartbeat failed. Restarting registration.")
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

@app.get("/healthz", tags=["System"])
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

@app.post("/guardian/validate_action")
def validate_action(payload: ValidateAction):
    """Evaluate a single action request."""
    task_id, proposed_action = payload.task_id, payload.proposed_action
    context = payload.context or {}
    policies = fetch_policies_from_hub("global")

    try:
        analysis = analyze_payload({
            "task_id": task_id,
            "proposed_action": proposed_action,
            "context": context
        }, policies=policies)
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Analyzer failed: {e}")
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": f"Analyzer error: {e}"})

    decision = analysis.get("decision", "Deny")
    reason = analysis.get("one_liner", "No reason")

    log_to_overseer(task_id, "INFO", f"Guardian decision: {decision}", analysis)

    if decision == "Deny":
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": reason})
    elif decision == "Ambiguous":
        return JSONResponse(status_code=200, content={
            "decision": "Ambiguous",
            "reason": reason,
            "requires_human_review": True,
            "details": analysis
        })
    else:
        return JSONResponse(status_code=200, content={
            "decision": "Allow",
            "reason": reason,
            "details": analysis
        })

@app.post("/guardian/validate_plan")
def validate_plan(payload: ValidatePlan):
    """Evaluate multi-step plan."""
    task_id, plan = payload.task_id, payload.plan
    policies = fetch_policies_from_hub("global")

    if not isinstance(plan, dict) or "steps" not in plan:
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": "Malformed plan"})

    try:
        result = deterministic_eval_plan(plan, policies)
    except Exception as e:
        log_to_overseer(task_id, "ERROR", f"Plan evaluation error: {e}")
        return JSONResponse(status_code=403, content={"decision": "Deny", "reason": "Evaluation error"})

    log_to_overseer(task_id, "INFO", f"Plan decision: {result['decision']}", result)

    if result["decision"] == "Deny":
        return JSONResponse(status_code=403, content=result)
    else:
        return JSONResponse(status_code=200, content=result)

@app.post("/guardian/human_resolve")
def human_resolve(payload: dict):
    """Manual override endpoint for human approval."""
    task_id = payload.get("task_id")
    decision = payload.get("decision")
    if not task_id or decision not in ("Allow", "Deny"):
        raise HTTPException(400, "Invalid input")

    human_overrides[task_id] = {
        "decision": decision,
        "approved_by": payload.get("approved_by", "operator"),
        "note": payload.get("note", ""),
        "timestamp": time.time()
    }
    log_to_overseer(task_id, "INFO", f"Human override: {decision}", human_overrides[task_id])
    return {"status": "Recorded", "task_id": task_id, "decision": decision}

@app.get("/guardian/debug_last")
def debug_last():
    """Debug route to confirm analyzer output easily."""
    if not _policy_cache:
        return {"status": "empty"}
    return {"cached_policies": _policy_cache}

# -------------------- Entrypoint --------------------
if __name__ == "__main__":
    print(f"Starting Guardian on http://0.0.0.0:{SERVICE_PORT} ...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)

