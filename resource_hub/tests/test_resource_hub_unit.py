# resource_hub/tests/test_resource_hub_unit.py
import os
import time
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from main import app

# ------------------------------
# Setup test client & constants
# ------------------------------
client = TestClient(app)
HEADERS = {"X-SHIVA-SECRET": settings.SHIVA_SHARED_SECRET}

# ------------------------------
# Health checks
# ------------------------------

def test_health_rag():
    """Ensure the RAG health endpoint works and Chroma initializes."""
    r = client.get("/health/rag")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] in ["ok", "not_ready"]

def test_memory_stats():
    """Verify /memory/stats returns correct structure."""
    r = client.get("/memory/stats", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert "short_term_count" in data
    assert "long_term_count" in data
    assert isinstance(data["short_term_count"], int)
    assert isinstance(data["long_term_count"], int)

# ------------------------------
# Memory recall & storage
# ------------------------------

def test_contextual_recall_compose(monkeypatch):
    """Ensure contextual recall returns results and optional Gemini summary."""

    def mock_recall(task_id, text, k=3):
        return [{"text": "Sample context A", "metadata": {"source": "test"}}]

    def mock_ask(prompt, max_output_tokens=256):
        return "Mock summary generated."

    monkeypatch.setattr("app.services.rag_service.recall", mock_recall)
    monkeypatch.setattr("app.core.gemini_client.ask_gemini", mock_ask)

    body = {"task_id": "t1", "text": "test recall", "k": 1, "compose": True}
    r = client.post("/memory/contextual-recall", headers=HEADERS, json=body)
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    assert "summary" in data
    assert data["summary"].startswith("Mock")

def test_contextual_recall_unauthorized():
    """Ensure unauthorized access is rejected."""
    r = client.post("/memory/contextual-recall", json={"task_id": "t1", "text": "x"})
    assert r.status_code == 401

# ------------------------------
# Embeddings
# ------------------------------

def test_embeddings_consistency(monkeypatch):
    """Embedding same text twice should yield similar vectors."""
    from app.core.embeddings import embed_text
    v1 = embed_text("sample text")
    v2 = embed_text("sample text")
    # Cosine similarity
    import numpy as np
    cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    assert cos > 0.99

# ------------------------------
# Tools endpoint
# ------------------------------

def test_tool_list_execute(monkeypatch):
    """Ensure tools list and execute endpoints work."""

    # Mock tool execution to return deterministic result
    def mock_execute_tool(task_id, tool, params):
        return {"tool": tool, "output": "success"}

    monkeypatch.setattr("app.services.tool_service.execute_tool", mock_execute_tool, raising=False)

    # list
    r = client.get("/tools/list", headers=HEADERS)
    assert r.status_code == 200

    # execute
    body = {"task_id": "t_tool1", "tool": "summarizer", "params": {"text": "hi"}}
    r = client.post("/tools/execute", headers=HEADERS, json=body)
    assert r.status_code in (200, 201)
    data = r.json()
    assert "output" in data

# ------------------------------
# AutoRAG retry simulation
# ------------------------------

def test_autorag_retry(monkeypatch):
    """Ensure autorag retry mechanism behaves correctly."""

    from app.services import rag_service

    # simulate failure twice, then success
    state = {"calls": 0}

    def mock_get_collection():
        state["calls"] += 1
        if state["calls"] < 3:
            raise RuntimeError("Chroma not ready")
        return "ok"

    monkeypatch.setattr(rag_service, "_get_collection", mock_get_collection)
    from app.services import rag_auto_populator
    ready = rag_auto_populator._ensure_chroma_ready(retries=5, delay=0.1)
    assert ready is True
    assert state["calls"] >= 3

# ------------------------------
# Fallbacks
# ------------------------------

def test_gemini_fallback(monkeypatch):
    """Ensure Gemini fallback works when no API key."""
    import app.core.gemini_client as gemini

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = gemini.ask_gemini("Test fallback")
    assert result.startswith("FALLBACK SUMMARY")

# ------------------------------
# Telemetry off
# ------------------------------

def test_telemetry_off(monkeypatch):
    """Ensure telemetry env vars are disabled."""
    import app.services.rag_service as rs
    val = os.environ.get("ANONYMIZED_TELEMETRY", "false")
    assert val.lower() in ("false", "0", "no")

# ------------------------------
# Memory persistence
# ------------------------------

def test_remember_and_recall(monkeypatch):
    """Store text into Chroma and recall it."""
    from app.services import rag_service

    # try a real add/get cycle
    doc_id = rag_service.remember_document("unit1", "test document content")
    assert isinstance(doc_id, str)
    results = rag_service.recall("unit1", "document", k=1)
    assert isinstance(results, list)
