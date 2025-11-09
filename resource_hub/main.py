# app/main.py
import asyncio
import threading
import warnings
import logging
import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn
import requests
import os

from app.core.config import settings
from app.core.db import init_db, start_cleanup_thread
from app.core.discovery import start_heartbeat_loop
from app.core.logging_client import log_to_overseer

# Mock fallbacks (from their resource_hub_service.py)
MOCK_POLICIES = {
    "global": ["Disallow: delete", "Disallow: shutdown", "Disallow: rm -rf"]
}
MOCK_TOOLS = [
    {"name": "summarizer", "description": "Summarizes text", "handler": "summarizer"},
    {"name": "keyword_extractor", "description": "Extracts keywords", "handler": "keyword_extractor"},
    {"name": "sentiment_analyzer", "description": "Basic sentiment", "handler": "sentiment_analyzer"}
]

warnings.filterwarnings("ignore", message="`resume_download` is deprecated")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

app = FastAPI(title="SHIVA Hybrid Resource Hub", version="2.0")

# --- HEALTH CHECK ---
@app.get("/healthz", tags=["System"])
def healthcheck():
    return {"status": "ok", "message": "Hybrid Resource Hub active"}

# --- POLICY LIST ---
@app.get("/policy/list", tags=["Policies"])
def list_policies():
    try:
        from app.models.policy import Policy  # if real DB model exists
        # Placeholder: Replace with ORM or direct query
        # Example: return {"policies": [p.text for p in session.query(Policy).all()]}
        raise NotImplementedError  # to trigger fallback for now
    except Exception:
        log_to_overseer("resource_hub", "policy-fetch", "INFO", "Using MOCK policies fallback")
        return {"policies": MOCK_POLICIES["global"]}

# --- TOOL LIST ---
@app.get("/tools/list", tags=["Tools"])
def list_tools():
    try:
        # Placeholder for DB repo or dynamic tool registry
        raise NotImplementedError
    except Exception:
        log_to_overseer("resource_hub", "tool-fetch", "INFO", "Using MOCK tools fallback")
        return {"tools": MOCK_TOOLS}

# --- MEMORY ROUTES (Simplified Proxy) ---
@app.get("/memory/all", tags=["Memory"])
def list_memory():
    try:
        import sqlite3
        conn = sqlite3.connect(settings.DB_PATH)
        c = conn.cursor()
        c.execute("SELECT text, metadata, created_at FROM memory_entries")
        entries = [{"text": r[0], "metadata": r[1], "created_at": r[2]} for r in c.fetchall()]
        conn.close()
        return entries
    except Exception:
        return []

@app.post("/memory/add", tags=["Memory"])
def add_memory(entry: dict):
    text = entry.get("text", "")
    meta = entry.get("metadata", {})
    if not text:
        raise HTTPException(400, "Missing text field")
    try:
        import sqlite3
        conn = sqlite3.connect(settings.DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO memory_entries (text, metadata, created_at) VALUES (?, ?, ?)",
                  (text, str(meta), datetime.datetime.utcnow().timestamp()))
        conn.commit()
        conn.close()
        log_to_overseer("resource_hub", "memory-add", "INFO", f"Stored memory: {text[:30]}")
        return {"status": "Memory added"}
    except Exception as e:
        log_to_overseer("resource_hub", "memory-add", "ERROR", f"DB write failed: {e}")
        raise HTTPException(500, "Memory insert failed")

# --- RAG QUERY (Hybrid) ---
@app.post("/rag/query", tags=["RAG"])
def rag_query(payload: dict):
    """
    Hybrid RAG query: fetches results either from embeddings (if available)
    or falls back to simple keyword-based matching against mock data.
    """
    question = payload.get("question", "")
    if not question:
        raise HTTPException(400, "Missing 'question' field")

    # Log the query for traceability
    log_to_overseer("resource_hub", "rag-query", "INFO", f"Received RAG query: {question}")

    try:
        # Try real semantic retrieval first (if chroma is available)
        from app.services.rag_auto_populator import query_knowledge_base
        answer, sources = query_knowledge_base(question)
        if answer:
            log_to_overseer("resource_hub", "rag-query", "INFO", f"RAG (semantic) answer: {answer[:60]}")
            return {"answer": answer, "sources": sources}
    except Exception as e:
        print(f"[RAG] Semantic query fallback: {e}")

    # Fallback: mock behavior (like theirs)
    matches = [t for t in MOCK_TOOLS if t["name"] in question.lower()]
    if matches:
        answer = f"Tool found: {matches[0]['name']}"
        log_to_overseer("resource_hub", "rag-query", "INFO", f"RAG (mock) matched {matches[0]['name']}")
        return {"answer": answer, "sources": [m['name'] for m in matches]}

    log_to_overseer("resource_hub", "rag-query", "WARN", "No relevant info found")
    return {"answer": "No relevant info found.", "sources": []}

# --- BACKGROUND TASKS ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing DB...")
    try:
        init_db()
        start_cleanup_thread()
    except Exception as e:
        print(f"[HybridHub] DB init failed: {e}")

    # Heartbeat to Directory
    asyncio.create_task(start_heartbeat_loop())

    log_to_overseer("resource_hub", "startup", "INFO", "Hybrid Resource Hub online")

    try:
        yield
    finally:
        print("Shutting down...")
        log_to_overseer("resource_hub", "shutdown", "INFO", "Service shutting down")

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.getenv("SERVICE_PORT", "8006"))
    print(f"Starting Hybrid Resource Hub on http://0.0.0.0:{port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
