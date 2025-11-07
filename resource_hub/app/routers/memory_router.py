from fastapi import APIRouter, Request, HTTPException
from app.core.db import save_short_term, get_short_term
from app.core.config import settings
from app.core.logging_client import send_log
import typing

router = APIRouter(prefix="/memory/short-term", tags=["ShortTermMemory"])

@router.post("/save")
def save(payload: dict, request: Request):
    task_id = payload.get("task_id")
    text = payload.get("text")
    metadata = payload.get("metadata", {})
    ttl = payload.get("ttl", settings.DEFAULT_TTL)
    if not (task_id and text):
        raise HTTPException(status_code=400, detail="task_id and text required")
    save_short_term(task_id, text, metadata, ttl)
    send_log(settings.SERVICE_NAME, task_id, "INFO", "Short-term memory saved")
    return {"task_id": task_id, "status": "saved"}

@router.get("/{task_id}")
def get(task_id: str, request: Request):
    rows = get_short_term(task_id)
    return {"task_id": task_id, "status": "OK", "data": rows}
