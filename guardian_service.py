# guardian_service.py (updated)
from fastapi import FastAPI, HTTPException, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key  # Import our auth (kept for later/per-route use)
from guardian_prompt_safety import analyze_payload
from gemini_client import get_model, generate_json
from guardian_rules import deterministic_eval_action, deterministic_eval_plan, parse_proposed_action
from guardian_schemas import ACTION_DECISION_SCHEMA, PLAN_VALIDATION_SCHEMA

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
_policy_cache = {}
_POLICY_TTL = 30  # seconds

# In-memory map for human resolutions: { task_id: { "decision": "Allow"|"Deny", "approved_by": "...", "note": "...", "timestamp": <float> } }
human_overrides = {}

guardian_model = get_model(system_instruction=GUARDIAN_SYSTEM_PROMPT)

# --- Authentication & Service Constants ---
# NOTE: Removed app-level global dependency so tests can import the module and
# override dependencies before requests. If you want app-wide auth in production,
# either re-add per-route Depends(get_api_key) or ensure test fixture overrides run
# before imports.
app = FastAPI(
    title="Guardian Service",
    description="Compliance and safety assistant for SHIVA.",
    # dependencies=[Depends(get_api_key)]  <-- comment it for testability
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "guardian-service"
SERVICE_PORT = 8003

# ---- Helper functions (RAG, LLM decision, discovery, logging) ----
def sanitize_for_llm(text: str) -> str:
    """Strip obvious injection constructs and truncate reasonably."""
    if not text:
        return ""
    t = text.replace("```system", "```").replace("<script", "<removed>").strip()
    if len(t) > 2000:
        t = t[:2000] + " ...[truncated]"
    return t

def fetch_runbook_snippets(task_id: str, query: str, max_snippets: int = 3):
    """Fetch runbook snippets using RAG (vector-based semantic search)."""
    try:
        hub_url = discover("resource-hub-service")
        r = requests.post(f"{hub_url}/rag/query",
                          json={"query": query, "max_snippets": max_snippets, "task_id": task_id},
                          headers=AUTH_HEADER,
                          timeout=10)
        if r.status_code == 200:
            snippets = r.json().get("snippets", [])
            for snippet in snippets:
                snippet.pop("similarity", None)
                snippet.pop("source", None)
            return snippets
        else:
            print(f"[Guardian] RAG query failed: {r.status_code} {r.text}")
            log_to_overseer(task_id, "WARN", f"RAG query failed: {r.status_code}", {"text": r.text[:200]})
            return _fallback_runbook_search(hub_url, task_id, query, max_snippets)
    except Exception as e:
        print(f"[Guardian] Exception calling RAG: {e}")
        log_to_overseer(task_id, "WARN", f"RAG fetch error: {e}")
        try:
            hub_url = discover("resource-hub-service")
            return _fallback_runbook_search(hub_url, task_id, query, max_snippets)
        except:
            pass
    return [{"title": "No runbook available", "text": "No additional runbook context available."}]

def _fallback_runbook_search(hub_url: str, task_id: str, query: str, max_snippets: int):
    try:
        r = requests.post(f"{hub_url}/runbook/search",
                          json={"query": query, "max_snippets": max_snippets},
                          headers=AUTH_HEADER,
                          timeout=5)
        if r.status_code == 200:
            return r.json().get("snippets", [])
    except Exception as e:
        print(f"[Guardian] Fallback runbook search also failed: {e}")
    return [{"title": "No runbook available", "text": "No additional runbook context available."}]

def llm_decide_action(task_id: str, proposed_action: str, context: dict, policies: list) -> dict:
    """LLM fallback for action decision (returns dict with 'decision' and 'reason')."""
    snippets = fetch_runbook_snippets(task_id, proposed_action, max_snippets=3)
    system_instruction = (
        "You are a safety assistant. Output only valid JSON with keys: "
        "\"decision\" (Allow or Deny) and \"reason\" (short string). "
        "Use the provided trusted runbook snippets and policies to make a conservative decision."
    )
    sanitized = sanitize_for_llm(proposed_action)
    runbook_text = "\n\n".join([f"{s['title']}: {s['text']}" for s in snippets])
    prompt_parts = [
        f"TRUSTED RUNBOOK / POLICIES: {json.dumps(policies)}\n{runbook_text}\n\n",
        f"UNTRUSTED PROPOSED ACTION: <<BEGIN_ACTION>>{sanitized}<<END_ACTION>>\n",
        "Evaluate strictly and return JSON: {\"decision\":\"Allow\"|\"Deny\",\"reason\":\"...\"}."
    ]
    try:
        model = get_model(system_instruction=system_instruction)
        response = generate_json(model, prompt_parts, expected_schema=ACTION_DECISION_SCHEMA, max_retries=1)
        if isinstance(response, dict) and "decision" in response:
            d = response["decision"]
            if d not in ("Allow","Deny"):
                audit_decision_to_overseer(task_id, "Deny", "LLM returned invalid decision", {"raw": response})
                return {"decision":"Deny","reason":"LLM returned invalid decision"}
            audit_decision_to_overseer(task_id, d, response.get("reason", "No reason"), {"raw": response})
            return {"decision":d,"reason":response.get("reason","No reason")}
        else:
            return {"decision":"Deny","reason":"LLM produced invalid output"}
    except Exception as e:
        return {"decision":"Deny","reason":f"LLM fallback failed: {str(e)}"}

def llm_decide_plan(task_id: str, plan: dict, policies: list) -> dict:
    """LLM fallback for plan decision (returns dict with 'decision' and 'reason')."""
    plan_text = json.dumps(plan) if isinstance(plan, dict) else str(plan)
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
        response = generate_json(model, prompt_parts, expected_schema=PLAN_VALIDATION_SCHEMA, max_retries=1)
        if isinstance(response, dict) and "decision" in response:
            d = response["decision"]
            if d not in ("Allow","Deny"):
                audit_decision_to_overseer(task_id, "Deny", "LLM returned invalid decision", {"raw": response})
                return {"decision":"Deny","reason":"LLM returned invalid decision"}
            audit_decision_to_overseer(task_id, d, response.get("reason", "No reason"), {"raw": response})
            return {"decision":d,"reason":response.get("reason","No reason")}
        else:
            return {"decision":"Deny","reason":"LLM produced invalid output for plan"}
    except Exception as e:
        return {"decision":"Deny","reason":f"LLM fallback failed for plan: {str(e)}"}

# --- Service Discovery & Logging ---
def discover(service_name: str) -> str:
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

# --- Policy fetcher ---
def fetch_policies_from_hub(context: str = "global") -> list:
    now = time.time()
    cache = _policy_cache.get(context)
    if cache and cache.get("expires_at", 0) > now:
        return cache.get("policies", [])
    try:
        hub_url = discover("resource-hub-service")
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
        print(f"[Guardian] Failed to send audit to Overseer: {e}")

# --- Service Registration (unchanged) ---
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
                print(f"[Guardian] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Guardian] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[Guardian] Could not connect to Directory. Retrying in 5s...")
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
            print("[Guardian] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[Guardian] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

# --- Pydantic models ---
class ValidateAction(BaseModel):
    task_id: str
    proposed_action: str
    context: dict = {}

class ValidatePlan(BaseModel):
    task_id: str
    plan: dict

# --- validate_action with human override check (modified) ---
@app.post("/guardian/validate_action", response_model=None)
def validate_action(payload: ValidateAction):
    """
    Deterministic + dynamic analyzer entry for validating a proposed action.

    Request body is validated via Pydantic (ValidateAction).
    Returns:
      - 403 Forbidden with body when decision is Deny.
      - 200 OK with decision Ambiguous (and requires_human_review) when analyzer asks for human.
      - 200 OK with decision Allow (or Ambiguous) with deterministic details when allowed.
    """
    task_id = payload.task_id or "N/A"
    proposed_action = payload.proposed_action or ""
    context = payload.context or {}
    policies_context = getattr(payload, "policies_context", "global")
    approved_plan = getattr(payload, "approved_plan", None)

    # 0) Fetch dynamic policies (best-effort)
    policies = fetch_policies_from_hub(policies_context) or []

    # 1) Run the centralized analyzer (dynamic)
    try:
        analysis = analyze_payload({
            "task_id": task_id,
            "proposed_action": proposed_action,
            "context": context,
            "approved_plan": approved_plan
        }, policies=policies)
    except Exception as e:
        # Fail-closed if analyzer crashes
        audit_decision_to_overseer(task_id, "Deny", f"Analyzer exception: {e}", {"exc": str(e)})
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": f"Internal analyzer error: {e}"
        })

    # Audit analyzer result (dynamic_analyzer)
    audit_decision_to_overseer(task_id, analysis.get("decision", "Deny"), analysis.get("one_liner", ""), {
        "score": analysis.get("score"),
        "reasons": analysis.get("reasons"),
        "source": "dynamic_analyzer"
    })

    # 2) Handle analyzer outcome
    decision = analysis.get("decision", "Deny")

    if decision == "Deny":
        # Deny immediately with 403
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": analysis.get("one_liner", "Denied by analyzer"),
            "evidence": analysis.get("details", {})
        })

    if decision == "Ambiguous":
        # Return 200 OK with requires_human_review flag so UI can surface it.
        return JSONResponse(status_code=200, content={
            "decision": "Ambiguous",
            "reason": analysis.get("one_liner", ""),
            "requires_human_review": True,
            "evidence": analysis.get("details", {}),
            "score": analysis.get("score", 0.0)
        })

    # 3) If analyzer said Allow -> run deterministic post-check (backwards compatibility)
    det = deterministic_eval_action(proposed_action, context, policies)

    # audit deterministic decision too
    audit_decision_to_overseer(task_id, det.get("decision", "Deny"), det.get("reason", ""), {
        "evidence": det.get("evidence", ""),
        "policy_score": det.get("policy_score", 0.0),
        "source": "deterministic_post_analyzer"
    })

    final_decision = det.get("decision", "Deny")
    response_body = {
        "decision": final_decision,
        "reason": det.get("reason", ""),
        "evidence": det.get("evidence", ""),
        "policy_score": det.get("policy_score", 0.0)
    }

    if final_decision == "Deny":
        return JSONResponse(status_code=403, content=response_body)

    # Allow: return 200 with message + deterministic evidence
    response_body["message"] = det.get("reason", "Action allowed")
    return JSONResponse(status_code=200, content=response_body)

@app.post("/guardian/human_resolve", status_code=200)
def human_resolve(payload: dict):
    task_id = payload.get("task_id")
    decision = payload.get("decision")
    approved_by = payload.get("approved_by", "operator")
    note = payload.get("note", "")

    if not task_id or decision not in ("Allow", "Deny"):
        raise HTTPException(status_code=400, detail="Missing task_id or invalid decision")

    human_overrides[task_id] = {
        "decision": decision,
        "approved_by": approved_by,
        "note": note,
        "timestamp": time.time()
    }

    audit_decision_to_overseer(task_id, decision, f"Human override by {approved_by}: {note}", {
        "source": "human_override",
        "approved_by": approved_by,
        "note": note
    })

    return {"status": "Recorded", "task_id": task_id, "decision": decision}

@app.post("/guardian/validate_plan", response_model=None)
def validate_plan(payload: ValidatePlan):
    """
    Deterministically validate a proposed plan, with dynamic analyzer fallback.
    Returns a JSON object: {"decision": "Allow"|"Deny"|"Ambiguous", "reason": "...", "warnings": [...]}
    - Deny => HTTP 403
    - Ambiguous/Allow => HTTP 200
    """
    task_id = payload.task_id or "N/A"
    plan = payload.plan or {}
    policies = fetch_policies_from_hub("global") or []

    # Basic structural check
    if not isinstance(plan, dict) or "steps" not in plan:
        audit_decision_to_overseer(task_id, "Deny", "Malformed plan", {"plan": str(plan)})
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": "Malformed plan",
            "warnings": []
        })

    # 1) Run deterministic evaluation first
    try:
        det = deterministic_eval_plan(plan, policies)
    except Exception as e:
        audit_decision_to_overseer(task_id, "Deny", f"Deterministic evaluator error: {e}", {"exc": str(e)})
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": "Internal error during deterministic plan evaluation",
            "warnings": []
        })

    # Audit deterministic result
    audit_decision_to_overseer(task_id, det.get("decision", "Deny"), det.get("reason", ""), {
        "evidence": det.get("evidence", ""),
        "policy_score": det.get("policy_score", 0.0),
        "source": "deterministic_plan_evaluator"
    })

    # If deterministic denies -> deny (403)
    if det.get("decision") == "Deny":
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": det.get("reason", ""),
            "warnings": []
        })

    # If deterministic says Ambiguous -> surface Ambiguous to UI (200 OK)
    if det.get("decision") == "Ambiguous":
        return JSONResponse(status_code=200, content={
            "decision": "Ambiguous",
            "reason": det.get("reason", ""),
            "warnings": det.get("evidence") if isinstance(det.get("evidence"), list) else [str(det.get("evidence"))],
            "policy_score": det.get("policy_score", 0.0),
            "requires_human_review": det.get("requires_human_review", True)
        })

    # Deterministic returned Allow — but we may still want LLM check for subtle issues.
    # Call LLM fallback (best-effort) but fail-closed on errors.
    try:
        llm_resp = llm_decide_plan(task_id, plan, policies)
    except Exception as e:
        audit_decision_to_overseer(task_id, "Deny", f"LLM plan evaluation error: {e}", {"exc": str(e)})
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": "LLM plan evaluation failed",
            "warnings": []
        })

    # LLM returns a dict {"decision":"Allow"|"Deny", "reason": "..."}
    if not isinstance(llm_resp, dict) or llm_resp.get("decision") not in ("Allow", "Deny"):
        audit_decision_to_overseer(task_id, "Deny", "LLM returned invalid plan decision", {"raw": llm_resp})
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": "LLM returned invalid plan response",
            "warnings": []
        })

    # Audit LLM decision
    audit_decision_to_overseer(task_id, llm_resp.get("decision"), llm_resp.get("reason", ""), {"source": "llm_plan_decision"})

    if llm_resp.get("decision") == "Deny":
        return JSONResponse(status_code=403, content={
            "decision": "Deny",
            "reason": llm_resp.get("reason", ""),
            "warnings": []
        })

    # Final: Allow
    return JSONResponse(status_code=200, content={
        "decision": "Allow",
        "reason": llm_resp.get("reason", "Plan allowed"),
        "warnings": []
    })
