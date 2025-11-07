from fastapi import APIRouter, Request, HTTPException, Depends, Body
from app.core.db import save_short_term, get_short_term
from app.core.config import settings
from app.core.logging_client import send_log
import typing

# --- Integration Fix ---
# Import the unified security dependency
# This assumes you have copied 'security.py' to 'app/core/security.py'
try:
    from app.core.security import get_api_key
except ImportError:
    print("FATAL: Could not import get_api_key. Please copy 'security.py' to 'app/core/security.py'")
    # Define a dummy fallback to allow the server to start, but it will fail auth
    def get_api_key():
        raise HTTPException(status_code=500, detail="Auth not configured")

# --- Integration Fix ---
# Change prefix to /memory to match what Partner/Guardian call.
# Add the unified auth dependency to the whole router.
router = APIRouter(
    prefix="/memory", 
    tags=["ShortTermMemory"],
    dependencies=[Depends(get_api_key)]
)


# --- START: Compatibility Endpoints for existing services ---

@router.get("/{task_id}", status_code=200)
def get_memory_for_guardian(task_id: str):
    """
    (Compatibility) Provides simple list format for Guardian service.
    The Guardian expects a direct JSON list of memory entries.
    """
    rows = get_short_term(task_id)
    # Return the list directly
    return rows

@router.post("/{task_id}", status_code=201)
def add_memory_for_partner(task_id: str, entry: dict = Body(...)):
    """
    (Compatibility) Accepts the (Thought, Action, Observation) 
    format from the Partner service.
    """
    thought = entry.get("thought", "N/A")
    action = entry.get("action", "N/A")
    observation = entry.get("observation", "N/A")
    
    # Combine into a single text entry for your new database
    text_entry = f"Thought: {thought}\nAction: {action}\nObservation: {observation}"
    
    # Use your existing save logic
    save_short_term(
        task_id=task_id, 
        text=text_entry, 
        metadata={"source": "partner-v1-compat"}, 
        ttl=settings.DEFAULT_TTL
    )
    send_log(settings.SERVICE_NAME, task_id, "INFO", "Short-term memory saved (via partner endpoint)")
    
    # Return a response compatible with the old hub
    return {"status": "Memory added"}

# --- END: Compatibility Endpoints ---


# --- START: New, Standard Endpoints ---
# These routes are nested to avoid conflicting with the compatibility routes.

@router.post("/short-term/save")
def save_standard(payload: dict):
    """
    Standard endpoint for saving memory with a full payload.
    """
    task_id = payload.get("task_id")
    text = payload.get("text")
    metadata = payload.get("metadata", {})
    ttl = payload.get("ttl", settings.DEFAULT_TTL)
    if not (task_id and text):
        raise HTTPException(status_code=400, detail="task_id and text required")
    
    save_short_term(task_id, text, metadata, ttl)
    send_log(settings.SERVICE_NAME, task_id, "INFO", "Short-term memory saved")
    return {"task_id": task_id, "status": "saved"}

@router.get("/short-term/{task_id}")
def get_standard(task_id: str):
    """
    Standard endpoint for retrieving memory, returns a full response object.
    """
    rows = get_short_term(task_id)
    # This is the "new" style response, which is more descriptive
    return {"task_id": task_id, "status": "OK", "data": rows}

# --- END: New, Standard Endpoints ---