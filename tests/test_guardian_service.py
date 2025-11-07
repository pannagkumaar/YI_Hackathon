# tests/test_guardian_service.py
import json
import pytest
from fastapi.testclient import TestClient

# Import your FastAPI app object from guardian_service.py
from guardian_service import app

# Import the deterministic evaluator so we can monkeypatch it
import guardian_rules

# Setup TestClient
client = TestClient(app)

# Helper to monkeypatch get_policies_from_hub and log_to_overseer
def fake_policies_ok(task_id):
    return ["Disallow: delete", "Disallow: shutdown"]

def fake_policies_none(task_id):
    return None

# 1) Deterministic deny should short-circuit LLM
def test_validate_action_deterministic_deny(monkeypatch):
    # patch policies fetch
    monkeypatch.setattr("guardian_service.get_policies_from_hub", lambda task_id: ["Disallow: delete"])
    # Use actual deterministic evaluator (no patch) and call endpoint
    payload = {
        "task_id": "task-1",
        "proposed_action": "run_script:{'path':'/srv/x','args':'rm -rf /'}",
        "context": {}
    }
    r = client.post("/guardian/validate_action", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "Deny"

# 2) Ambiguous -> LLM Allow
def test_validate_action_ambiguous_llm_allows(monkeypatch):
    # Make deterministic evaluator return Ambiguous for a test input
    def det_ambiguous(pa, ctx, policies):
        return {"decision":"Ambiguous", "reason":"Ambiguous test", "evidence":"", "policy_score":0.0}
    monkeypatch.setattr("guardian_rules.deterministic_eval_action", det_ambiguous)
    monkeypatch.setattr("guardian_service.get_policies_from_hub", lambda task_id: [])
    # Monkeypatch llm_decide_action to simulate LLM Allow
    monkeypatch.setattr("guardian_service.llm_decide_action", lambda tid, pa, ctx, policies: {"decision":"Allow","reason":"LLM says safe"})
    payload = {"task_id":"t2","proposed_action":"fetch_data:{'url':'https://unknown.com'}","context":{}}
    r = client.post("/guardian/validate_action", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "Allow"
    assert "LLM" in data.get("reason","") or "safe" in data["reason"].lower()

# 3) Ambiguous -> LLM Deny
def test_validate_action_ambiguous_llm_denies(monkeypatch):
    monkeypatch.setattr("guardian_rules.deterministic_eval_action", lambda pa, ctx, policies: {"decision":"Ambiguous","reason":"Ambiguous","evidence":"","policy_score":0.0})
    monkeypatch.setattr("guardian_service.get_policies_from_hub", lambda task_id: [])
    monkeypatch.setattr("guardian_service.llm_decide_action", lambda tid, pa, ctx, policies: {"decision":"Deny","reason":"LLM denies"})
    payload = {"task_id":"t3","proposed_action":"exec_shell:{'cmd':'ls'}","context":{}}
    r = client.post("/guardian/validate_action", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "Deny"
    assert "LLM" in data.get("reason","") or "deny" in data["reason"].lower()

# 4) Ambiguous -> LLM malformed result -> Deny
def test_validate_action_llm_malformed(monkeypatch):
    monkeypatch.setattr("guardian_rules.deterministic_eval_action", lambda pa, ctx, policies: {"decision":"Ambiguous","reason":"Amb","evidence":"","policy_score":0.0})
    monkeypatch.setattr("guardian_service.get_policies_from_hub", lambda task_id: [])
    # LLM returns malformed data (no 'decision')
    monkeypatch.setattr("guardian_service.llm_decide_action", lambda tid, pa, ctx, policies: {"foo":"bar"})
    payload = {"task_id":"t4","proposed_action":"exec_shell:{'cmd':'ls'}","context":{}}
    r = client.post("/guardian/validate_action", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "Deny"

# 5) LLM raises exception -> Deny
def test_validate_action_llm_raises(monkeypatch):
    monkeypatch.setattr("guardian_rules.deterministic_eval_action", lambda pa, ctx, policies: {"decision":"Ambiguous","reason":"Amb","evidence":"","policy_score":0.0})
    monkeypatch.setattr("guardian_service.get_policies_from_hub", lambda task_id: [])
    def raise_exc(*args, **kwargs):
        raise RuntimeError("LLM broken")
    monkeypatch.setattr("guardian_service.llm_decide_action", raise_exc)
    payload = {"task_id":"t5","proposed_action":"exec_shell:{'cmd':'ls'}","context":{}}
    r = client.post("/guardian/validate_action", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "Deny"

# 6) Plan deterministic deny (too many steps)
def test_validate_plan_too_many_steps(monkeypatch):
    # Use real deterministic eval to check >10 steps
    monkeypatch.setattr("guardian_service.get_policies_from_hub", lambda task_id: [])
    plan = {"task_id":"t6","plan":{"steps":[{"step_id":i,"goal":"ok"} for i in range(11)]}}
    r = client.post("/guardian/validate_plan", json=plan)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "Deny"
