from fastapi import APIRouter, Request, HTTPException
from app.repos.tool_repo import register_tool, list_tools, get_tool
from app.services.tool_service import execute_tool, bootstrap_default_tools
from app.core.logging_client import send_log
from app.core.config import settings
from fastapi import APIRouter, Request, HTTPException, Depends # Add Depends
from app.core.security import get_api_key

router = APIRouter(
    prefix="/tools", 
    tags=["Tools"], 
    dependencies=[Depends(get_api_key)]
)

# router = APIRouter(prefix="/tools", tags=["Tools"])

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
    return {"tools": list_tools()}

@router.post("/execute")
def execute(payload: dict, request: Request):
    task_id = payload.get("task_id")
    # --- START FIX ---
    # Accept "tool_name" as a fallback for "tool"
    tool = payload.get("tool") or payload.get("tool_name") 
    # Accept "parameters" as a fallback for "params"
    params = payload.get("params") or payload.get("parameters", {}) 
    # --- END FIX ---

    try:
        out = execute_tool(tool, params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    send_log(settings.SERVICE_NAME, task_id, "INFO", f"Tool executed: {tool}", {"tool": tool})
    return {"task_id": task_id, "status": "SUCCESS", "output": out}
