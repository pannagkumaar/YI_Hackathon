import warnings
import logging
warnings.filterwarnings("ignore", message="`resume_download` is deprecated")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
import asyncio
import uvicorn
from app.core.config import settings
from app.core.config import settings
from app.core.db import init_db, start_cleanup_thread
from app.core.discovery import start_heartbeat_loop
from app.services.rag_auto_populator import start_autorag_thread, start_policy_thread

# --- Integration Imports ---
# Import all existing and new routers
from app.routers import (
    tools_router, 
    memory_router, 
    itsm_router, 
    demo_router,
    long_memory_router, 
    rag_router,
    policy_router  # <-- 1. ADDED: Import the new policy router
)

# Import the unified security dependency
# (Assumes security.py is copied to app/core/security.py)
try:
    from app.core.security import get_api_key
except ImportError:
    print("FATAL: security.py not found in app/core/. Please copy it from the project root.")
    # Define a dummy fallback to allow the server to start, but auth will fail
    def get_api_key():
        raise HTTPException(status_code=500, detail="Auth dependency not configured")
# --- End Integration Imports ---


# --- Integration Fix ---
# 2. ADDED: Global dependency for authentication
# This secures all routes in all included routers
app = FastAPI(
    title="SHIVA Resource Hub", 
    version="1.0",
    dependencies=[Depends(get_api_key)]
)

# --- 3. INCLUDE ROUTERS (with new policy_router) ---
app.include_router(policy_router.router)
app.include_router(tools_router.router)
app.include_router(memory_router.router)
app.include_router(itsm_router.router)
app.include_router(demo_router.router)
app.include_router(long_memory_router.router)
app.include_router(rag_router.router)
# --- End Include Routers ---

# --- Health Check Endpoint ---
@app.get("/healthz", tags=["System"])
def healthcheck():
    """Simple health-check endpoint for monitoring."""
    return {"status": "ok", "message": "Resource Hub is alive"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing database...")
    init_db()
    print("Starting background cleanup thread...")
    start_cleanup_thread()

    # Start auto-RAG populator thread
    await asyncio.sleep(5)  # Give app time to start listening
    start_autorag_thread()
    await asyncio.sleep(2)
    start_policy_thread()

    # Start a background heartbeat if directory url is configured
    hb_task = None
    if settings.DIRECTORY_URL:
        print(f"Starting heartbeat task to Directory: {settings.DIRECTORY_URL}")
        hb_task = asyncio.create_task(start_heartbeat_loop())
    else:
        print("WARNING: DIRECTORY_URL not set. Service will not be discoverable.")
        
    try:
        yield
    finally:
        # This code runs on server shutdown
        print("Shutting down...")
        if hb_task:
            print("Cancelling heartbeat task...")
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                print("Heartbeat task successfully cancelled.")

# Assign the lifespan event handler to the app
app.router.lifespan_context = lifespan

# --- Integration Fix ---
# 4. ADDED: Main run block
if __name__ == "__main__":
    # Get port from settings, default to 8000
    try:
        port = int(settings.SERVICE_BASE_URL.split(':')[-1])
    except Exception:
        port = SERVICE_PORT = 8006
        
    print(f"Starting SHIVA Resource Hub on http://0.0.0.0:{port}...")
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=True  # reload=True is great for development
    )