# directory_service.py
"""
Simple Directory / Service Registry for SHIVA
Provides:
 - POST /register  { service_name, service_url, ttl_seconds }
 - POST /deregister { service_name }
 - GET  /discover?service_name=<name>
Auth: X-SHIVA-SECRET header
"""

import time
import threading
import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, AnyUrl
from fastapi.responses import JSONResponse
import uvicorn

API_KEY = os.getenv("SHIVA_SECRET", os.getenv("SHARED_SECRET", "mysecretapikey"))
DEFAULT_TTL = int(os.getenv("DIRECTORY_DEFAULT_TTL", "60"))
CLEANUP_INTERVAL = int(os.getenv("DIRECTORY_CLEANUP_INTERVAL", "10"))
SERVICE_PORT = int(os.getenv("SERVICE_PORT", 8005))
SERVICE_NAME = os.getenv("SERVICE_NAME", "directory")

app = FastAPI(title="SHIVA Directory Service")

# In-memory registry:
# services = { "<service_name>": { "url": "http://...", "expires_at": <epoch> } }
services = {}
services_lock = threading.Lock()


class RegisterPayload(BaseModel):
    service_name: str
    service_url: AnyUrl
    ttl_seconds: Optional[int] = DEFAULT_TTL


class DeregisterPayload(BaseModel):
    service_name: str


def _now() -> float:
    return time.time()


def _cleaner():
    """Background thread: remove expired services periodically."""
    while True:
        time.sleep(CLEANUP_INTERVAL)
        removed = []
        with services_lock:
            now = _now()
            for name in list(services.keys()):
                if services[name]["expires_at"] <= now:
                    removed.append(name)
                    del services[name]
        if removed:
            print(f"[Directory] cleaned expired services: {removed}")


@app.on_event("startup")
def start_cleanup():
    t = threading.Thread(target=_cleaner, daemon=True)
    t.start()


def _auth_ok(x_shiva_secret: str):
    return x_shiva_secret == API_KEY


@app.post("/register")
async def register(payload: RegisterPayload, request: Request, x_shiva_secret: str = Header(None)):
    """Register or refresh a service entry."""
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    name = payload.service_name.strip()
    url = str(payload.service_url).rstrip("/")
    ttl = int(payload.ttl_seconds or DEFAULT_TTL)
    expires_at = _now() + ttl

    with services_lock:
        services[name] = {"url": url, "expires_at": expires_at}

    print(f"[Directory] registered {name} -> {url} (ttl={ttl}s)")
    return JSONResponse(status_code=200, content={"service": name, "url": url, "status": "ok", "expires_at": expires_at})


@app.post("/deregister")
async def deregister(payload: DeregisterPayload, request: Request, x_shiva_secret: str = Header(None)):
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    name = payload.service_name.strip()
    with services_lock:
        if name in services:
            del services[name]
            print(f"[Directory] deregistered {name}")
            return JSONResponse(status_code=200, content={"service": name, "status": "deregistered"})
        else:
            return JSONResponse(status_code=404, content={"service": name, "status": "not_found"})


@app.get("/discover")
async def discover(service_name: str, x_shiva_secret: str = Header(None)):
    """
    Discover must be callable like:
      GET /discover?service_name=guardian
    Returns:
      200 {"service": "<name>", "url": "http://..."}
      404 {"error": true, "message": "..."}
    """
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Accept different variants (exact, with/without -service)
    variants = [
        service_name,
        f"{service_name}-service",
        service_name.replace("_", "-"),
        service_name.replace("-", "_"),
    ]

    now = _now()
    with services_lock:
        for name in variants:
            entry = services.get(name)
            if entry and entry.get("expires_at", 0) > now:
                return JSONResponse(status_code=200, content={"service": name, "url": entry["url"]})

    return JSONResponse(status_code=404, content={"error": True, "message": f"Service '{service_name}' not found"})


@app.get("/list")
async def list_services(x_shiva_secret: str = Header(None)):
    if not _auth_ok(x_shiva_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    now = _now()
    with services_lock:
        out = {k: {"url": v["url"], "expires_at": v["expires_at"], "healthy": v["expires_at"] > now} for k, v in services.items()}
    return {"services": out}

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "directory"}



if __name__ == "__main__":
    print(f"Starting Directory on 0.0.0.0:{SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
