# app/routers/long_memory_router.py
from fastapi import APIRouter, Request, HTTPException
from app.services.rag_service import remember_document, recall
from app.core.config import settings

router = APIRouter(prefix="/memory/long-term", tags=["LongTermMemory"])

@router.post("/remember")
def remember(payload: dict, request: Request):
    task_id = payload.get("task_id")
    text = payload.get("text")
    metadata = payload.get("metadata", {})
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    res = remember_document(text, metadata=metadata, task_id=task_id)
    return {"task_id": task_id, "status": "remembered", "doc_id": res["doc_id"], "chunk_ids": res["chunk_ids"]}

@router.post("/recall")
def recall_endpoint(payload: dict, request: Request):
    task_id = payload.get("task_id")
    query = payload.get("query")
    k = int(payload.get("k", 3))
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    results = recall(query, k=k)
    return {"task_id": task_id, "results": results}
