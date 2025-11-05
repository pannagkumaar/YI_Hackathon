# 📄 overseer_service.py
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
import json
from typing import List

from security import get_api_key

# --- Authentication & Service Constants ---

# REMOVED: dependencies=[Depends(get_api_key)] from here
app = FastAPI(
    title="Overseer Service",
    description="Observability, logging, and kill-switch for SHIVA."
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


# --- WebSocket Connection Manager (No change) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                self.active_connections.remove(connection)

manager = ConnectionManager()
# --- END: WebSocket Connection Manager ---


class LogEntry(BaseModel):
    service: str
    task_id: str
    level: str
    message: str
    context: dict = {}

# --- Service Registration (No changes) ---
def register_self():
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            if r.status_code == 200:
                print(f"[Overseer] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[Overseer] Failed to register. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[Overseer] Could not connect to Directory. Retrying in 5s...")
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            print("[Overseer] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[Overseer] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---


# --- API Endpoints (UPDATED) ---

# NEW: Serve the HTML Dashboard (No dependency)
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("overseer_dashboard.html", "r") as f:
        return HTMLResponse(content=f.read())

# NEW: WebSocket endpoint (No dependency)
@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("[Overseer] Client disconnected from WebSocket.")


# UPDATED: All other endpoints NOW individually require auth
@app.post("/log/event", status_code=201)
async def log_event(entry: LogEntry, api_key: str = Depends(get_api_key)):
    log_data = entry.dict()
    print(f"[Overseer] Log Received from {entry.service} (Task: {entry.task_id}): {entry.message}")
    logs.append(log_data)
    
    await manager.broadcast(json.dumps(log_data))
    
    return {"status": "Logged", "log_id": len(logs) - 1}

@app.get("/log/view", status_code=200)
def view_logs(limit: int = 50, api_key: str = Depends(get_api_key)):
    return logs[-limit:]

@app.get("/control/status", status_code=200)
def get_status(api_key: str = Depends(get_api_key)):
    return {"status": status["system"]}

@app.post("/control/kill", status_code=200)
def kill_switch(api_key: str = Depends(get_api_key)):
    print("[Overseer] !!! KILL SWITCH ACTIVATED !!!")
    status["system"] = "HALT"
    return {"status": "HALT", "message": "System halt signal issued"}

@app.post("/control/resume", status_code=200)
def resume_system(api_key: str = Depends(get_api_key)):
    print("[Overseer] --- System Resumed ---")
    status["system"] = "RUNNING"
    return {"status": "RUNNING", "message": "System resume signal issued"}

if __name__ == "__main__":
    print(f"Starting Overseer Service on port {SERVICE_PORT}...")
    print(f"Access the live dashboard at http://localhost:{SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)