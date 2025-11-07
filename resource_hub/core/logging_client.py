import requests, json
from core.config import settings

def log_event(service, task_id, level, message, context=None):
    payload = {
        "service": service,
        "task_id": task_id,
        "level": level,
        "message": message,
        "context": context or {}
    }
    try:
        requests.post(f"{settings.OVERSEER_URL}/log/event", json=payload, timeout=2)
    except Exception:
        pass  # ignore for now
