"""
AutoRAG Populator for SHIVA Resource Hub
----------------------------------------
This runs automatically at startup and continuously syncs the RAG memory
with data fetched from internal endpoints (/tools, /policy, /memory).
It ensures that the RAG knowledge base always reflects live system state.
"""

import threading
import time
import requests
from app.services.rag_service import store_qa
from app.core.config import settings

DIRECTORY_RETRY_DELAY = 5
SYNC_INTERVAL = 60  # seconds

def _safe_fetch(url: str) -> dict:
    try:
        r = requests.get(url, headers={"X-SHIVA-SECRET": settings.SHARED_SECRET}, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"[AutoRAG] Non-200 from {url}: {r.status_code}")
    except Exception as e:
        print(f"[AutoRAG] Failed fetching {url}: {e}")
    return {}

def _populate_tools():
    url = f"{settings.SERVICE_BASE_URL}/tools/list"
    data = _safe_fetch(url)
    if not data or "tools" not in data:
        return 0
    count = 0
    for t in data["tools"]:
        q = f"What does the {t['name']} tool do?"
        a = f"The {t['name']} tool {t['description']}."
        store_qa(q, a, metadata={"source": "tools"}, task_id="auto")
        count += 1
    print(f"[AutoRAG] Added {count} tools to RAG memory.")
    return count

def _populate_policies():
    url = f"{settings.SERVICE_BASE_URL}/policy/list"
    data = _safe_fetch(url)
    if not data or "policies" not in data:
        return 0
    count = 0
    for p in data["policies"]:
        q = f"Which Guardian policy governs: {p}?"
        a = f"Guardian policy states: {p}"
        store_qa(q, a, metadata={"source": "policy_auto"}, task_id="auto-policy")
        count += 1
    print(f"[AutoRAG] Added {count} policies to RAG memory.")
    return count

def _populate_memory():
    url = f"{settings.SERVICE_BASE_URL}/memory/all"
    data = _safe_fetch(url)
    if not data:
        return 0
    count = 0
    for task_id, entries in data.items():
        for e in entries:
            txt = e.get("text", "")
            if "Action:" in txt:
                q = f"What happened when executing '{txt.split('Action: ')[1].split()[0]}'?"
                a = f"When thinking '{txt.split('Thought: ')[1].splitlines()[0]}', the agent performed '{txt.split('Action: ')[1].splitlines()[0]}' and observed '{txt.split('Observation: ')[1].splitlines()[0]}'."
                store_qa(q, a, metadata={"source": "auto-memory"}, task_id=task_id)
                count += 1
    print(f"[AutoRAG] Added {count} memory-based QA entries.")
    return count

def autorag_loop():
    print("[AutoRAG] Dynamic memory populator started...")
    time.sleep(5)  # wait for services to register
    for attempt in range(5):
        try:
            _populate_tools()
            _populate_policies()
            _populate_memory()
            print("[AutoRAG] Initial seeding complete.")
            break
        except Exception as e:
            print(f"[AutoRAG] Initialization failed ({attempt+1}/5): {e}")
            time.sleep(DIRECTORY_RETRY_DELAY)

    while True:
        try:
            print("[AutoRAG] Periodic RAG refresh...")
            _populate_policies()
            _populate_memory()
            time.sleep(SYNC_INTERVAL)
        except Exception as e:
            print(f"[AutoRAG] Error in periodic sync: {e}")
            time.sleep(SYNC_INTERVAL)

def start_autorag_thread():
    t = threading.Thread(target=autorag_loop, daemon=True)
    t.start()
    return t

def start_policy_thread():
    # Compatibility hook — now unified with autorag
    pass
