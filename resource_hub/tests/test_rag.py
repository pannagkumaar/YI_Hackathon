import pytest
from fastapi.testclient import TestClient
from main import app
from app.services import rag_service
from app.core import gemini_client

HEAD = {"Authorization": "Bearer dev-secret"}

@pytest.fixture(scope="function")
def client(monkeypatch):
    """
    A lightweight client fixture using in-memory Chroma (already default)
    and a mocked Gemini API to avoid real network calls.
    """
    # Mock Gemini API
    monkeypatch.setattr(gemini_client, "ask_gemini", lambda prompt, max_output_tokens=256: "mocked gemini answer")

    # Clear Chroma collection between tests (if exists)
    try:
        rag_service._client.delete_collection(name=rag_service._COLLECTION_NAME)
    except Exception:
        pass
    rag_service._collection = None  # force recreation

    yield TestClient(app)

    # Cleanup after each test
    try:
        rag_service._client.delete_collection(name=rag_service._COLLECTION_NAME)
    except Exception:
        pass
    rag_service._collection = None


def test_chunking_and_embedding(monkeypatch):
    """Ensure chunking and embedding shapes behave as expected."""
    text = "This is a long text. " * 30
    chunks = rag_service.chunk_text(text, chunk_size=100)
    assert len(chunks) > 1
    embeddings = rag_service.embed_texts(chunks)
    assert len(embeddings) == len(chunks)
    assert all(isinstance(v, list) for v in embeddings)


def test_remember_and_recall(client):
    """Store a document and recall it semantically."""
    # Remember document
    payload = {"task_id": "rag1", "text": "The CPU temperature monitor checks system heat."}
    r = client.post("/memory/long-term/remember", json=payload, headers=HEAD)
    assert r.status_code == 200
    data = r.json()
    assert "doc_id" in data
    doc_id = data["doc_id"]

    # Recall document
    payload = {"task_id": "rag1", "query": "monitor system heat", "k": 3}
    r = client.post("/memory/long-term/recall", json=payload, headers=HEAD)
    assert r.status_code == 200
    results = r.json().get("results", [])
    assert len(results) > 0
    assert any("CPU" in r["text"] or "heat" in r["text"] for r in results)


def test_rag_query_and_qa_storage(client):
    """Run RAG query end-to-end with mocked Gemini and verify Q&A stored."""
    # Step 1: remember some knowledge
    payload = {"task_id": "rag2", "text": "Network latency is measured in milliseconds."}
    r = client.post("/memory/long-term/remember", json=payload, headers=HEAD)
    assert r.status_code == 200

    # Step 2: run RAG query
    payload = {"task_id": "rag2", "query": "How is latency measured?", "k": 3, "compose": True}
    r = client.post("/rag/query", json=payload, headers=HEAD)
    assert r.status_code == 200
    data = r.json()
    assert "answer" in data
    assert data["answer"] == "mocked gemini answer"
    assert len(data["sources"]) > 0

    # Step 3: ensure Q&A got stored
    payload = {"task_id": "rag2", "query": "latency measured", "k": 5}
    r = client.post("/memory/long-term/recall", json=payload, headers=HEAD)
    assert r.status_code == 200
    results = r.json()["results"]
    # There should be at least one document with source 'qa'
    qa_sources = [r for r in results if r["metadata"].get("source") == "qa"]
    assert len(qa_sources) >= 1


def test_rag_debug_contexts(client):
    """Debug flag should return contexts array."""
    payload = {"task_id": "rag3", "text": "Memory caching improves retrieval speed."}
    client.post("/memory/long-term/remember", json=payload, headers=HEAD)

    payload = {"task_id": "rag3", "query": "What improves retrieval speed?", "debug": True}
    r = client.post("/rag/query", json=payload, headers=HEAD)
    assert r.status_code == 200
    data = r.json()
    assert "contexts" in data
    assert isinstance(data["contexts"], list)
