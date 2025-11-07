import json
from app.core.config import settings

HEAD = {"Authorization": f"Bearer {settings.SHARED_SECRET}"}

def test_tool_and_memory_cycle(client):
    # list tools
    r = client.get("/tools/list", headers=HEAD)
    assert r.status_code == 200
    # execute tool
    r = client.post("/tools/execute", json={"task_id":"t1","tool":"summarizer","params":{"text":"hello"}}, headers=HEAD)
    assert r.status_code == 200
    # save memory
    r = client.post("/memory/short-term/save", json={"task_id":"t1","text":"hello world"}, headers=HEAD)
    assert r.status_code == 200
    # retrieve
    r = client.get("/memory/short-term/t1", headers=HEAD)
    assert r.status_code == 200
    data = r.json().get("data", [])
    assert len(data) == 1
    assert data[0]["text"] == "hello world"

def test_itsm_update_and_list(client):
    r = client.post("/mock/itsm/change", json={"task_id":"it1","change_id":"CHG-T1","new_state":"Scheduled"}, headers=HEAD)
    assert r.status_code == 200
    r = client.get("/mock/itsm/change", headers=HEAD)
    assert r.status_code == 200
    payload = r.json()
    assert "changes" in payload
    # ensure our new change is present
    assert any(c.get("id") == "CHG-T1" for c in payload["changes"])
