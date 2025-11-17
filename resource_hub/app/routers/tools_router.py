# resource_hub/app/routers/tools_router.py
"""
Router exposing tools endpoints:
- GET  /tools/list      -> list available tools (tool definitions)
- POST /tools/execute   -> run a tool by name with parameters
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Any, Dict

from app.repos.tool_repo import list_tools, get_tool
from app.services.tool_service import execute_tool
# Use your existing security util (same as other services)
from app.core.security import get_api_key

router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(get_api_key)])


class ExecuteRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}


@router.get("/list")
def tools_list():
    """Return the list of tool definitions the Resource Hub provides."""
    return {"tools": list_tools()}


@router.post("/execute")
async def tools_execute(req: ExecuteRequest):
    """
    Execute a tool. Returns the tool execution response.
    Response schema: {"status": "ok"|"deviation"|"error", "output": ..., "error": ...}
    """
    tool_def = get_tool(req.tool_name)
    if tool_def is None:
        raise HTTPException(status_code=404, detail=f"Tool '{req.tool_name}' not found")

    result = await execute_tool(req.tool_name, req.parameters or {})
    # Normalize basic error status to HTTP 200 (the API returns structured status).
    return {"tool": req.tool_name, "result": result}
