"""
Overseer Service for SHIVA
- /log/event  (POST)  <- structured logs
- /control/kill (POST) -> set HALT or RESUME
- /control/status (GET) -> {status: "OK"/"HALT"}
- WebSocket endpoint: /ws/logs -> broadcast logs in real-time
- /logs (GET) -> query logs, filter by service/task_id
"""

import os
import time
import threading
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import httpx
import asyncio

# ============================================================
# SERVICE CONFIG
# ============================================================
API_KEY = os.getenv("SHARED_SECRET", "mysecretapikey")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8004))
SERVICE_NAME = os.getenv("SERVICE_NAME", "overseer")
AUTH_HEADER_NAME = "X-SHIVA-SECRET"

DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://127.0.0.1:8005")
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

app = FastAPI(title="SHIVA Overseer")

# ============================================================
# LOG STORE
# ============================================================
LOG_STORE = []
LOG_LOCK = threading.Lock()

# ============================================================
# WEBSOCKET MANAGER
# ============================================================
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, msg: dict):
        to_remove = []
        for ws in list(self.active):
            try:
                await ws.send_json(msg)
            except Exception:
                to_remove.append(ws)
        for ws in to_remove:
            self.disconnect(ws)

manager = ConnectionManager()

# ============================================================
# CONTROL STATE
# ============================================================
CONTROL_STATE = {"status": "OK", "updated_at": time.time(), "note": ""}

# ============================================================
# AUTH HELPER
# ============================================================
def _auth_ok(header_val: str | None):
    return header_val == API_KEY

# ============================================================
# DIRECTORY REGISTRATION + HEARTBEAT
# ============================================================
def register_self():
    """Registers this service with the Directory service."""
    while True:
        try:
            r = httpx.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": f"http://127.0.0.1:{SERVICE_PORT}",
                    "ttl_seconds": 60
                },
                headers=AUTH_HEADER,
                timeout=5
            )
            if r.status_code == 200:
                print(f"[Overseer] Registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                return
            else:
                print(f"[Overseer] Registration failed: {r.status_code}")
        except Exception as e:
            print(f"[Overseer] Directory unavailable. Retry in 5s. Error: {e}")
        time.sleep(5)


def heartbeat():
    """Periodic TTL refresh."""
    while True:
        time.sleep(45)
        try:
            httpx.post(
                f"{DIRECTORY_URL}/register",
                json={
                    "service_name": SERVICE_NAME,
                    "service_url": f"http://127.0.0.1:{SERVICE_PORT}",
                    "ttl_seconds": 60
                },
                headers=AUTH_HEADER,
                timeout=5
            )
            print("[Overseer] Heartbeat sent to Directory.")
        except Exception as e:
            print(f"[Overseer] Heartbeat failed: {e}. Restarting registration...")
            register_self()
            return

# Start registration on startup
@app.on_event("startup")
def startup_event():
    threading.Thread(target=register_self, daemon=True).start()

# ============================================================
# LOGGING ENDPOINTS
# ============================================================
class LogEvent(BaseModel):
    service: str
    task_id: str | None = None
    level: str
    message: str
    context: dict | None = {}

@app.post("/log/event")
async def log_event(payload: LogEvent, request: Request, x_shiva_secret: str | None = Header(None)):
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    entry = {
        "ts": time.time(),
        "service": payload.service,
        "task_id": payload.task_id,
        "level": payload.level,
        "message": payload.message,
        "context": payload.context or {}
    }

    with LOG_LOCK:
        LOG_STORE.append(entry)

    try:
        asyncio.create_task(manager.broadcast({"type": "log", "entry": entry}))
    except Exception:
        pass

    return JSONResponse(status_code=200, content={"status": "ok", "entry_count": len(LOG_STORE)})

@app.get("/logs")
async def get_logs(service: str | None = None, task_id: str | None = None, limit: int = 200, x_shiva_secret: str | None = Header(None)):
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    with LOG_LOCK:
        results = [e for e in reversed(LOG_STORE)
                   if (service is None or e["service"] == service)
                   and (task_id is None or e["task_id"] == task_id)]

    return {"count": len(results), "logs": results[:limit]}

# ============================================================
# CONTROL ENDPOINTS
# ============================================================
@app.post("/control/kill")
async def control_kill(payload: dict, x_shiva_secret: str | None = Header(None)):
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    action = payload.get("action", "").upper()
    note = payload.get("note", "")

    if action not in ("HALT", "RESUME"):
        raise HTTPException(status_code=400, detail="action must be HALT or RESUME")

    CONTROL_STATE["status"] = "HALT" if action == "HALT" else "OK"
    CONTROL_STATE["updated_at"] = time.time()
    CONTROL_STATE["note"] = note

    entry = {
        "ts": time.time(),
        "service": "overseer",
        "task_id": None,
        "level": "CONTROL",
        "message": f"Control action: {CONTROL_STATE['status']}",
        "context": {"note": note}
    }

    with LOG_LOCK:
        LOG_STORE.append(entry)

    try:
        asyncio.create_task(manager.broadcast({"type": "control", "state": CONTROL_STATE}))
    except Exception:
        pass

    return {"status": CONTROL_STATE["status"], "note": note}

@app.get("/control/status")
async def control_status(x_shiva_secret: str | None = Header(None)):
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return CONTROL_STATE

# ============================================================
# WEBSOCKET
# ============================================================
@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            msg = await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ============================================================
# HEALTH CHECK
# ============================================================
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print(f"Starting Overseer on 0.0.0.0:{SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
