from fastapi import APIRouter, Request, HTTPException, Depends
from app.repos.tool_repo import register_tool, list_tools, get_tool
from app.services.tool_service import execute_tool, bootstrap_default_tools
from app.core.logging_client import send_log
from app.core.config import settings

# --- Integration Fix ---
# Import the new, unified security
try:
    from app.core.security import get_api_key
except ImportError:
    def get_api_key():
        raise HTTPException(status_code=500, detail="Auth not configured")

# Secure the entire router
router = APIRouter(
    prefix="/tools", 
    tags=["Tools"],
    dependencies=[Depends(get_api_key)]
)
# --- END FIX ---


# bootstrap default tools on import
bootstrap_default_tools()

@router.post("/register")
def register(payload: dict, request: Request):
    name = payload.get("name")
    desc = payload.get("description", "")
    handler = payload.get("handler")
    if not name or not handler:
        raise HTTPException(status_code=400, detail="name and handler required")
    register_tool(name, desc, handler)
    send_log(settings.SERVICE_NAME, None, "INFO", f"Tool registered: {name}")
    return {"status": "registered", "name": name}

@router.get("/list")
def list_all():
    # This endpoint is already compatible with the Partner service.
    # It expects a dict with a "tools" key.
    return {"tools": list_tools()}

@router.post("/execute")
def execute(payload: dict, request: Request):
    task_id = payload.get("task_id")
    
    # Accept "tool_name" and "parameters" as fallbacks
    tool = payload.get("tool") or payload.get("tool_name")
    params = payload.get("params") or payload.get("parameters", {})
    
    try:
        out = execute_tool(tool, params)
    except ValueError as e:
        # --- INTEGRATION FIX ---
        # Return a deviation status, which the Partner service understands
        return {
            "task_id": task_id, 
            "status": "deviation", 
            "error": str(e)
        }
        # --- END FIX ---
        
    send_log(settings.SERVICE_NAME, task_id, "INFO", f"Tool executed: {tool}", {"tool": tool})
    
    # --- INTEGRATION FIX ---
    # Return a "success" status (lowercase)
    return {
        "task_id": task_id, 
        "status": "success",  # Changed from "SUCCESS"
        "output": out
    }
    # --- END FIX ---