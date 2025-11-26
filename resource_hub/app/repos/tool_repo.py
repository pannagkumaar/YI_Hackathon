# resource_hub/app/repos/tool_repo.py
from typing import List, Dict, Optional

# Basic static tool registry used by the router and partner
_TOOL_REGISTRY = {
    "summarizer": {
        "name": "summarizer",
        "description": "Summarizes text",
        "handler": "summarizer",
        "parameters": {"text": "string"}
    },
    "keyword_extractor": {
        "name": "keyword_extractor",
        "description": "Extracts keywords from text",
        "handler": "keyword_extractor",
        "parameters": {"text": "string"}
    },
    "sentiment_analyzer": {
        "name": "sentiment_analyzer",
        "description": "Analyzes sentiment in text",
        "handler": "sentiment_analyzer",
        "parameters": {"text": "string"}
    },
    "ping_host": {
        "name": "ping_host",
        "description": "Ping a host to test basic connectivity (mock simple wrapper)",
        "handler": "ping_host",
        "parameters": {"host": "string"}
    },
    "http_status_check": {
        "name": "http_status_check",
        "description": "Perform a simple HTTP GET and return status code",
        "handler": "http_status_check",
        "parameters": {"url": "string"}
    },
    "system_info": {
        "name": "system_info",
        "description": "Return basic system information (OS, uptime, cpu_percent)",
        "handler": "system_info",
        "parameters": {}
    },
}

def list_tools() -> List[Dict]:
    return list(_TOOL_REGISTRY.values())

def get_tool(name: str) -> Optional[Dict]:
    return _TOOL_REGISTRY.get(name)
