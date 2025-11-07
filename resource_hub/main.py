from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
from app.core.config import settings
from app.core.db import init_db, start_cleanup_thread
from app.routers import tools_router, memory_router, itsm_router, demo_router
from app.core.discovery import start_heartbeat_loop
from app.routers import long_memory_router, rag_router


app = FastAPI(title="SHIVA Resource Hub", version="1.0")

# include routers
app.include_router(tools_router.router)
app.include_router(memory_router.router)
app.include_router(itsm_router.router)
app.include_router(demo_router.router)
app.include_router(long_memory_router.router)
app.include_router(rag_router.router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    init_db()
    start_cleanup_thread()
    # start a background heartbeat if directory url is configured
    hb_task = None
    if settings.DIRECTORY_URL:
        hb_task = asyncio.create_task(start_heartbeat_loop())
    try:
        yield
    finally:
        # shutdown: cancel heartbeat
        if hb_task:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass

app.router.lifespan_context = lifespan
