# 📄 resource_hub_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key
from typing import List, Optional, Dict, Tuple
import math
from gemini_client import get_embedding

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Resource Hub Service",
    description="Provides tools, policies, and memory for SHIVA agents.",
    dependencies=[Depends(get_api_key)]
)
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "resource-hub-service"
SERVICE_PORT = 8006
# --- End Authentication & Service Constants ---

# --- Mock Database ---
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
        {"name": "fetch_data", "description": "Fetches data from an API."}
    ]
}

# --- NEW: Short-Term Memory Database ---
# Stores { "task_id": [ { "thought": "...", "action": "...", "observation": "..." } ] }
tasks_memory = {}
# --- End Mock Database ---

# --- NEW: Pydantic Model for Memory ---
class MemoryEntry(BaseModel):
    thought: str
    action: str
    observation: str
# ---

# --- Service Discovery & Logging (No change) ---
def discover(service_name: str) -> str:
    """Finds a service's URL from the Directory."""
    print(f"[ResourceHub] Discovering: {service_name}")
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER
        )
        if r.status_code != 200:
            print(f"[ResourceHub] FAILED to discover {service_name}.")
            raise HTTPException(500, detail=f"Could not discover {service_name}")
        url = r.json()["url"]
        print(f"[ResourceHub] Discovered {service_name} at {url}")
        return url
    except requests.exceptions.ConnectionError:
        print(f"[ResourceHub] FAILED to connect to Directory at {DIRECTORY_URL}")
        raise HTTPException(500, detail="Could not connect to Directory Service")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service."""
    try:
        overseer_url = discover("overseer-service") # Corrected: 'overseer-service'
        requests.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER)
    except Exception as e:
        print(f"[ResourceHub] FAILED to log to Overseer: {e}")
# --- End Service Discovery & Logging ---

# --- Service Registration (No change) ---
def register_self():
    """Registers this service with the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            if r.status_code == 200:
                print(f"[ResourceHub] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[ResourceHub] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[ResourceHub] Could not connect to Directory. Retrying in 5s...")
        time.sleep(5)

def heartbeat():
    """Sends a periodic heartbeat to the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER)
            print("[ResourceHub] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[ResourceHub] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
    # Initialize vector store with embeddings
    try:
        initialize_vector_store()
    except Exception as e:
        print(f"[ResourceHub] WARNING: Failed to initialize vector store: {e}")
        print("[ResourceHub] Falling back to keyword-based search only.")
# --- End Service Registration ---


# --- API Endpoints (UPDATED) ---
@app.get("/policy/list", status_code=200)
def get_policies(context: str = "global"):
    """Fetch compliance policies."""
    log_to_overseer("N/A", "INFO", f"Policy list requested for context: {context}")
    return {"policies": MOCK_POLICIES.get(context, [])}

@app.get("/tools/list", status_code=200)
def get_tools():
    """Fetch available tools for agents."""
    log_to_overseer("N/A", "INFO", "Tool list requested.")
    return MOCK_TOOLS

# --- NEW: Memory Endpoints (Point 2) ---

@app.post("/memory/{task_id}", status_code=201)
def add_memory(task_id: str, entry: MemoryEntry):
    """Add a (Thought, Action, Observation) entry to short-term memory."""
    if task_id not in tasks_memory:
        tasks_memory[task_id] = []
    
    tasks_memory[task_id].append(entry.dict())
    log_to_overseer(task_id, "INFO", f"Memory entry added for task {task_id}")
    return {"status": "Memory added", "entries": len(tasks_memory[task_id])}

@app.get("/memory/{task_id}", status_code=200, response_model=List[MemoryEntry])
def get_memory(task_id: str):
    """Retrieve the full short-term memory history for a task."""
    if task_id not in tasks_memory:
        log_to_overseer(task_id, "WARN", f"No memory found for task {task_id}")
        return []
    
    log_to_overseer(task_id, "INFO", f"Memory retrieved for task {task_id}")
    return tasks_memory[task_id]

@app.get("/memory/query/{task_id}", status_code=200)
def query_rag(task_id: str, query: str):
    """(Mock RAG) Query the task's memory for insights."""
    
    memory_history = tasks_memory.get(task_id, [])
    log_to_overseer(task_id, "INFO", f"RAG query received: {query}")
    
    # Mock RAG: A real implementation would use LangChain + ChromaDB
    # This mock just looks for keywords in the memory
    
    if not memory_history:
        return {"insight": "No memory to analyze, but I'll try my best."}

    history_str = str(memory_history)
    insight = f"Mock RAG insight based on {len(memory_history)} entries. "
    if "error" in history_str.lower():
        insight += "Analysis of memory shows a previous error was encountered."
    elif "success" in history_str.lower():
        insight += "Analysis of memory shows previous steps were successful."
    else:
        insight += "Memory seems nominal."
        
    return {"insight": insight}

# --- End NEW Memory Endpoints ---


class RunbookQuery(BaseModel):
    query: str
    max_snippets: Optional[int] = 3

# A mock "runbook" store you can extend later
MOCK_RUNBOOK = [
    {"title": "Delete operations", "text": "Deleting files: never run 'rm -rf' on production. Use backup->archive first. Only operations team may approve."},
    {"title": "Shutdown procedure", "text": "Planned shutdowns must be scheduled and approved; emergency shutdown needs signoff from on-call. Use `systemctl` carefully."},
    {"title": "Deploy checklist", "text": "Deploy to staging first. Run health checks: list of commands: check-disk, check-db-connections, run smoke tests."}
]

# --- RAG Vector Store ---
# Structure: { "id": {"text": str, "title": str, "embedding": List[float], "source": str } }
vector_store: Dict[str, Dict] = {}

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(a * a for a in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)

def initialize_vector_store():
    """Initialize the vector store with embeddings for runbook, policies, and tools."""
    global vector_store
    vector_store = {}
    doc_id = 0
    
    print("[ResourceHub] Initializing vector store with embeddings...")
    
    # Add runbook entries
    for entry in MOCK_RUNBOOK:
        text = f"{entry['title']}: {entry['text']}"
        embedding = get_embedding(text, task_type="retrieval_document")
        vector_store[str(doc_id)] = {
            "text": entry['text'],
            "title": entry['title'],
            "embedding": embedding,
            "source": "runbook"
        }
        doc_id += 1
    
    # Add policy entries
    for policy in MOCK_POLICIES.get("global", []):
        embedding = get_embedding(policy, task_type="retrieval_document")
        vector_store[str(doc_id)] = {
            "text": policy,
            "title": "Policy",
            "embedding": embedding,
            "source": "policy"
        }
        doc_id += 1
    
    # Add tool entries
    for tool in MOCK_TOOLS.get("tools", []):
        text = f"{tool['name']}: {tool['description']}"
        embedding = get_embedding(text, task_type="retrieval_document")
        vector_store[str(doc_id)] = {
            "text": tool['description'],
            "title": f"Tool: {tool['name']}",
            "embedding": embedding,
            "source": "tool"
        }
        doc_id += 1
    
    print(f"[ResourceHub] Vector store initialized with {len(vector_store)} documents.")

def search_vector_store(query: str, max_results: int = 3) -> List[Dict]:
    """Search the vector store using semantic similarity."""
    if not vector_store:
        return []
    
    # Get query embedding (use retrieval_query task type for queries)
    try:
        query_embedding = get_embedding(query, task_type="retrieval_query")
    except Exception as e:
        print(f"[ResourceHub] Failed to get query embedding: {e}")
        # Fallback to keyword search
        return fallback_keyword_search(query, max_results)
    
    # Calculate similarities
    similarities: List[Tuple[str, float, Dict]] = []
    for doc_id, doc in vector_store.items():
        similarity = cosine_similarity(query_embedding, doc['embedding'])
        similarities.append((doc_id, similarity, doc))
    
    # Sort by similarity (descending)
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    # Return top results
    results = []
    for doc_id, similarity, doc in similarities[:max_results]:
        if similarity > 0.1:  # Minimum similarity threshold
            results.append({
                "title": doc['title'],
                "text": doc['text'],
                "source": doc['source'],
                "similarity": round(similarity, 4)
            })
    
    return results

def fallback_keyword_search(query: str, max_results: int) -> List[Dict]:
    """Fallback to keyword search if embedding fails."""
    query_lower = query.lower()
    results = []
    
    # Search runbook
    for entry in MOCK_RUNBOOK:
        if query_lower in entry['title'].lower() or query_lower in entry['text'].lower():
            results.append({"title": entry['title'], "text": entry['text'], "source": "runbook", "similarity": 0.5})
            if len(results) >= max_results:
                return results
    
    # Search policies
    for policy in MOCK_POLICIES.get("global", []):
        if query_lower in policy.lower():
            results.append({"title": "Policy", "text": policy, "source": "policy", "similarity": 0.5})
            if len(results) >= max_results:
                return results
    
    return results

@app.post("/runbook/search", status_code=200)
def runbook_search(q: RunbookQuery, api_key: str = Depends(get_api_key)):
    """Legacy endpoint - searches runbook and policies for query terms (keyword-based)."""
    query = q.query.lower().strip()
    max_snips = q.max_snippets or 3

    # naive keyword match across policies, runbook, tools
    snippets = []

    # search MOCK_RUNBOOK
    for r in MOCK_RUNBOOK:
        if query in r["title"].lower() or query in r["text"].lower():
            snippets.append({"title": r["title"], "text": r["text"]})
            if len(snippets) >= max_snips:
                break

    # search policies (as small explanatory snippets)
    if len(snippets) < max_snips:
        for p in MOCK_POLICIES.get("global", []):
            if query in p.lower() or any(w in p.lower() for w in query.split()):
                snippets.append({"title": "Policy", "text": p})
                if len(snippets) >= max_snips:
                    break

    # search tools descriptions
    if len(snippets) < max_snips:
        for t in MOCK_TOOLS.get("tools", []):
            if query in t["name"].lower() or query in t["description"].lower():
                snippets.append({"title": f"Tool: {t['name']}", "text": t["description"]})
                if len(snippets) >= max_snips:
                    break

    if not snippets:
        snippets = [{"title": "No relevant runbook found", "text": "No direct guidance found for this query in runbook/policies/tools."}]

    return {"snippets": snippets}

class RAGQuery(BaseModel):
    query: str
    max_snippets: Optional[int] = 3
    task_id: Optional[str] = None

@app.post("/rag/query", status_code=200)
def rag_query(q: RAGQuery, api_key: str = Depends(get_api_key)):
    """Proper RAG endpoint using vector embeddings for semantic search."""
    query = q.query.strip()
    max_snippets = q.max_snippets or 3
    task_id = q.task_id or "N/A"
    
    log_to_overseer(task_id, "INFO", f"RAG query received: {query[:100]}")
    
    if not query:
        return {"snippets": [], "message": "Empty query provided"}
    
    # Use vector-based semantic search
    results = search_vector_store(query, max_results=max_snippets)
    
    # Format results to match expected structure
    snippets = []
    for result in results:
        snippets.append({
            "title": result["title"],
            "text": result["text"],
            "source": result.get("source", "unknown"),
            "similarity": result.get("similarity", 0.0)
        })
    
    if not snippets:
        snippets = [{
            "title": "No relevant documents found",
            "text": "No semantically similar documents found for this query.",
            "source": "system",
            "similarity": 0.0
        }]
    
    log_to_overseer(task_id, "INFO", f"RAG query returned {len(snippets)} snippets")
    
    return {"snippets": snippets}



if __name__ == "__main__":
    print(f"Starting Resource Hub Service on port {SERVICE_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)