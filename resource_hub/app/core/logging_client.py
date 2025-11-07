import requests, threading, time
from app.core.config import settings

def _post(payload):
    try:
        if settings.OVERSEER_URL:
            requests.post(f"{settings.OVERSEER_URL}/log/event", json=payload, timeout=2)
    except Exception:
        # swallow errors
        pass

def send_log(service: str, task_id: str | None, level: str, message: str, context: dict | None = None):
    payload = {
        "service": service,
        "task_id": task_id,
        "level": level,
        "message": message,
        "context": context or {},
        "ts": int(time.time())
    }
    # fire-and-forget to avoid blocking main flow
    t = threading.Thread(target=_post, args=(payload,), daemon=True)
    t.start()
