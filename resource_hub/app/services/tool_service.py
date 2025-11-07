from app.repos.tool_repo import register_tool, list_tools, get_tool

# Simple deterministic handlers - extendable
def summarizer_handler(text: str):
    return (text[:300] + "...") if len(text) > 300 else text

def keyword_handler(text: str):
    # naive keywords
    words = [w.strip('.,()[]') for w in text.split() if len(w) > 3]
    uniq = []
    for w in words:
        lw = w.lower()
        if lw not in uniq:
            uniq.append(lw)
    return uniq[:10]

def sentiment_handler(text: str):
    if any(x in text.lower() for x in ["fail", "error", "panic", "fatal"]):
        return {"sentiment": "negative"}
    if any(x in text.lower() for x in ["good", "ok", "success", "complete"]):
        return {"sentiment": "positive"}
    return {"sentiment": "neutral"}

# map handler name to callable
HANDLERS = {
    "summarizer": summarizer_handler,
    "keyword_extractor": keyword_handler,
    "sentiment_analyzer": sentiment_handler
}

def execute_tool(name: str, params: dict):
    tool = get_tool(name)
    if not tool:
        raise ValueError("tool not found")
    handler_name = tool['handler']
    handler = HANDLERS.get(handler_name)
    if not handler:
        raise ValueError("handler not implemented")
    text = params.get("text", "")
    return handler(text)

# initialize default tools
def bootstrap_default_tools():
    register_tool("summarizer", "Summarizes text", "summarizer")
    register_tool("keyword_extractor", "Extracts keywords", "keyword_extractor")
    register_tool("sentiment_analyzer", "Basic sentiment", "sentiment_analyzer")
