# overseer_service.py
"""
Overseer service for SHIVA
- Receives logs via POST /log/event
- Broadcasts logs to connected WebSocket clients at /ws/logs
- Provides UI proxy endpoints: /ui/tasks, /ui/approve_task/{id}, /ui/replan_task/{id}
- Services health aggregator: /services/healthz
- Small memory stats proxy: /memory/stats (best-effort)
"""

import asyncio
import json
import os
import time
from typing import Dict, Any, List

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

SHARED_SECRET = os.getenv("SHARED_SECRET", "mysecretapikey")
AUTH_HEADER = {"X-SHIVA-SECRET": SHARED_SECRET}
DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005").rstrip("/")

SERVICE_NAME = "overseer"
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8004))
SERVICE_URL = f"http://127.0.0.1:{SERVICE_PORT}"

# store last N logs
MAX_LOGS = int(os.getenv("OVERSEER_MAX_LOGS", 800))
logs: List[Dict[str, Any]] = []

# connected websockets
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active:
                self.active.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        # send to all clients, drop dead connections
        text = json.dumps(message, default=str)
        async with self.lock:
            to_remove = []
            for ws in list(self.active):
                try:
                    await ws.send_text(text)
                except Exception:
                    to_remove.append(ws)
            for r in to_remove:
                if r in self.active:
                    self.active.remove(r)

manager = ConnectionManager()

app = FastAPI(title="SHIVA Overseer")

# helper to persist log
def push_log(entry: Dict[str, Any]):
    if not isinstance(entry, dict):
        return
    entry.setdefault("ts", time.time())
    logs.append(entry.copy())
    if len(logs) > MAX_LOGS:
        # remove oldest
        del logs[0]

async def discover(service_name: str) -> str:
    """
    Resolve service URL from Directory.

    Returns full base url (no trailing slash).
    """
    async with httpx.AsyncClient(timeout=4) as client:
        r = await client.get(f"{DIRECTORY_URL}/discover", params={"service_name": service_name}, headers=AUTH_HEADER, timeout=4)
        r.raise_for_status()
        return r.json()["url"].rstrip("/")

# -------- Log ingestion endpoint (services call this) --------
@app.post("/log/event")
async def receive_log(payload: Dict[str, Any], request: Request):
    """
    Expects JSON:
    {
      "service": "manager",
      "task_id": "...",
      "level": "INFO|WARN|ERROR",
      "message": "text",
      "context": {...} (optional)
    }
    """
    # best-effort auth: check header X-SHIVA-SECRET
    header = request.headers.get("x-shiva-secret") or request.headers.get("X-SHIVA-SECRET")
    if header != SHARED_SECRET:
        raise HTTPException(401, "unauthorized")

    entry = {
        "service": payload.get("service", "unknown"),
        "task_id": payload.get("task_id"),
        "level": payload.get("level", "INFO"),
        "message": payload.get("message", ""),
        "context": payload.get("context", {}),
        "ts": time.time()
    }
    push_log(entry)

    # broadcast asynchronously (don't await blocking the caller)
    asyncio.create_task(manager.broadcast(entry))
    return {"status": "ok"}

# -------- WebSocket for UI clients --------
@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    await manager.connect(ws)
    try:
        # On connect, send last 40 logs
        for e in logs[-40:]:
            await ws.send_text(json.dumps(e, default=str))

        # Heartbeat loop: UI never sends messages, so WE must keep socket alive
        while True:
            await asyncio.sleep(30)
            try:
                await ws.send_text(json.dumps({"type": "ping", "ts": time.time()}))
            except Exception:
                break

    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:
        await manager.disconnect(ws)


# -------- UI proxy endpoints --------
@app.get("/ui/tasks")
async def ui_tasks():
    """
    Proxy to manager /tasks/list
    """
    try:
        manager_url = await discover("manager")
    except Exception as e:
        raise HTTPException(500, f"directory discovery failed: {e}")

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            r = await client.get(f"{manager_url}/tasks/list", headers=AUTH_HEADER, timeout=6)
            r.raise_for_status()
            return JSONResponse(r.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"manager error: {e.response.text}")
        except Exception as e:
            raise HTTPException(500, f"could not fetch tasks: {e}")

@app.post("/ui/approve_task/{task_id}")
async def ui_approve_task(task_id: str):
    """
    Proxy to manager /task/{task_id}/approve
    """
    try:
        manager_url = await discover("manager")
    except Exception as e:
        raise HTTPException(500, f"directory discovery failed: {e}")

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            r = await client.post(f"{manager_url}/task/{task_id}/approve", headers=AUTH_HEADER, timeout=6)
            r.raise_for_status()
            return JSONResponse(r.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"manager error: {e.response.text}")
        except Exception as e:
            raise HTTPException(500, f"approve failed: {e}")

@app.post("/ui/replan_task/{task_id}")
async def ui_replan_task(task_id: str, body: Dict[str, Any]):
    """
    Proxy to manager replan endpoint:
    Body: { "goal": "...", "context": {...} }
    """
    try:
        manager_url = await discover("manager")
    except Exception as e:
        raise HTTPException(500, f"directory discovery failed: {e}")

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(f"{manager_url}/task/{task_id}/replan", headers={**AUTH_HEADER, "Content-Type": "application/json"}, json=body, timeout=8)
            r.raise_for_status()
            return JSONResponse(r.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"manager error: {e.response.text}")
        except Exception as e:
            raise HTTPException(500, f"replan failed: {e}")

# -------- Memory stats (best-effort) --------
@app.get("/memory/stats")
async def memory_stats():
    """
    Tries to fetch /memory/stats from resource_hub, falls back to counts in logs.
    """
    try:
        hub = await discover("resource_hub")
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{hub}/memory/stats", headers=AUTH_HEADER, timeout=4)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass

    # fallback: provide minimal counts calculated from logs (best-effort)
    short_count = sum(1 for l in logs if l.get("service") == "resource_hub")
    return {"short_term_count": short_count, "long_term_count": 0, "last_updated": time.time()}

# -------- Services health aggregator --------
@app.get("/services/healthz")
async def services_health():
    """
    Query a set of core services for their /healthz endpoints.
    Returns { service_name: {"ok": bool, "url": "...", "status": (json or text)} }
    """
    services = ["manager", "partner", "guardian", "resource_hub", "directory", "overseer"]
    results = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for s in services:
            try:
                if s == "directory":
                    url = DIRECTORY_URL
                elif s == "overseer":
                    url = SERVICE_URL
                else:
                    # try directory discovery for each service
                    try:
                        url = (await discover(s))
                    except Exception:
                        # fallback to common local host names
                        url = f"http://{s}:8000"
                # prefer /healthz
                try:
                    r = await client.get(f"{url}/healthz", headers=AUTH_HEADER, timeout=2)
                    if r.status_code == 200:
                        results[s] = {"ok": True, "url": url, "status": r.json()}
                    else:
                        results[s] = {"ok": False, "url": url, "status": r.text}
                except Exception as e:
                    results[s] = {"ok": False, "url": url, "status": str(e)}
            except Exception as e:
                results[s] = {"ok": False, "url": None, "status": str(e)}
    return results

# -------- UI: simple last-50 logs endpoint --------
@app.get("/ui/logs")
async def ui_logs(limit: int = 50):
    recent = list(logs[-limit:])
    return {"logs": recent}

@app.get("/logs")
async def logs_alias(limit: int = 50):
    """
    Alias so test_shiva.py can retrieve last logs using /logs
    """
    recent = list(logs[-limit:])
    return {"logs": recent}

# -------- root health --------
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

if __name__ == "__main__":
    print(f"Starting Overseer on 0.0.0.0:{SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT, log_level="info")
