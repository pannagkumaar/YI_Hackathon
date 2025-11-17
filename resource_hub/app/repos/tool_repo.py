# resource_hub/app/repos/tool_repo.py
"""
Central static tool registry for Resource Hub (the Armory).
This module provides a single source-of-truth for all tool definitions
that Partner and other services fetch via /tools/list.
"""

from typing import Dict, List, Optional

TOOLS: Dict[str, dict] = {}


def register_tool(name: str, description: str, handler_name: str, parameters: dict):
    """
    Register a tool in the in-memory registry.
    This is called on import/startup to preload default tools.
    """
    TOOLS[name] = {
        "name": name,
        "description": description,
        "handler": handler_name,
        "parameters": parameters
    }
    return TOOLS[name]


def list_tools() -> List[dict]:
    """Return a list of tool definitions."""
    return list(TOOLS.values())


def get_tool(name: str) -> Optional[dict]:
    """Return the tool definition or None if missing."""
    return TOOLS.get(name)


# ---------------------------
# Preload the default toolset
# ---------------------------

def initialize_tools():
    # NLP / existing tools
    register_tool(
        name="summarizer",
        description="Summarizes text",
        handler_name="summarizer",
        parameters={"text": "string"}
    )

    register_tool(
        name="keyword_extractor",
        description="Extracts keywords from text",
        handler_name="keyword_extractor",
        parameters={"text": "string"}
    )

    register_tool(
        name="sentiment_analyzer",
        description="Analyzes sentiment in text",
        handler_name="sentiment_analyzer",
        parameters={"text": "string"}
    )

    # Operational / IT tools (problem-statement required / mock IT tools)
    register_tool(
        name="ping_host",
        description="Ping a host to test basic connectivity (mock simple wrapper)",
        handler_name="ping_host",
        parameters={"host": "string"}
    )

    register_tool(
        name="http_status_check",
        description="Perform a simple HTTP GET and return status code",
        handler_name="http_status_check",
        parameters={"url": "string"}
    )

    register_tool(
        name="system_info",
        description="Return basic system information (OS, uptime, cpu_percent)",
        handler_name="system_info",
        parameters={}
    )


# initialize at import time
initialize_tools()
