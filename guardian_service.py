# 📄 guardian_service.py
from fastapi import FastAPI, HTTPException, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key # Import our new auth function
from gemini_client import get_model, generate_json
from guardian_rules import deterministic_eval_action, deterministic_eval_plan, parse_proposed_action, action_matches_plan_score
import json
from typing import Optional

GUARDIAN_SYSTEM_PROMPT = """
You are the "Guardian," a compliance and safety assistant for the SHIVA agent system.
Your sole purpose is to evaluate a "proposed_action" or "plan" against a set of "policies."

You must respond ONLY with a JSON object with two keys:
1. "decision": Must be either "Allow" or "Deny".
2. "reason": A brief, clear explanation for your decision.

Evaluate strictly. If a policy is "Disallow: <keyword>" and the <keyword> is in the 
proposed_action, you must "Deny" it. Also deny any plan with > 10 steps 
as "excessively complex".
"""


# --- simple in-memory cache for policies ---
_policy_cache = {
    # key: context string -> {"policies": [...], "expires_at": float}
}
_POLICY_TTL = 30  # seconds



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



def sanitize_for_llm(text: str) -> str:
    """Strip obvious injection constructs and truncate reasonably."""
    if not text:
        return ""
    t = text.replace("```system", "```").replace("<script", "<removed>").strip()
    # limit length
    if len(t) > 2000:
        t = t[:2000] + " ...[truncated]"
    return t

# Helper: fetch runbook snippets from Resource Hub (RAG)
def fetch_runbook_snippets(task_id: str, query: str, max_snippets: int = 3):
    try:
        hub_url = discover("resource-hub-service")
        r = requests.post(f"{hub_url}/runbook/search",
                          json={"query": query, "max_snippets": max_snippets},
                          headers=AUTH_HEADER,
                          timeout=5)
        if r.status_code == 200:
            return r.json().get("snippets", [])
        else:
            print(f"[Guardian] Runbook search failed: {r.status_code} {r.text}")
            log_to_overseer(task_id, "WARN", f"Runbook search failed: {r.status_code}", {"text": r.text[:200]})
    except Exception as e:
        print(f"[Guardian] Exception calling runbook: {e}")
        log_to_overseer(task_id, "WARN", f"Runbook fetch error: {e}")

    # fallback
    return [{"title": "No runbook available", "text": "No additional runbook context available."}]

def llm_decide_action(task_id: str, proposed_action: str, context: dict, policies: list) -> dict:
    # 1) get runbook snippets (RAG)
    snippets = fetch_runbook_snippets(task_id, proposed_action, max_snippets=3)

    # 2) build system instruction
    system_instruction = (
        "You are a safety assistant. Output only valid JSON with keys: "
        "\"decision\" (Allow or Deny) and \"reason\" (short string). "
        "Use the provided trusted runbook snippets and policies to make a conservative decision."
    )

    # 3) prepare prompt parts (include trusted runbook)
    sanitized = sanitize_for_llm(proposed_action)
    runbook_text = "\n\n".join([f"{s['title']}: {s['text']}" for s in snippets])

    prompt_parts = [
        f"TRUSTED RUNBOOK / POLICIES: {json.dumps(policies)}\n{runbook_text}\n\n",
        f"UNTRUSTED PROPOSED ACTION: <<BEGIN_ACTION>>{sanitized}<<END_ACTION>>\n",
        "Evaluate strictly and return JSON: {\"decision\":\"Allow\"|\"Deny\",\"reason\":\"...\"}."
    ]

    # 4) call model
    try:
        model = get_model(system_instruction=system_instruction)
        response = generate_json(model, prompt_parts)
        if isinstance(response, dict) and "decision" in response:
            d = response["decision"]
            if d not in ("Allow","Deny"):
                audit_decision_to_overseer(task_id, "Deny", "LLM returned invalid decision", {"raw": response})
                return {"decision":"Deny","reason":"LLM returned invalid decision"}
            # structured audit: include LLM reason and raw response if available
            audit_decision_to_overseer(task_id, d, response.get("reason", "No reason"), {"raw": response})
            return {"decision":d,"reason":response.get("reason","No reason")}
        else:
            return {"decision":"Deny","reason":"LLM produced invalid output"}
    except Exception as e:
        return {"decision":"Deny","reason":f"LLM fallback failed: {str(e)}"}

def llm_decide_plan(task_id: str, plan: dict, policies: list) -> dict:
    # summarize plan text
    plan_text = json.dumps(plan) if isinstance(plan, dict) else str(plan)
    # fetch runbook snippets targeted at the plan summary
    snippets = fetch_runbook_snippets(task_id, plan_text[:800], max_snippets=4)

    system_instruction = (
        "You are a safety assistant. Output only valid JSON with keys: "
        "\"decision\" (Allow or Deny) and \"reason\" (short string). "
        "Use the trusted runbook and policies to evaluate the plan."
    )

    runbook_text = "\n\n".join([f"{s['title']}: {s['text']}" for s in snippets])
    if len(plan_text) > 3000:
        plan_text = plan_text[:3000] + " ...[truncated]"

    prompt_parts = [
        f"TRUSTED RUNBOOK / POLICIES: {json.dumps(policies)}\n{runbook_text}\n\n",
        f"PLAN (untrusted): <<BEGIN_PLAN>>{plan_text}<<END_PLAN>>\n",
        "Evaluate the plan strictly and return JSON: {\"decision\":\"Allow\"|\"Deny\",\"reason\":\"...\"}."
    ]

    try:
        model = get_model(system_instruction=system_instruction)
        response = generate_json(model, prompt_parts)
        if isinstance(response, dict) and "decision" in response:
            d = response["decision"]
            if d not in ("Allow","Deny"):
                audit_decision_to_overseer(task_id, "Deny", "LLM returned invalid decision", {"raw": response})
                return {"decision":"Deny","reason":"LLM returned invalid decision"}
            # structured audit: include LLM reason and raw response if available
            audit_decision_to_overseer(task_id, d, response.get("reason", "No reason"), {"raw": response})
            return {"decision":d,"reason":response.get("reason","No reason")}
        else:
            return {"decision":"Deny","reason":"LLM produced invalid output for plan"}
    except Exception as e:
        return {"decision":"Deny","reason":f"LLM fallback failed for plan: {str(e)}"}



# --- Mock Agent Function (UPDATED) ---
def use_agent(prompt: str, input_data: dict, policies: list) -> dict:
    """(UPDATED) AI-based validation logic using Gemini."""
    print(f"[Guardian] AI Agent called with prompt: {prompt}")

    # Construct the prompt for the model
    prompt_parts = [
        f"User Prompt: {prompt}\n",
        f"Policies: {json.dumps(policies)}\n",
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
# --- End Mock Agent Function ---


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

def fetch_policies_from_hub(context: str = "global") -> list:
    """Fetch policies from Resource Hub with short TTL caching. Returns list of policy strings."""
    now = time.time()
    cache = _policy_cache.get(context)
    if cache and cache.get("expires_at", 0) > now:
        return cache.get("policies", [])

    try:
        hub_url = discover("resource-hub-service")
        # Resource Hub exposes GET /policy/list?context=global
        r = requests.get(f"{hub_url}/policy/list", params={"context": context}, headers=AUTH_HEADER, timeout=5)
        if r.status_code == 200:
            policies = r.json().get("policies", [])
            _policy_cache[context] = {"policies": policies, "expires_at": now + _POLICY_TTL}
            log_to_overseer("N/A", "INFO", f"Fetched {len(policies)} policies from Resource Hub", {"context": context})
            return policies
        else:
            log_to_overseer("N/A", "WARN", f"Resource Hub policy fetch returned {r.status_code}", {"text": r.text[:200]})
    except Exception as e:
        log_to_overseer("N/A", "ERROR", f"Exception fetching policies from Resource Hub: {e}")

    # fallback: return empty list (deterministic rules still exist locally)
    return []

def audit_decision_to_overseer(task_id: str, decision: str, reason: str, details: dict = None):
    payload = {
        "service": SERVICE_NAME,
        "task_id": task_id or "N/A",
        "level": "INFO" if decision == "Allow" else "WARN",
        "message": f"Guardian Decision: {decision}",
        "context": {
            "decision": decision,
            "reason": reason,
            **(details or {})
        }
    }
    try:
        overseer_url = discover("overseer-service")
        requests.post(f"{overseer_url}/log/event", json=payload, headers=AUTH_HEADER, timeout=3)
    except Exception as e:
        # best-effort: log locally
        print(f"[Guardian] Failed to send audit to Overseer: {e}")



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


@app.post("/guardian/validate_action")
def validate_action(payload: dict):
    """
    Expected payload:
    {
      "task_id": "<id>",
      "proposed_action": "<string>",
      "context": {...},            # optional
      "policies_context": "global",# optional
      "approved_plan": {...}       # optional - plan object from Manager
    }
    """
    task_id = payload.get("task_id", "N/A")
    proposed_action = payload.get("proposed_action", "")
    context = payload.get("context", {})
    policies_context = payload.get("policies_context", "global")
    approved_plan = payload.get("approved_plan")

    # 1) Fetch dynamic policies (best-effort, cached)
    policies = fetch_policies_from_hub(policies_context) or []

    # 2) Deterministic checks
    det = deterministic_eval_action(proposed_action, context, policies)

    # Audit deterministic decision
    audit_decision_to_overseer(task_id, det["decision"], det.get("reason", ""), {
        "evidence": det.get("evidence", ""),
        "policy_score": det.get("policy_score", 0.0),
        "source": "deterministic"
    })

    # 3) If deterministic allowed and approved_plan present -> cross-check action against plan
    if det["decision"] == "Allow" and approved_plan:
        # try parsing for a more meaningful action text
        ok, parsed_action, parse_err = parse_proposed_action(proposed_action)
        if ok:
            # create a compact text describing the action for matching
            action_text = f"{parsed_action.get('action')} {json.dumps(parsed_action.get('action_input', {}))}"
        else:
            action_text = proposed_action

        # compute best matching step in the approved plan
        score, best_step_id = action_matches_plan_score(action_text, approved_plan)

        # threshold: if match is too weak then require human review
        PLAN_MATCH_THRESHOLD = 0.50  # tune as needed
        if score < PLAN_MATCH_THRESHOLD:
            reason = f"Action does not match approved plan (best_score={score:.2f})"
            audit_decision_to_overseer(task_id, "Ambiguous", reason, {"best_score": score, "matched_step": best_step_id})
            return {
                "decision": "Ambiguous",
                "reason": reason,
                "evidence": action_text,
                "policy_score": score,
                "requires_human_review": True
            }

    # 4) If deterministic returned Ambiguous, call LLM fallback
    if det["decision"] == "Ambiguous":
        llm_resp = llm_decide_action(task_id, proposed_action, context, policies)
        # llm_decide_action audits result itself (we double-audit for safety)
        audit_decision_to_overseer(task_id, llm_resp.get("decision", "Deny"), llm_resp.get("reason", ""), {
            "source": "llm_fallback"
        })
        final_decision = llm_resp.get("decision", "Deny")
        response_body = {
            "decision": final_decision,
            "reason": llm_resp.get("reason", "LLM fallback returned no reason"),
            **({"requires_human_review": True} if final_decision == "Ambiguous" else {})
        }
        # API Contract: Return 403 Forbidden for Deny decisions
        if final_decision == "Deny":
            return JSONResponse(status_code=403, content=response_body)
        return response_body

    # 5) Deterministic final Allow/Deny -> return
    final_decision = det["decision"]
    response_body = {
        "decision": final_decision,
        "reason": det.get("reason", ""),
        "evidence": det.get("evidence", ""),
        "policy_score": det.get("policy_score", 0.0)
    }
    # API Contract: Return 403 Forbidden for Deny decisions
    if final_decision == "Deny":
        return JSONResponse(status_code=403, content=response_body)
    # API Contract: Return 200 OK with "message" field for Allow
    if final_decision == "Allow":
        response_body["message"] = det.get("reason", "Action allowed")
    return response_body

@app.post("/guardian/validate_plan")
def validate_plan(payload: dict):
    """
    Expected payload:
    {
      "task_id": "<id>",
      "plan": { ... },           # plan object
      "policies_context": "global"
    }
    """
    task_id = payload.get("task_id", "N/A")
    plan = payload.get("plan", {})
    policies_context = payload.get("policies_context", "global")

    # 1) Fetch dynamic policies
    policies = fetch_policies_from_hub(policies_context) or []

    # 2) Deterministic check
    det = deterministic_eval_plan(plan, policies)

    # 3) Audit deterministic result
    audit_decision_to_overseer(task_id, det["decision"], det.get("reason", ""), {
        "policy_score": det.get("policy_score", 0.0),
        "source": "deterministic"
    })

    # 4) If ambiguous, call LLM fallback (which will also audit)
    if det["decision"] == "Ambiguous":
        llm_res = llm_decide_plan(task_id, plan, policies)
        audit_decision_to_overseer(task_id, llm_res.get("decision", "Deny"), llm_res.get("reason", ""), {
            "source": "llm_fallback"
        })
        final_decision = llm_res.get("decision", "Deny")
        response_body = {
            "decision": final_decision,
            "reason": llm_res.get("reason", "")
        }
        # API Contract: Add warnings field for Allow decisions
        if final_decision == "Allow":
            response_body["warnings"] = []
        return response_body

    # API Contract: Add warnings field for Allow decisions
    final_decision = det["decision"]
    response_body = {
        "decision": final_decision,
        "reason": det.get("reason", ""),
        "evidence": det.get("evidence", ""),
        "policy_score": det.get("policy_score", 0.0)
    }
    if final_decision == "Allow":
        # Collect any warnings from the evaluation
        warnings = []
        if det.get("policy_score", 0.0) > 0.5:
            warnings.append("High policy similarity score detected")
        if len(plan.get("steps", [])) > 5:
            warnings.append("Plan has many steps - consider breaking down")
        response_body["warnings"] = warnings
    return response_body


if __name__ == "__main__":
    print("Starting Guardian Service on port 8003...")
    uvicorn.run(app, host="0.0.0.0", port=8003)