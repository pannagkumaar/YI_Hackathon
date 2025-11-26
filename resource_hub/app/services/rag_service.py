# resource_hub/app/services/rag_service.py

"""
RAG + Plan Expansion service layer for SHIVA Resource Hub.
- Long-term memory read/write (Chroma)
- Store QA pairs
- Dynamic multi-step plan generation (Gemini → fallback)
"""

import os
import json
import re  
from typing import List, Dict

from app.core.config import settings
from app.core.gemini_client import ask_gemini
from core.logging_client import send_log

from memory.long_term import remember_memory, recall_memory
from memory.short_term import save_short_term

# --------------------------
# RAG: RECALL
# --------------------------
def recall(query: str, k: int = 3):
    try:
        return recall_memory(query, top_k=k)
    except Exception as e:
        print("[RAG] recall failed:", e)
        return []

# --------------------------
# STORE QA
# --------------------------
def store_qa(question: str, answer: str, metadata=None, task_id: str = None):
    try:
        doc = f"Q: {question}\nA: {answer}"
        meta = metadata or {}
        meta.update({"type": "qa"})
        return remember_memory(doc, meta)
    except Exception as e:
        send_log("resource_hub", task_id, "WARN", f"store_qa failed: {e}")
        return None

# --------------------------
# DOCUMENT INGEST
# --------------------------
def remember_document(text: str, metadata=None):
    return remember_memory(text, metadata or {})
