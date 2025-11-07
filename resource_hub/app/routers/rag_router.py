# app/routers/rag_router.py
from fastapi import APIRouter, Request, HTTPException
from app.services.rag_service import recall, store_qa
from app.core.gemini_client import ask_gemini
from app.core.logging_client import send_log
from app.core.config import settings
import textwrap

router = APIRouter(prefix="/rag", tags=["RAG"])

PROMPT_TEMPLATE = textwrap.dedent("""\
You are the SHIVA Resource Hub. Use ONLY the context below to answer the question concisely and accurately.

Context:
{contexts}

Question:
{question}

Answer concisely. If the answer is not present in the context, reply: "I don't have enough information in my current knowledge."
""")

@router.post("/query")
def rag_query(payload: dict, request: Request):
    task_id = payload.get("task_id")
    query = payload.get("query")
    k = int(payload.get("k", 3))
    compose = payload.get("compose", True)
    debug = payload.get("debug", False)
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    # Retrieve
    hits = recall(query, k=k)
    contexts = ""
    sources = []
    for i, h in enumerate(hits):
        contexts += f"{i+1}) {h['text']}\n"
        sources.append(h['id'])
    # Compose with Gemini
    if compose:
        prompt = PROMPT_TEMPLATE.format(contexts=contexts, question=query)
        answer = ask_gemini(prompt)
    else:
        # simple aggregation fallback (shouldn't happen per your choice)
        answer = " | ".join([h['text'] for h in hits])
    # store Q&A into long-term memory
    try:
        store_qa(query, answer, metadata={"source": "qa", "via": "rag_query"}, task_id=task_id)
    except Exception as e:
        # non-fatal; log and continue
        send_log(settings.SERVICE_NAME, task_id, "WARN", f"Failed to store QA: {e}")
    send_log(settings.SERVICE_NAME, task_id, "INFO", "RAG query processed", {"query": query, "k": k, "hits": len(hits)})
    out = {"task_id": task_id, "answer": answer, "sources": sources}
    if debug:
        out["contexts"] = hits
    return out
