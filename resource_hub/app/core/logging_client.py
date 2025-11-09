import os
import requests
import json
import datetime

# ───────────────────────────────────────────────
# Global SHIVA Logging Client
# ───────────────────────────────────────────────

def send_log(service: str, task_id: str, level: str, message: str, context: dict = None):
    """
    Send a structured log event to the Overseer service.

    Args:
        service (str): Name of the sending service (e.g., 'resource_hub', 'manager')
        task_id (str): Associated task or operation identifier
        level (str): Log level - INFO, WARN, ERROR, DEBUG
        message (str): Human-readable message
        context (dict, optional): Additional metadata for debugging
    """
    overseer_url = os.getenv("OVERSEER_URL", "http://overseer:8004")
    secret = os.getenv("SHARED_SECRET", "mysecretapikey")

    headers = {
        "X-SHIVA-SECRET": secret,
        "Content-Type": "application/json"
    }

    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "service": service,
        "task_id": task_id,
        "level": level.upper(),
        "message": message,
        "context": context or {}
    }

    try:
        response = requests.post(
            f"{overseer_url}/log/event",
            headers=headers,
            data=json.dumps(payload),
            timeout=5
        )
        if response.status_code != 201:
            print(f"[LoggingClient] Overseer responded {response.status_code}: {response.text}")
        else:
            print(f"[LoggingClient] ✅ Logged: {service}:{level} → {message[:60]}")
    except requests.exceptions.RequestException as e:
        print(f"[LoggingClient] ❌ Failed to send log: {e}")


# ───────────────────────────────────────────────
# Simple console logger fallback (no Overseer)
# ───────────────────────────────────────────────

def local_log(level: str, message: str):
    """
    Lightweight local console logger for debugging inside containers.
    """
    print(f"[{level.upper()}] {message}")

# Backward compatibility alias for legacy imports
log_to_overseer = send_log
