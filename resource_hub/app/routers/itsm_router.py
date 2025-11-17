from fastapi import APIRouter, Request, HTTPException
import json, os
from app.core.config import settings
from core.logging_client import send_log

router = APIRouter(prefix="/mock/itsm", tags=["MockITSM"])

def ensure_itsm_file():
    os.makedirs(os.path.dirname(settings.ITSM_PATH), exist_ok=True)
    if not os.path.exists(settings.ITSM_PATH):
        with open(settings.ITSM_PATH, "w") as f:
            json.dump([], f)
    # handle empty/malformed
    try:
        with open(settings.ITSM_PATH, "r") as f:
            json.load(f)
    except Exception:
        with open(settings.ITSM_PATH, "w") as f:
            json.dump([], f)

def load_itsm():
    ensure_itsm_file()
    with open(settings.ITSM_PATH, "r") as f:
        return json.load(f)

def save_itsm(data):
    ensure_itsm_file()
    with open(settings.ITSM_PATH, "w") as f:
        json.dump(data, f, indent=2)

@router.get("/change")
def list_changes():
    data = load_itsm()
    return {"status": "OK", "changes": data}

@router.post("/change")
def update_change(payload: dict, request: Request):
    task_id = payload.get("task_id")
    change_id = payload.get("change_id")
    new_state = payload.get("new_state")
    if not (task_id and change_id and new_state):
        raise HTTPException(status_code=400, detail="task_id, change_id, new_state required")
    data = load_itsm()
    found = False
    for item in data:
        if item.get("id") == change_id:
            item["state"] = new_state
            found = True
            break
    if not found:
        data.append({"id": change_id, "state": new_state})
    save_itsm(data)
    send_log(settings.SERVICE_NAME, task_id, "INFO", f"Change {change_id} updated to {new_state}", {"change_id": change_id})
    return {"task_id": task_id, "status": "UPDATED", "message": f"Change {change_id} updated to {new_state}"}
