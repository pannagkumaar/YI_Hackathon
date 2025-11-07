from fastapi import APIRouter, Depends, HTTPException
import json, os
from core.auth import verify_auth
from core.config import settings
from core.logging_client import log_event

router = APIRouter(prefix="/mock/itsm", tags=["MockITSM"])
SERVICE = "resource-hub"

# --- Utility functions ---

def ensure_file_exists():
    """Create the ITSM file if it doesn't exist or is empty."""
    os.makedirs(os.path.dirname(settings.ITSM_PATH), exist_ok=True)
    if not os.path.exists(settings.ITSM_PATH):
        with open(settings.ITSM_PATH, "w") as f:
            json.dump([], f)
    # Handle case: file exists but is empty or invalid
    try:
        with open(settings.ITSM_PATH, "r") as f:
            json.load(f)
    except (json.JSONDecodeError, ValueError):
        with open(settings.ITSM_PATH, "w") as f:
            json.dump([], f)

def load_itsm():
    ensure_file_exists()
    with open(settings.ITSM_PATH, "r") as f:
        return json.load(f)

def save_itsm(data):
    ensure_file_exists()
    with open(settings.ITSM_PATH, "w") as f:
        json.dump(data, f, indent=2)

# --- Routes ---

@router.get("/change")
def list_changes(auth=Depends(verify_auth)):
    data = load_itsm()
    return {"status": "OK", "changes": data}

@router.post("/change")
def update_change(payload: dict, auth=Depends(verify_auth)):
    task_id = payload.get("task_id")
    change_id = payload.get("change_id")
    new_state = payload.get("new_state")

    if not (task_id and change_id and new_state):
        raise HTTPException(status_code=400, detail="Missing required fields")

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
    msg = f"Change {change_id} updated to {new_state}"
    log_event(SERVICE, task_id, "INFO", msg, {"change_id": change_id})
    return {"task_id": task_id, "status": "UPDATED", "message": msg}
