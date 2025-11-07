# simple in-memory tool registry (persisted in-memory for now)
TOOLS = {}

def register_tool(name: str, description: str, handler_name: str):
    TOOLS[name] = {"name": name, "description": description, "handler": handler_name}
    return TOOLS[name]

def list_tools():
    return list(TOOLS.values())

def get_tool(name: str):
    return TOOLS.get(name)
