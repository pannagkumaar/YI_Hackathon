# app/routers/rag_router.py

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel                      # REQUIRED
import textwrap
import os
from dotenv import load_dotenv

from app.core.gemini_client import ask_gemini
from core.logging_client import send_log
from app.core.config import settings

# NEW — dynamic plan expansion

# from app.services.llm_planner import generate_plan_steps
from app.services.rag_service import recall, store_qa

from pydantic import BaseModel
import re

# Load environment
load_dotenv()
if os.path.exists(".env.local"):
    load_dotenv(".env.local")


router = APIRouter(prefix="/rag", tags=["RAG"])


PROMPT_TEMPLATE = textwrap.dedent("""\
You are the SHIVA Resource Hub. Use ONLY the context below to answer the question concisely and accurately.

Context:
{contexts}

Question:
{question}

Answer concisely. If the answer is not present in the context, reply: "I don't have enough information in my current knowledge."
""")


# --------------------------
#  PLAN EXPANSION SUPPORT
# --------------------------

# class PlanRequest(BaseModel):
#     goal: str
#     context: dict = {}


# @router.post("/plan/expand")
# async def expand_plan(req: PlanRequest):
#     """
#     Expand a high-level goal into multiple actionable steps.
#     Uses LLM or simple rule-based fallback.
#     """
#     try:
#         steps = await generate_plan_steps(req.goal, req.context)
#         return {"steps": steps}
#     except Exception as e:
#         raise HTTPException(500, f"Plan generation failed: {e}")


# --------------------------
#  RAG QUERY ENDPOINT
# --------------------------

@router.post("/query")
def rag_query(payload: dict, request: Request):
    task_id = payload.get("task_id")
    query = payload.get("query")
    k = int(payload.get("k", 3))
    compose = payload.get("compose", True)
    debug = payload.get("debug", False)

    send_log(settings.SERVICE_NAME, task_id, "INFO",
             f"RAG query: {payload.get('question')}")

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
        answer = " | ".join([h['text'] for h in hits])

    # store Q&A into long-term memory
    try:
        store_qa(query, answer, metadata={"source": "qa", "via": "rag_query"}, task_id=task_id)
    except Exception as e:
        send_log(settings.SERVICE_NAME, task_id, "WARN", f"Failed to store QA: {e}")

    send_log(settings.SERVICE_NAME, task_id, "INFO", "RAG query processed",
             {"query": query, "k": k, "hits": len(hits)})

    out = {"task_id": task_id, "answer": answer, "sources": sources}
    if debug:
        out["contexts"] = hits

    return out
