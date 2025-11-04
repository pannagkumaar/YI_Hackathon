# 📄 overseer_service.py
from fastapi import FastAPI, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key # Import our new auth function

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Overseer Service",
    description="Observability, logging, and kill-switch for SHIVA.",
    dependencies=[Depends(get_api_key)] # Apply auth to all endpoints
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "overseer-service"
SERVICE_PORT = 8004
# --- End Authentication & Service Constants ---

# In-memory log storage
logs = []
# System status
status = {"system": "RUNNING"}


class LogEntry(BaseModel):
    service: str
    task_id: str
    level: str # e.g., INFO, ERROR, WARN
    message: str
    context: dict = {}

def register_self():
    """Registers this service with the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER) # Auth
            if r.status_code == 200:
                print(f"[Overseer] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Overseer] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[Overseer] Could not connect to Directory. Retrying in 5s...")
        time.sleep(5)

def heartbeat():
    """Sends a periodic heartbeat to the Directory to stay registered."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        time.sleep(45) # Send heartbeat before TTL (60s) expires
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER) # Auth
            print("[Overseer] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[Overseer] Failed to send heartbeat. Will retry registration.")
            register_self()
            break 

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

@app.post("/log/event", status_code=201)
def log_event(entry: LogEntry):
    """Receive and store a log event from another service."""
    log_data = entry.dict()
    print(f"[Overseer] Log Received from {entry.service} (Task: {entry.task_id}): {entry.message}")
    logs.append(log_data)
    return {"status": "Logged", "log_id": len(logs) - 1}

@app.get("/log/view", status_code=200)
def view_logs(limit: int = 50):
    """View the most recent logs."""
    return logs[-limit:]

@app.get("/control/status", status_code=200)
def get_status():
    """Get the global system status."""
    return {"status": status["system"]}

@app.post("/control/kill", status_code=200)
def kill_switch():
    """Activate the global kill-switch, halting all operations."""
    print("[Overseer] !!! KILL SWITCH ACTIVATED !!!")
    status["system"] = "HALT"
    return {"status": "HALT", "message": "System halt signal issued"}

@app.post("/control/resume", status_code=200)
def resume_system():
    """Resume system operations."""
    print("[Overseer] --- System Resumed ---")
    status["system"] = "RUNNING"
    return {"status": "RUNNING", "message": "System resume signal issued"}

if __name__ == "__main__":
    print("Starting Overseer Service on port 8004...")
    uvicorn.run(app, host="0.0.0.0", port=8004)