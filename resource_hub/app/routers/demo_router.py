from fastapi import APIRouter, Request
from app.services.tool_service import execute_tool
from app.core.db import save_short_term
from app.core.config import settings
from core.logging_client import send_log
import uuid

@router.get("/sequence")
def demo_sequence():
    # Simulate a real flow: run summarizer -> save memory -> create ITSM change -> log
    task_id = str(uuid.uuid4())
    sample_text = "The database needs a security patch. Reboot scheduled at midnight. Monitor services."
    # execute summarizer
    summary = execute_tool("summarizer", {"text": sample_text})
    save_short_term(task_id, summary, {"source": "demo"}, settings.DEFAULT_TTL)
    send_log(settings.SERVICE_NAME, task_id, "INFO", "Demo: summarized and saved memory", {"summary": summary})
    # create a mock ITSM change
    from app.routers.itsm_router import load_itsm, save_itsm
    changes = load_itsm()
    change_id = f"CHG-DEMO-{int(uuid.uuid4().int & (1<<20))}"
    changes.append({"id": change_id, "state": "Scheduled", "desc": summary})
    save_itsm(changes)
    send_log(settings.SERVICE_NAME, task_id, "INFO", f"Demo: ITSM change created {change_id}", {"change_id": change_id})
    return {"task_id": task_id, "summary": summary, "change_id": change_id}
