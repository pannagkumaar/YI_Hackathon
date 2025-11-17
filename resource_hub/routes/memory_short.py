from fastapi import APIRouter, Depends
import sqlite3, time, json
from core.auth import verify_auth
from core.config import settings
from core.logging_client import send_log


router = APIRouter(prefix="/memory/short-term", tags=["ShortTermMemory"])
SERVICE = "resource-hub"

@router.post("/save")
def save_memory(payload: dict, auth=Depends(verify_auth)):
    task_id = payload["task_id"]
    text = payload["text"]
    metadata = json.dumps(payload.get("metadata", {}))
    ttl = 86400
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO short_term_memory(task_id,text,metadata,created_at,ttl) VALUES (?,?,?,?,?)",
              (task_id, text, metadata, time.time(), ttl))
    conn.commit(); conn.close()
    log_event(SERVICE, task_id, "INFO", "Short-term memory saved")
    return {"task_id": task_id, "status": "saved"}

@router.get("/{task_id}")
def get_memory(task_id: str, auth=Depends(verify_auth)):
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT text, metadata, created_at FROM short_term_memory WHERE task_id=?", (task_id,))
    rows = c.fetchall()
    conn.close()
    return {"task_id": task_id, "status": "OK", "data": [{"text": r[0], "metadata": json.loads(r[1]), "created_at": r[2]} for r in rows]}
