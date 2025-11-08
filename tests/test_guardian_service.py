# tests/test_guardian_service.py
import pytest
from fastapi.testclient import TestClient
import guardian_service as gs

# Create TestClient for guardian FastAPI app
client = TestClient(gs.app)

def test_validate_action_malformed():
    payload = {"task_id":"t1","proposed_action":"","context":{}}
    # Expect Deny (malformed)
    r = client.post("/guardian/validate_action", json=payload)
    assert r.status_code == 403 or r.json().get("decision") == "Deny"

def test_validate_action_ambiguous(monkeypatch):
    # Force analyze_payload to return Ambiguous
    def fake_analyze(payload, policies=None):
        return {"decision":"Ambiguous","approved":False,"score":0.8,"one_liner":"Ambig","reasons":["x"],"details":{}}
    monkeypatch.setattr("guardian_service.analyze_payload", fake_analyze)
    r = client.post("/guardian/validate_action", json={"task_id":"t2","proposed_action":"something","context":{}})
    assert r.status_code == 200
    j = r.json()
    assert j["decision"] == "Ambiguous"
    assert j.get("requires_human_review") in (True, None)

def test_validate_plan_allow(monkeypatch):
    def fake_analyze(payload, policies=None):
        return {"decision":"Allow","approved":True,"score":0.0,"one_liner":"ok","reasons":[],"details":{}}
    monkeypatch.setattr("guardian_service.analyze_payload", fake_analyze)
    # Also ensure deterministic_eval_plan returns Allow
    def fake_det(plan, policies):
        return {"decision":"Allow","reason":"ok","evidence":"","policy_score":0.0}
    monkeypatch.setattr("guardian_service.deterministic_eval_plan", fake_det)
    r = client.post("/guardian/validate_plan", json={"task_id":"p1","plan":{"steps":[{"step_id":1,"goal":"noop"}]}})
    assert r.status_code == 200
    j = r.json()
    assert j["decision"] == "Allow"
