import time
import uuid
import traceback
import chromadb
from app.core.config import settings
from sklearn.feature_extraction.text import HashingVectorizer

# --- Chroma Setup ---
_COLLECTION_NAME = "resource_hub_mem"
_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)

# --- Embedding Setup ---
try:
    from sentence_transformers import SentenceTransformer
    _embedder = SentenceTransformer(settings.EMBEDDING_MODEL)
    print("[RAG] sentence-transformers loaded.")
except Exception as e:
    _embedder = None
    print(f"[RAG] sentence-transformers not available; using hashing fallback")
    _vectorizer = HashingVectorizer(n_features=256)
    print("[RAG] HashingVectorizer ready (dim=256).")


def _ensure_collection():
    try:
        return _client.get_collection(_COLLECTION_NAME)
    except Exception:
        coll = _client.create_collection(name=_COLLECTION_NAME)
        print(f"[RAG] Created new Chroma collection: {_COLLECTION_NAME}")
        return coll


def embed_texts(texts):
    if _embedder:
        return _embedder.encode(texts).tolist()
    return _vectorizer.transform(texts).toarray().tolist()


def store_qa(question, answer, metadata=None, task_id="manual"):
    try:
        collection = _ensure_collection()
        qa_text = f"Q: {question}\nA: {answer}"

        # --- DEDUPLICATION GUARD ---
        existing = collection.query(
            query_texts=[question],
            n_results=3,
            include=["documents"]
        )
        for doc in existing.get("documents", [[]])[0]:
            if question.strip().lower() in doc.lower():
                print(f"[RAG] Skipping duplicate QA: '{question}'")
                return {"status": "skipped", "reason": "duplicate"}

        embedding = embed_texts([qa_text])
        doc_id = str(uuid.uuid4())
        metadata = metadata or {}
        metadata.update({
            "task_id": task_id,
            "created_at": time.time(),
            "chunk_index": 0,
        })
        collection.add(
            ids=[f"{doc_id}#0"],
            documents=[qa_text],
            embeddings=embedding,
            metadatas=[metadata]
        )
        print(f"[RAG] Stored QA -> {question[:50]}... | ID={doc_id}")
        return {"status": "ok", "id": doc_id}
    except Exception as e:
        print(f"[RAG] Error in store_qa: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


def recall(query, k=3):
    try:
        collection = _ensure_collection()
        query_embedding = embed_texts([query])
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=k,
            include=["documents", "metadatas", "distances"]
        )
        hits = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            hit = {
                "id": results["ids"][0][i],
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "score": results["distances"][0][i],
            }
            hits.append(hit)
        return hits
    except Exception as e:
        print(f"[RAG] Error in recall(): {e}")
        traceback.print_exc()
        return []


def remember_document(text, metadata=None, task_id="auto"):
    q = "What information does this document contain?"
    a = text
    return store_qa(q, a, metadata=metadata or {"source": "auto-ingest"}, task_id=task_id)


def list_all():
    try:
        collection = _ensure_collection()
        data = collection.get(include=["documents", "metadatas"])
        return data
    except Exception as e:
        print(f"[RAG] Error in list_all(): {e}")
        return {}


def wipe_all():
    try:
        _client.delete_collection(_COLLECTION_NAME)
        print(f"[RAG] Wiped collection: {_COLLECTION_NAME}")
    except Exception as e:
        print(f"[RAG] Error wiping collection: {e}")

# --- Compatibility alias for older code ---
def _get_collection():
    """Alias for older code expecting _get_collection()."""
    return _ensure_collection()
