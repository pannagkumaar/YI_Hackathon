from fastapi import APIRouter, Depends, HTTPException
from core.auth import verify_auth
from core.logging_client import log_event

router = APIRouter(prefix="/tools", tags=["Tools"])
SERVICE = "resource-hub"

def summarizer(text: str): return text[:100] + "..."
def keyword_extractor(text: str): return list(set(text.lower().split()))[:5]
def sentiment_analyzer(text: str): return "positive" if "good" in text else "negative"

TOOLS = {
    "summarizer": summarizer,
    "keyword_extractor": keyword_extractor,
    "sentiment_analyzer": sentiment_analyzer
}

@router.post("/execute")
def execute_tool(payload: dict, auth=Depends(verify_auth)):
    task_id = payload.get("task_id")
    tool = payload.get("tool")
    params = payload.get("params", {})
    if tool not in TOOLS:
        raise HTTPException(status_code=400, detail="Unknown tool")
    text = params.get("text", "")
    output = TOOLS[tool](text)
    log_event(SERVICE, task_id, "INFO", f"Tool {tool} executed", {"tool": tool})
    return {"task_id": task_id, "status": "SUCCESS", "output": output, "logs": [f"{tool} executed"]}
