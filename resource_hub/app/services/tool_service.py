# resource_hub/app/services/tool_service.py
"""
Tool execution service for Resource Hub.
Provides implementation for all handlers referenced in tool_repo.
Supports both synchronous (NLP) handlers and async (I/O / system) handlers.
"""

import subprocess
import platform
import time
from typing import Any, Dict

import httpx
import psutil

from app.repos.tool_repo import get_tool

# -----------------------
# NLP / synchronous handlers
# -----------------------
def summarizer(params: Dict[str, Any]):
    text = params.get("text", "")
    # deterministic simple summarizer for demo
    return (text[:300] + "...") if len(text) > 300 else text

def keyword_extractor(params: Dict[str, Any]):
    text = params.get("text", "")
    words = [w.strip('.,()[]') for w in text.split() if len(w) > 3]
    uniq = []
    for w in words:
        lw = w.lower()
        if lw not in uniq:
            uniq.append(lw)
    return uniq[:10]

def sentiment_analyzer(params: Dict[str, Any]):
    text = (params.get("text") or "").lower()
    if any(x in text for x in ["fail", "error", "panic", "fatal"]):
        return {"sentiment": "negative"}
    if any(x in text for x in ["good", "ok", "success", "complete"]):
        return {"sentiment": "positive"}
    return {"sentiment": "neutral"}


# -----------------------
# Operational / async handlers
# -----------------------
async def ping_host(params: Dict[str, Any]):
    host = params.get("host")
    if not host:
        return {"status": "error", "error": "Missing 'host' parameter"}

    # cross-platform one-shot ping; keep simple and bounded
    flag = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        proc = subprocess.run(
            ["ping", flag, "2", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8
        )
        return {
            "status": "ok" if proc.returncode == 0 else "deviation",
            "output": proc.stdout or proc.stderr
        }
    except Exception as e:
        return {"status": "deviation", "error": str(e)}


async def http_status_check(params: Dict[str, Any]):
    url = params.get("url")
    if not url:
        return {"status": "error", "error": "Missing 'url' parameter"}

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
        return {"status": "ok", "output": {"status_code": resp.status_code}}
    except Exception as e:
        return {"status": "deviation", "error": str(e)}


async def system_info(params: Dict[str, Any]):
    try:
        return {
            "status": "ok",
            "output": {
                "os": platform.system(),
                "release": platform.release(),
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "uptime_seconds": time.time() - psutil.boot_time()
            }
        }
    except Exception as e:
        return {"status": "deviation", "error": str(e)}


# -----------------------
# Handler registry mapping
# -----------------------
# keys must match tool_repo.register_tool(... handler_name=)
HANDLERS = {
    # NLP / sync
    "summarizer": summarizer,
    "keyword_extractor": keyword_extractor,
    "sentiment_analyzer": sentiment_analyzer,
    # Operational / async
    "ping_host": ping_host,
    "http_status_check": http_status_check,
    "system_info": system_info,
}


# -----------------------
# Unified execution entrypoint
# -----------------------
async def execute_tool(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the named tool with params.
    Returns a structured result:
      - for sync NLP handlers: {"status":"ok","output": <any>}
      - for async handlers: handlers return their own structured dicts (ok/deviation)
      - if tool or handler missing, returns {"status":"deviation","error": ...}
    """

    tool = get_tool(tool_name)
    if not tool:
        return {"status": "deviation", "error": f"Tool '{tool_name}' not found"}

    handler_name = tool.get("handler")
    handler = HANDLERS.get(handler_name)
    if handler is None:
        return {"status": "deviation", "error": f"Handler '{handler_name}' not implemented"}

    try:
        # sync function (NLP)
        if not callable(handler):
            return {"status": "deviation", "error": "Internal: handler not callable"}

        # detect coroutine function by attribute
        if hasattr(handler, "__call__") and hasattr(handler, "__code__") and handler.__code__.co_flags & 0x80:
            # coroutine function (async def) -> await it
            return await handler(params)
        else:
            # synchronous handler
            out = handler(params)
            return {"status": "ok", "output": out}
    except Exception as e:
        return {"status": "deviation", "error": str(e)}
