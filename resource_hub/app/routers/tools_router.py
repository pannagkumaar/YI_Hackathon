from fastapi import APIRouter, Request, HTTPException
from app.repos.tool_repo import register_tool, list_tools, get_tool
from app.services.tool_service import execute_tool, bootstrap_default_tools
from app.core.logging_client import send_log
from app.core.config import settings
from fastapi import APIRouter, Request, HTTPException, Depends # Add Depends

# --- Integration Fix ---
# Import the unified security dependency
try:
    from app.core.security import get_api_key
except ImportError:
    print("FATAL: Could not import get_api_key. Please copy 'security.py' to 'app/core/security.py'")
    # Define a dummy fallback to allow the server to start, but it will fail auth
    def get_api_key():
        raise HTTPException(status_code=500, detail="Auth not configured")

router = APIRouter(
    prefix="/tools", 
    tags=["Tools"], 
    dependencies=[Depends(get_api_key)] # Apply security to all routes
)
# --- End Integration Fix ---

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
    send_log(settings.SERVICE_NAME, request.state.task_id, "INFO", f"Tool registered: {name}")
    return {"status": "registered", "name": name}

@router.get("/list")
def list_all():
    # This is the endpoint the Partner service calls
    return {"tools": list_tools()}

@router.post("/execute")
def execute(payload: dict, request: Request):
    task_id = payload.get("task_id")
    
    # --- Integration Fix ---
    # Accept "tool_name" and "parameters" from the Partner service
    tool = payload.get("tool") or payload.get("tool_name") 
    params = payload.get("params") or payload.get("parameters", {}) 
    # --- End Integration Fix ---

    try:
        out = execute_tool(tool, params)
        
        # --- Integration Fix ---
        # Return the "success" (lowercase) status that Partner expects
        return {"task_id": task_id, "status": "success", "output": out}
        # --- End Integration Fix ---
        
    except ValueError as e:
        # --- Integration Fix ---
        # Return the "deviation" status that Partner expects
        error_message = str(e)
        if "tool not found" in error_message:
            raise HTTPException(status_code=404, detail=error_message)
        
        # For other errors (e.g., "handler not implemented"), return a deviation
        send_log(settings.SERVICE_NAME, task_id, "WARN", f"Tool execution failed: {tool}", {"error": error_message})
        return {"task_id": task_id, "status": "deviation", "error": error_message}
        # --- End Integration Fix ---
    except Exception as e:
        # Catch-all for unexpected errors
        error_message = str(e)
        send_log(settings.SERVICE_NAME, task_id, "ERROR", f"Tool execution fatal error: {tool}", {"error": error_message})
        return {"task_id": task_id, "status": "deviation", "error": f"Unhandled exception: {error_message}"}