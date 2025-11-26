# guardian_service.py
"""
SHIVA Guardian Service (Option B - Safe Defaults + Sensitive-Only Approval)

Behavior (Option B):
- Simple/benign tools (ping_host, http_status_check, summarizer, system_info, etc.)
  -> auto-ALLOW
- High-risk actions (file modification, shell execution, destructive networking)
  -> DENY if obviously malicious (e.g. rm -rf /) or require explicit operator approval
- Unknown / unregistered tools or unclear parameters
  -> AMBIGUOUS (request human review)
- Time-based "off_hours" checks are intentionally disabled by default.
- Service exposes:
    POST /guardian/validate_plan   -> quick plan-level sanity check
    POST /guardian/validate_action -> action-level check (Allow / Ambiguous / Deny)
    GET  /healthz
- Sends best-effort logs to Overseer if available.

This file is intended to replace the existing guardian_service.py completely.
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict, Optional
import os
import re
import time
import requests
import httpx
import threading
import uuid
import logging
import json

# -------------------------
# CONFIG
# -------------------------
SERVICE_NAME = os.getenv("SERVICE_NAME", "guardian")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8003))
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005").rstrip("/")
SHARED_SECRET = os.getenv("SHARED_SECRET", "mysecretapikey")
AUTH_HEADER = {"X-SHIVA-SECRET": SHARED_SECRET}
OVERSEER_NAME = "overseer"

# -------------------------
# FastAPI app
# -------------------------
app = FastAPI(title="SHIVA Guardian", version="1.0")

# -------------------------
# Logging helper (best-effort to overseer)
# -------------------------
def discover_service(service_name: str) -> Optional[str]:
    """
    Blocking discovery helper for synchronous contexts.
    Returns URL string or None on failure.
    """
    try:
        r = requests.get(f"{DIRECTORY_URL}/discover", params={"service_name": service_name}, headers=AUTH_HEADER, timeout=3)
        r.raise_for_status()
        return r.json().get("url", "").rstrip("/") or None
    except Exception:
        return None

def send_overseer_log(task_id: Optional[str], level: str, message: str, context: Optional[Dict[str, Any]] = None):
    try:
        overseer = discover_service(OVERSEER_NAME)
        if not overseer:
            return
        payload = {
            "service": SERVICE_NAME,
            "task_id": task_id or "N/A",
            "level": level,
            "message": message,
            "context": context or {}
        }
        # fire-and-forget (synchronous)
        requests.post(f"{overseer}/log/event", headers=AUTH_HEADER, json=payload, timeout=3)
    except Exception:
        # swallow errors - best-effort only
        return

# -------------------------
# Policy rules (Option B)
# -------------------------

# Known safe tool names (auto-allowed)
SAFE_TOOLS = {
    "ping_host",
    "http_status_check",
    "summarizer",
    "keyword_extractor",
    "sentiment_analyzer",
    "system_info",
    # add other clearly-safe tools here
}

# Tools that are explicitly "tool-callers" that may be sensitive (require review)
SENSITIVE_TOOLS = {
    "run_shell",        # hypothetical
    "exec_command",
    "write_file",
    "delete_file",
    "modify_file",
    "ssh_exec",
    # others that your stack may expose
}

# Patterns that indicate destructive shell commands or file ops
DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\brm\s+/\b",
    r"\brm\s+\*\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bshutdown\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\b:>\b",            # truncate
    r"\b>w+\b",           # suspicious redirects (approx)
    r"\bnc\b|\bnetcat\b|\bnmap\b|\bmasscan\b",
    r"\biptables\b|\bifconfig\b|\bip\s+addr\b",
    r"\bscp\b|\bssh\b",
    r"\bwget\b|\bcurl\b",
    r"\bddos\b|\bflood\b|\bslowloris\b",
]

# Generic "file operation" words
FILE_OP_KEYWORDS = ["write", "overwrite", "append", "create file", "delete", "remove", "truncate"]

# Minimum decision response schema
def make_decision(decision: str, reason: str = "", details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "details": details or {}
    }

# -------------------------
# Helper functions
# -------------------------
def _safe_text_param_extract(obj: Any) -> str:
    """
    Extract various strings from the action_input structure to evaluate suspicious content.
    """
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        txt = json.dumps(obj)
    except Exception:
        try:
            txt = str(obj)
        except Exception:
            txt = ""
    return txt.lower()

def _matches_destructive(text: str) -> Optional[str]:
    for pat in DESTRUCTIVE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return pat
    return None

def _contains_file_keyword(text: str) -> bool:
    for kw in FILE_OP_KEYWORDS:
        if kw in text:
            return True
    return False

# -------------------------
# Decision logic (core)
# -------------------------
def evaluate_action(task_id: Optional[str], proposed_action: str, action_input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return decision dict: {decision: "Allow"|"Ambiguous"|"Deny", reason: str, details: {...}}
    Option B policy:
      - If tool in SAFE_TOOLS -> Allow
      - If tool in SENSITIVE_TOOLS -> Ambiguous (require human review)
      - If action_input contains destructive patterns -> Deny
      - If unknown/unregistered tool -> Ambiguous
      - If action_input contains file ops or remote-exec hints -> Ambiguous
    """
    try:
        send_overseer_log(task_id, "DEBUG", "Guardian evaluating action", {"action": proposed_action, "input": action_input or {}, "context": context or {}})
    except Exception:
        pass

    # Normalize
    act = (proposed_action or "").strip()
    act_l = act.lower()

    # If clearly safe tool
    if act in SAFE_TOOLS or act_l in SAFE_TOOLS:
        return make_decision("Allow", "Tool is known benign", {"tool": act})

    # If clearly destructive in name (defensive: deny)
    if act_l in ("delete", "format", "shutdown", "reboot"):
        return make_decision("Deny", f"Action name flagged as destructive: {act}", {"tool": act})

    # Inspect action_input payload (stringify)
    input_text = _safe_text_param_extract(action_input)

    # Check destructive shell patterns inside input
    matched = _matches_destructive(input_text)
    if matched:
        return make_decision("Deny", f"Destructive pattern detected: {matched}", {"pattern": matched, "snippet": input_text[:800]})

    # If tool explicitly sensitive
    if act in SENSITIVE_TOOLS or act_l in SENSITIVE_TOOLS:
        return make_decision("Ambiguous", "Tool classified sensitive — require human approval", {"tool": act})

    # If any file-op keywords present in the parameters -> ambiguous (manual review)
    if _contains_file_keyword(input_text):
        return make_decision("Ambiguous", "Parameters indicate file operations — require human approval", {"snippet": input_text[:800]})

    # If parameters include remote-exec / network tools (ssh, scp, nmap, curl) -> ambiguous
    if re.search(r"\bssh\b|\bscp\b|\bnmap\b|\bnetcat\b|\bnc\b|\bwget\b|\bcurl\b", input_text, re.IGNORECASE):
        return make_decision("Ambiguous", "Parameters include remote-exec or network scanning tools — require human approval", {"snippet": input_text[:800]})

    # Unknown tool names -> ambiguous rather than allow
    if act and act not in SAFE_TOOLS:
        # If it's a one-word tool not matching safe list, treat as ambiguous
        return make_decision("Ambiguous", "Tool not recognized as explicitly safe — require human approval", {"tool": act})

    # Fallback - conservative: ambiguous
    return make_decision("Ambiguous", "Unable to safely classify action — require human review", {"tool": act, "snippet": input_text[:800]})

# -------------------------
# Request models
# -------------------------
class ValidateActionRequest(BaseModel):
    task_id: Optional[str]
    proposed_action: str
    action_input: Optional[Dict[str, Any]] = {}
    context: Optional[Dict[str, Any]] = {}

class ValidatePlanRequest(BaseModel):
    task_id: Optional[str]
    plan: Dict[str, Any] = {}

# -------------------------
# Endpoints
# -------------------------
@app.post("/guardian/validate_action")
async def validate_action(req: ValidateActionRequest):
    """
    Evaluate a single proposed action.
    Response: { decision: "Allow"|"Ambiguous"|"Deny", reason: str, details: {...} }
    """
    try:
        decision = evaluate_action(req.task_id, req.proposed_action, req.action_input or {}, req.context or {})
        # Attach a lightweight score for UI (0.0 - ambiguous/deny, 1.0 - allow)
        score = 1.0 if decision["decision"] == "Allow" else (0.5 if decision["decision"] == "Ambiguous" else 0.0)
        decision["details"]["score"] = score
        send_overseer_log(req.task_id, "INFO", f"Guardian decision: {decision['decision']}", {"one_liner": decision["reason"], "details": decision.get("details", {})})
        # For Deny, return HTTP 403? Manager expects decision, not necessarily status code.
        # We keep 200 so orchestration can read structured decision and reason.
        return decision
    except Exception as e:
        send_overseer_log(req.task_id, "ERROR", "Guardian evaluation failed", {"error": str(e)})
        raise HTTPException(500, f"Guardian error: {e}")

@app.post("/guardian/validate_plan")
async def validate_plan(req: ValidatePlanRequest):
    """
    Lightweight plan-level checks. Default: allow simple plans, flag plans with sensitive step targets.
    Returns same { decision, reason, details } shape.
    """
    # Plan structure expected: { plan_id: "...", steps: [{ step_id, goal }, ...] }
    plan = req.plan or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []

    # If there are zero steps -> ambiguous
    if not steps:
        d = make_decision("Ambiguous", "Empty plan or no steps found", {"plan_id": plan.get("plan_id") if isinstance(plan, dict) else None})
        send_overseer_log(req.task_id, "WARN", "Plan ambiguous - empty", {"plan": plan})
        return d

    # Run step-level quick scan
    found_sensitive = []
    found_unknown = []
    for s in steps:
        goal_text = _safe_text_param_extract(s.get("goal") if isinstance(s, dict) else s)
        # If any destructive patterns in the human-written goal -> Deny
        matched = _matches_destructive(goal_text)
        if matched:
            d = make_decision("Deny", f"Destructive pattern in plan step: {matched}", {"step": s})
            send_overseer_log(req.task_id, "WARN", "Plan denied - destructive pattern", {"step": s, "pattern": matched})
            return d
        # If step mentions file ops or remote-exec -> record
        if _contains_file_keyword(goal_text) or re.search(r"\bssh\b|\bnmap\b|\bnc\b|\bnetcat\b", goal_text, re.IGNORECASE):
            found_sensitive.append(s)
        # If step seems like a known safe call (ping/http) then it's fine; else treat as unknown
        if not any(x in goal_text for x in ["ping", "http", "status", "connectivity", "summarize", "summarizer", "system info"]):
            # mark as unknown to require review
            found_unknown.append(s)

    if found_sensitive:
        d = make_decision("Ambiguous", "Plan contains steps that may modify state or perform remote-exec; require human approval", {"suspicious_steps": found_sensitive[:3], "count": len(found_sensitive)})
        send_overseer_log(req.task_id, "WARN", "Plan ambiguous - sensitive steps", {"found_sensitive_count": len(found_sensitive)})
        return d

    if found_unknown:
        d = make_decision("Ambiguous", "Plan contains steps that are not clearly benign; require review", {"unknown_examples": found_unknown[:3], "count": len(found_unknown)})
        send_overseer_log(req.task_id, "INFO", "Plan ambiguous - unknown steps", {"found_unknown_count": len(found_unknown)})
        return d

    # Otherwise allow
    d = make_decision("Allow", "Plan passes deterministic checks", {"plan_id": plan.get("plan_id")})
    send_overseer_log(req.task_id, "INFO", "Plan decision: Allow", {"plan_id": plan.get("plan_id")})
    return d

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

# -------------------------
# Directory registration (background)
# -------------------------
def register_self():
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={"service_name": SERVICE_NAME, "service_url": f"http://127.0.0.1:{SERVICE_PORT}", "ttl_seconds": 60}, headers=AUTH_HEADER, timeout=4)
            if r.status_code == 200:
                print("[Guardian] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                return
            else:
                print("[Guardian] Registration failed:", r.status_code, r.text)
        except Exception as e:
            print("[Guardian] Directory unavailable:", e)
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={"service_name": SERVICE_NAME, "service_url": f"http://127.0.0.1:{SERVICE_PORT}", "ttl_seconds": 60}, headers=AUTH_HEADER, timeout=4)
        except Exception:
            # on failure, re-register
            register_self()
            return

# Start registration thread at import/run
threading.Thread(target=register_self, daemon=True).start()

# -------------------------
# If run directly, start uvicorn (useful for local dev)
# -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("guardian_service:app", host="0.0.0.0", port=SERVICE_PORT, log_level="info")
