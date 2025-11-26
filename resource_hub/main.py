# resource_hub/main.py
"""
SHIVA Resource Hub (The Armory)
- Central tool registry
- Tool execution sandbox
- Memory (short + long term)
- RAG services
- ITSM mock service
- Overseer logging + Directory heartbeat
"""

import asyncio
import logging
import warnings
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
import uvicorn
from dotenv import load_dotenv

# app/core
from app.core.config import settings
from app.core.db import init_db, start_cleanup_thread
from app.core.discovery import start_heartbeat_loop

# logging client (use app.core.* path to be consistent)
from core.logging_client import send_log

# Routers
from app.routers.tools_router import router as tools_router
from app.routers.memory_router import router as memory_router
from app.routers.long_memory_router import router as long_memory_router
from app.routers.rag_router import router as rag_router
from app.routers.policy_router import router as policy_router
from app.routers.itsm_router import router as itsm_router

# Memory helpers (you noted these live at resource_hub/memory)
# Keep imports as-is — used only for optional stats endpoint below
try:
    from memory.short_term import get_short_term_stats  # optional helper if implemented
except Exception:
    get_short_term_stats = None

try:
    from memory.long_term import get_long_term_stats  # optional helper if implemented
except Exception:
    get_long_term_stats = None


# Load .env and .env.local (if present)
load_dotenv()
if os.path.exists(".env.local"):
    load_dotenv(".env.local")

warnings.filterwarnings("ignore", message="`resume_download` is deprecated")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

app = FastAPI(
    title="SHIVA Resource Hub",
    version="3.0",
    description="Central Armory: tools, memory, RAG, ITSM"
)

# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------
@app.get("/healthz", tags=["System"])
def healthcheck():
    return {"status": "ok", "service": "resource_hub"}


# ---------------------------------------------------------
# Small memory stats endpoint (UI expects /memory/stats)
# - best-effort: call optional helpers if present, otherwise return 0s
# ---------------------------------------------------------
@app.get("/memory/stats", tags=["System"])
def memory_stats(x_shiva_secret: str | None = Header(None, alias="X-SHIVA-SECRET")):
    # minimal auth for UI; don't raise if header absent in dev mode
    if settings.SHARED_SECRET and x_shiva_secret != settings.SHARED_SECRET:
        # keep this endpoint permissive in local dev; if you want strict, raise
        # raise HTTPException(401, "Unauthorized")
        pass

    short_count = 0
    long_count = 0
    last_updated = 0

    try:
        if callable(get_short_term_stats):
            s = get_short_term_stats()
            short_count = int(s.get("count", 0))
            last_updated = s.get("last_updated", last_updated) or last_updated
    except Exception:
        short_count = short_count

    try:
        if callable(get_long_term_stats):
            l = get_long_term_stats()
            long_count = int(l.get("count", 0))
            last_updated = l.get("last_updated", last_updated) or last_updated
    except Exception:
        long_count = long_count

    return {"short_term_count": short_count, "long_term_count": long_count, "last_updated": last_updated}


# ---------------------------------------------------------
# Startup & Shutdown Lifecycle
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing Resource Hub DB...")

    try:
        init_db()
        start_cleanup_thread()
    except Exception as e:
        print(f"[ResourceHub] DB init failed: {e}")

    # Directory heartbeat loop (shared discovery model)
    # start_heartbeat_loop is expected to handle registration/heartbeat with Directory
    try:
        asyncio.create_task(start_heartbeat_loop())
    except Exception as e:
        print(f"[ResourceHub] Failed to start heartbeat loop: {e}")

    # startup log
    try:
        send_log("resource_hub", "startup", "INFO", "Resource Hub online")
    except Exception:
        # don't fail startup if overseer not available
        pass

    try:
        yield
    finally:
        print("Shutting down Resource Hub...")
        try:
            send_log("resource_hub", "shutdown", "INFO", "Service shutting down")
        except Exception:
            pass


app.router.lifespan_context = lifespan


# ---------------------------------------------------------
# Router Registration
# - Use routers; DO NOT duplicate endpoints here to avoid collisions.
# ---------------------------------------------------------
app.include_router(tools_router)         # /tools/list, /tools/execute
app.include_router(memory_router)       # /memory/short-term
app.include_router(long_memory_router)  # /memory/long-term
app.include_router(rag_router)          # /rag/*
app.include_router(policy_router)       # /policy/*
app.include_router(itsm_router)         # /mock_itsm/*


# ---------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("SERVICE_PORT", str(settings.SERVICE_PORT)))
    host = "0.0.0.0"
    print(f"Starting Resource Hub on http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port)
