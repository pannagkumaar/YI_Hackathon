# resource_hub/app/services/tool_executor.py
"""
Safe tool executor (whitelist + subprocess + timeout).
Return format:
  {"status":"ok", "output": "..."} OR {"status":"deviation", "error":"..."}
"""

import shlex
import subprocess
from typing import Dict, Any

SAFE_TOOL_WHITELIST = {
    # If you want shell tools, add them carefully here:
    # "echo": "echo {text}",
    # "list_dir": "ls -la {path}"
    # For now, keep empty unless you need them.
}

def render_command(template: str, params: Dict[str, Any]):
    # quote each provided param (safe)
    safe_map = {k: shlex.quote(str(v)) for k, v in (params or {}).items()}
    return template.format(**safe_map)

def run_tool(tool_name: str, params: Dict[str, Any], timeout: int = 8) -> Dict[str, Any]:
    if tool_name not in SAFE_TOOL_WHITELIST:
        return {"status": "deviation", "error": f"Tool not allowed: {tool_name}"}
    template = SAFE_TOOL_WHITELIST[tool_name]
    try:
        cmd = render_command(template, params)
    except Exception as e:
        return {"status": "deviation", "error": f"Invalid parameters: {e}"}
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode != 0:
            return {"status": "deviation", "error": stderr or "non-zero exit", "rc": proc.returncode}
        return {"status": "ok", "output": stdout}
    except subprocess.TimeoutExpired:
        return {"status": "deviation", "error": "timeout"}
    except Exception as e:
        return {"status": "deviation", "error": str(e)}
