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

from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn

from app.core.config import settings
from app.core.db import init_db, start_cleanup_thread
from app.core.discovery import start_heartbeat_loop
from core.logging_client import send_log

# Routers
from app.routers.tools_router import router as tools_router
from app.routers.memory_router import router as memory_router
from app.routers.long_memory_router import router as long_memory_router
from app.routers.rag_router import router as rag_router
from app.routers.policy_router import router as policy_router
from app.routers.itsm_router import router as itsm_router
from dotenv import load_dotenv

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

    # Directory heartbeat loop
    asyncio.create_task(start_heartbeat_loop())

    send_log("resource_hub", "startup", "INFO", "Resource Hub online")
    try:
        yield
    finally:
        print("Shutting down Resource Hub...")
        send_log("resource_hub", "shutdown", "INFO", "Service shutting down")

app.router.lifespan_context = lifespan


# ---------------------------------------------------------
# Router Registration
# ---------------------------------------------------------
app.include_router(tools_router)         # /tools/list, /tools/execute
app.include_router(memory_router)        # /memory/short-term
app.include_router(long_memory_router)   # /memory/long-term
app.include_router(rag_router)           # /rag/*
app.include_router(policy_router)        # /policy/*
app.include_router(itsm_router)          # /mock_itsm/*


# ---------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("SERVICE_PORT", "8006"))
    print(f"Starting Resource Hub on http://0.0.0.0:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port)
