# resource_hub_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key
from typing import List, Optional, Dict, Tuple, Any
import math
from gemini_client import get_embedding

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Resource Hub Service",
    description="Provides tools, policies, and memory for SHIVA agents.",
    dependencies=[Depends(get_api_key)]  # Protect all endpoints by default
)
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "resource-hub-service"
SERVICE_PORT = 8006
# --- End Authentication & Service Constants ---

# --- Mock Database (extendable) ---
MOCK_POLICIES = {
    "global": [
        "Disallow: delete",
        "Disallow: shutdown",
        "Disallow: rm -rf"
    ]
}
MOCK_TOOLS = {
    "tools": [
        {"name": "run_script", "description": "Executes a python script."},
        {"name": "fetch_data", "description": "Fetches data from an API."},
        {"name": "restart_service", "description": "Restarts a local service by name."}
    ]
}

# Short-term memory store: { task_id: [ {thought, action, observation}, ... ] }
tasks_memory: Dict[str, List[Dict[str, Any]]] = {}

# Runbook + policy mock store
MOCK_RUNBOOK = [
    {"title": "Delete operations", "text": "Deleting files: never run 'rm -rf' on production. Use backup->archive first. Only operations team may approve."},
    {"title": "Shutdown procedure", "text": "Planned shutdowns must be scheduled and approved; emergency shutdown needs signoff from on-call. Use `systemctl` carefully."},
    {"title": "Deploy checklist", "text": "Deploy to staging first. Run health checks: check-disk, check-db-connections, run smoke tests."}
]

# Vector store structure (id -> {text, title, embedding, source})
vector_store: Dict[str, Dict[str, Any]] = {}

# --- Utility helpers ---
def discover(service_name: str) -> str:
    """Synchronous discovery helper to query Directory service."""
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER,
            timeout=3
        )
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Directory responded {r.status_code}")
        return r.json()["url"]
    except requests.exceptions.RequestException as e:
        print(f"[ResourceHub] Failed to reach Directory: {e}")
        raise HTTPException(status_code=500, detail="Could not contact Directory service")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = {}):
    """Best-effort logging to Overseer (synchronous)."""
    try:
        overseer_url = discover("overseer-service")
        requests.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER, timeout=2)
    except Exception as e:
        print(f"[ResourceHub] WARN: unable to send log to Overseer: {e}")

# --- Vector + RAG helpers ---
def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a*b for a,b in zip(vec1, vec2))
    m1 = math.sqrt(sum(a*a for a in vec1))
    m2 = math.sqrt(sum(b*b for b in vec2))
    if m1 == 0 or m2 == 0:
        return 0.0
    return dot / (m1*m2)

def initialize_vector_store():
    """Populate vector_store using get_embedding. Non-fatal on failures."""
    global vector_store
    vector_store = {}
    doc_id = 0
    print("[ResourceHub] Initializing vector store...")
    # Runbook
    for entry in MOCK_RUNBOOK:
        text = f"{entry['title']}: {entry['text']}"
        try:
            embedding = get_embedding(text, task_type="retrieval_document")
        except Exception as e:
            embedding = None
            print(f"[ResourceHub] embedding error for runbook '{entry['title']}': {e}")
        if not embedding:
            print(f"[ResourceHub] WARNING: embedding failed for runbook '{entry['title']}' (RAG degraded)")
            continue
        vector_store[str(doc_id)] = {"text": entry['text'], "title": entry['title'], "embedding": embedding, "source": "runbook"}
        doc_id += 1

    # Policies
    for policy in MOCK_POLICIES.get("global", []):
        try:
            embedding = get_embedding(policy, task_type="retrieval_document")
        except Exception as e:
            embedding = None
            print(f"[ResourceHub] embedding error for policy '{policy}': {e}")
        if not embedding:
            print(f"[ResourceHub] WARNING: embedding failed for policy '{policy}' (RAG degraded)")
            continue
        vector_store[str(doc_id)] = {"text": policy, "title": "Policy", "embedding": embedding, "source": "policy"}
        doc_id += 1

    # Tools
    for tool in MOCK_TOOLS.get("tools", []):
        text = f"{tool['name']}: {tool['description']}"
        try:
            embedding = get_embedding(text, task_type="retrieval_document")
        except Exception as e:
            embedding = None
            print(f"[ResourceHub] embedding error for tool '{tool['name']}': {e}")
        if not embedding:
            print(f"[ResourceHub] WARNING: embedding failed for tool '{tool['name']}' (RAG degraded)")
            continue
        vector_store[str(doc_id)] = {"text": tool['description'], "title": f"Tool: {tool['name']}", "embedding": embedding, "source": "tool"}
        doc_id += 1

    print(f"[ResourceHub] Vector store populated with {len(vector_store)} documents.")

def search_vector_store(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Semantic search using vector embeddings; falls back to keyword search."""
    if not vector_store:
        return []

    try:
        q_emb = get_embedding(query, task_type="retrieval_query")
    except Exception as e:
        print(f"[ResourceHub] Query embedding failed: {e}")
        q_emb = None

    if not q_emb:
        print("[ResourceHub] RAG degraded - fallback to keyword search")
        return fallback_keyword_search(query, max_results)

    sims = []
    for doc_id, doc in vector_store.items():
        if "embedding" not in doc:
            continue
        sim = cosine_similarity(q_emb, doc["embedding"])
        sims.append((doc_id, sim, doc))
    sims.sort(key=lambda x: x[1], reverse=True)

    results = []
    for _id, sim, doc in sims[:max_results]:
        if sim > 0.05:
            results.append({"title": doc.get("title", "doc"), "text": doc.get("text", ""), "source": doc.get("source", "unknown"), "similarity": round(sim, 4)})
    return results

def fallback_keyword_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    q = query.lower()
    results = []
    for r in MOCK_RUNBOOK:
        if q in r["title"].lower() or q in r["text"].lower():
            results.append({"title": r["title"], "text": r["text"], "source": "runbook", "similarity": 0.5})
            if len(results) >= max_results:
                return results
    for p in MOCK_POLICIES.get("global", []):
        if q in p.lower() or any(w in p.lower() for w in q.split()):
            results.append({"title": "Policy", "text": p, "source": "policy", "similarity": 0.45})
            if len(results) >= max_results:
                return results
    for t in MOCK_TOOLS.get("tools", []):
        if q in t["name"].lower() or q in t["description"].lower():
            results.append({"title": f"Tool: {t['name']}", "text": t["description"], "source": "tool", "similarity": 0.4})
            if len(results) >= max_results:
                return results
    return results

# --- Pydantic models ---
class MemoryEntry(BaseModel):
    thought: str
    action: str
    observation: str

class RunbookQuery(BaseModel):
    query: str
    max_snippets: Optional[int] = 3

class RAGQuery(BaseModel):
    query: str
    max_snippets: Optional[int] = 3
    task_id: Optional[str] = None

# --- Endpoints ---
@app.get("/policy/list", status_code=200)
def get_policies(context: str = "global"):
    """Return policies (protected by dependency defined on app)."""
    log_to_overseer("N/A", "INFO", f"Policy list requested for context={context}")
    return {"policies": MOCK_POLICIES.get(context, [])}

@app.get("/tools/list", status_code=200)
def get_tools():
    log_to_overseer("N/A", "INFO", "Tool list requested")
    return MOCK_TOOLS

@app.post("/memory/{task_id}", status_code=201)
def add_memory(task_id: str, entry: MemoryEntry):
    if task_id not in tasks_memory:
        tasks_memory[task_id] = []
    tasks_memory[task_id].append(entry.dict())
    log_to_overseer(task_id, "INFO", "Memory entry added", {"entries": len(tasks_memory[task_id])})
    return {"status": "Memory added", "entries": len(tasks_memory[task_id])}

@app.get("/memory/{task_id}", status_code=200)
def get_memory(task_id: str):
    if task_id not in tasks_memory:
        log_to_overseer(task_id, "WARN", "Memory not found")
        return []
    log_to_overseer(task_id, "INFO", "Memory retrieved", {"entries": len(tasks_memory[task_id])})
    return tasks_memory[task_id]

@app.get("/memory/query/{task_id}", status_code=200)
def query_rag(task_id: str, query: str):
    memory_history = tasks_memory.get(task_id, [])
    log_to_overseer(task_id, "INFO", f"Memory RAG query: {query}")
    if not memory_history:
        return {"insight": "No memory to analyze."}
    history_str = str(memory_history)
    insight = f"Mock RAG insight based on {len(memory_history)} entries."
    if "error" in history_str.lower():
        insight += " Memory shows previous error."
    elif "success" in history_str.lower():
        insight += " Memory shows previous successes."
    else:
        insight += " Memory seems nominal."
    return {"insight": insight}

@app.post("/runbook/search", status_code=200)
def runbook_search(q: RunbookQuery):
    query = (q.query or "").strip()
    max_snips = q.max_snippets or 3
    snippets = []
    if not query:
        return {"snippets": [{"title": "Empty query", "text": "No query provided."}]}

    # naive keyword search
    for r in MOCK_RUNBOOK:
        if query.lower() in r["title"].lower() or query.lower() in r["text"].lower():
            snippets.append({"title": r["title"], "text": r["text"]})
            if len(snippets) >= max_snips:
                break

    for p in MOCK_POLICIES.get("global", []):
        if len(snippets) >= max_snips:
            break
        if query.lower() in p.lower() or any(w in p.lower() for w in query.split()):
            snippets.append({"title": "Policy", "text": p})

    for t in MOCK_TOOLS.get("tools", []):
        if len(snippets) >= max_snips:
            break
        if query.lower() in t["name"].lower() or query.lower() in t["description"].lower():
            snippets.append({"title": f"Tool: {t['name']}", "text": t["description"]})

    if not snippets:
        snippets = [{"title": "No relevant runbook found", "text": "No guidance found."}]
    return {"snippets": snippets}

@app.post("/rag/query", status_code=200)
def rag_query(q: RAGQuery):
    query = (q.query or "").strip()
    max_snips = q.max_snippets or 3
    task_id = q.task_id or "N/A"
    log_to_overseer(task_id, "INFO", f"RAG query: {query[:120]}")
    if not query:
        return {"snippets": [], "message": "Empty query provided"}
    results = search_vector_store(query, max_results=max_snips)
    if not results:
        results = [{"title": "No relevant documents found", "text": "No semantically similar documents found.", "source": "system", "similarity": 0.0}]
    log_to_overseer(task_id, "INFO", f"RAG returned {len(results)} snippets")
    return {"snippets": results}

# --- Service registration & heartbeat (synchronous) ---
def register_self():
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER, timeout=3)
            if r.status_code == 200:
                print(f"[ResourceHub] Registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[ResourceHub] Register failed ({r.status_code}) - retrying")
        except requests.exceptions.RequestException:
            print("[ResourceHub] Directory not ready, retrying in 5s")
        time.sleep(5)

def heartbeat():
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER, timeout=3)
        except requests.exceptions.RequestException:
            print("[ResourceHub] Heartbeat failed, re-registering")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
    # Initialize vector store but don't fail if embeddings are unavailable
    try:
        initialize_vector_store()
    except Exception as e:
        print(f"[ResourceHub] Vector init warning: {e}")

if __name__ == "__main__":
    print(f"Starting Resource Hub Service on port {SERVICE_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)