# overseer_service.py
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import requests
import httpx
import threading
import time
import json
from datetime import datetime
from typing import List, Dict, Any

from security import get_api_key

# --- Authentication & Service Constants ---
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

# In-memory logs & status
logs: List[Dict[str, Any]] = []
status: Dict[str, str] = {"system": "RUNNING"}

# --- WebSocket connection manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: str):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                try:
                    self.active_connections.remove(connection)
                except Exception:
                    pass

manager = ConnectionManager()

# --- Pydantic models for API ---
class LogEntry(BaseModel):
    service: str
    task_id: str
    level: str
    message: str
    context: dict = {}

class ReplanRequest(BaseModel):
    goal: str
    context: dict = {}

# --- Service registration & heartbeat ---
def register_self():
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER, timeout=3)
            if r.status_code == 200:
                print(f"[Overseer] Registered with Directory")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print("[Overseer] Register failed, retrying in 5s")
        except requests.exceptions.RequestException:
            print("[Overseer] Directory unavailable, retrying in 5s")
        time.sleep(5)

def heartbeat():
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": f"http://localhost:{SERVICE_PORT}",
                "ttl_seconds": 60
            }, headers=AUTH_HEADER, timeout=3)
        except requests.exceptions.RequestException:
            print("[Overseer] Heartbeat failed, re-registering")
            register_self()
            break

@app.lifespan("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()

# --- UI and WebSocket endpoints (no auth for UI access) ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("overseer_dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # keep connection alive - client sends ping messages; server doesn't expect content
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(websocket)

# --- UI proxy helpers (no auth) ---
async def discover_manager() -> str:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{DIRECTORY_URL}/discover", params={"service_name": "manager-service"}, headers=AUTH_HEADER)
            r.raise_for_status()
            return r.json()["url"]
        except Exception as e:
            print(f"[Overseer] Discover manager failed: {e}")
            raise HTTPException(status_code=500, detail="Could not discover Manager")

@app.get("/ui/tasks", status_code=200)
async def get_ui_tasks():
    try:
        manager_url = await discover_manager()
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{manager_url}/tasks/list", headers=AUTH_HEADER)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/ui/ambiguous", status_code=200)
async def ui_get_ambiguous():
    ambiguous_items = []
    # scan recent logs (newest first)
    for entry in reversed(logs[-2000:]):
        try:
            ctx = entry.get("context", {}) if isinstance(entry, dict) else {}
            msg = entry.get("message", "") if isinstance(entry, dict) else str(entry)
            svc = entry.get("service", "unknown")
            is_amb = (ctx.get("decision") == "Ambiguous") or ("ambig" in (msg or "").lower()) or (ctx.get("requires_human_review") is True)
            if is_amb:
                ambiguous_items.append({
                    "service": svc,
                    "task_id": entry.get("task_id", "N/A"),
                    "message": msg,
                    "context": ctx,
                    "timestamp": entry.get("timestamp", datetime.utcnow().isoformat() + "Z"),
                    "first_seen": entry.get("timestamp", datetime.utcnow().isoformat() + "Z")
                })
        except Exception:
            continue
    return {"ambiguous": ambiguous_items}

@app.post("/ui/resolve_ambiguous/{task_id}", status_code=200)
async def ui_resolve_ambiguous(task_id: str, payload: dict):
    decision = str(payload.get("decision", "Dismiss"))
    approved_by = payload.get("approved_by", "operator")
    note = payload.get("note", "")
    timestamp = datetime.utcnow().isoformat() + "Z"

    audit = {
        "service": "overseer-service",
        "task_id": task_id,
        "level": "INFO",
        "message": f"Human decision recorded: {decision} by {approved_by} {note}",
        "context": {"decision": decision, "approved_by": approved_by, "note": note},
        "timestamp": timestamp
    }
    logs.append(audit)
    try:
        await manager.broadcast(json.dumps(audit))
    except Exception:
        pass

    # If Allow, try to resume via Manager
    if decision.lower() == "allow":
        try:
            manager_url = await discover_manager()
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{manager_url}/task/{task_id}/approve", headers=AUTH_HEADER)
                try:
                    body = await r.aread()
                    body = body.decode(errors="ignore")
                except Exception:
                    body = ""
                return {"status": "ok", "manager_call_status": r.status_code, "manager_response": body}
        except Exception as e:
            return {"status": "ok", "manager_call_status": "failed", "error": str(e)}

    return {"status": "ok"}

@app.post("/ui/approve_task/{task_id}", status_code=202)
async def approve_ui_task(task_id: str):
    try:
        manager_url = await discover_manager()
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{manager_url}/task/{task_id}/approve", headers=AUTH_HEADER)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e)}

@app.post("/ui/replan_task/{task_id}", status_code=202)
async def replan_ui_task(task_id: str, request: ReplanRequest):
    try:
        manager_url = await discover_manager()
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{manager_url}/task/{task_id}/replan", json=request.dict(), headers=AUTH_HEADER)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e)}

# --- Internal secure endpoints (require API key) ---
@app.post("/log/event", status_code=201)
async def log_event(entry: LogEntry, api_key: str = Depends(get_api_key)):
    log_data = entry.dict()
    log_data["timestamp"] = datetime.utcnow().isoformat() + "Z"
    print(f"[Overseer] Log from {entry.service} (Task {entry.task_id}): {entry.message}")
    logs.append(log_data)
    # Broadcast to websocket clients
    try:
        await manager.broadcast(json.dumps(log_data))
    except Exception as e:
        print(f"[Overseer] Broadcast failed: {e}")
    return {"status": "Logged", "log_id": len(logs) - 1}

@app.get("/log/view", status_code=200)
def view_logs(limit: int = 50, api_key: str = Depends(get_api_key)):
    return logs[-limit:]

@app.get("/control/status", status_code=200)
def get_status(api_key: str = Depends(get_api_key)):
    return {"status": status["system"]}

@app.post("/control/kill", status_code=200)
def kill_switch(api_key: str = Depends(get_api_key)):
    print("[Overseer] KILL SWITCH ACTIVATED")
    status["system"] = "HALT"
    # broadcast a log entry for visibility
    entry = {"service": "overseer-service", "task_id": "N/A", "level": "WARN", "message": "KILL SWITCH issued", "context": {}, "timestamp": datetime.utcnow().isoformat() + "Z"}
    logs.append(entry)
    try:
        # best-effort synchronous notify to Dashboard clients via websocket manager
        import asyncio
        asyncio.get_event_loop().create_task(manager.broadcast(json.dumps(entry)))
    except Exception:
        pass
    return {"status": "HALT", "message": "System halt signal issued"}

@app.post("/control/resume", status_code=200)
def resume_system(api_key: str = Depends(get_api_key)):
    print("[Overseer] System resumed")
    status["system"] = "RUNNING"
    entry = {"service": "overseer-service", "task_id": "N/A", "level": "INFO", "message": "System resumed", "context": {}, "timestamp": datetime.utcnow().isoformat() + "Z"}
    logs.append(entry)
    try:
        import asyncio
        asyncio.get_event_loop().create_task(manager.broadcast(json.dumps(entry)))
    except Exception:
        pass
    return {"status": "RUNNING", "message": "System resume signal issued"}

if __name__ == "__main__":
    print(f"Starting Overseer Service on port {SERVICE_PORT}...")
    print(f"Open dashboard at http://localhost:{SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
