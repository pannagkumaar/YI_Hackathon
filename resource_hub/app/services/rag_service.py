# app/services/rag_service.py
import uuid, time
from chromadb.config import Settings
import chromadb
from chromadb.utils import embedding_functions
from app.core.embeddings import embed_texts, embed_text
from app.core.config import settings
from app.core.logging_client import send_log
from chromadb import PersistentClient

# Uses the persist directory set in settings (or :memory: default)
_client = PersistentClient(path="/tmp/chroma_dev")

# Create a collection for Resource Hub long-term memory (name 'resource_hub_mem')
_collection = None
_COLLECTION_NAME = "resource_hub_mem"

def _ensure_collection():
    global _client, _collection
    if _collection is None:
        try:
            _collection = _client.get_collection(_COLLECTION_NAME)
        except Exception:
            # create new collection with default embedding function wrapper (we'll pass embeddings directly)
            _collection = _client.create_collection(name=_COLLECTION_NAME)
    return _collection

def chunk_text(text, chunk_size=500, overlap=50):
    """
    naive sentence-preserving chunker: split on whitespace ensuring chunk_size
    """
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # try to extend to end of sentence if possible
        # find last period/newline within chunk
        last_period = max(chunk.rfind('.'), chunk.rfind('\n'))
        if last_period != -1 and last_period > (len(chunk) // 2):
            # extend to sentence end
            end = start + last_period + 1
            chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap
    return chunks

def remember_document(text, metadata=None, task_id=None, model_name="all-MiniLM-L6-v2", chunk_size=500):
    """
    Split text into chunks, embed each chunk, store into chroma collection.
    Returns list of inserted ids.
    """
    collection = _ensure_collection()
    doc_id = str(uuid.uuid4())
    chunks = chunk_text(text, chunk_size=chunk_size)
    to_embed = chunks
    embeddings = embed_texts(to_embed, model_name=model_name)
    ids = []
    metadatas = []
    documents = []
    
    # FIX: Safely extract source_value, default to None
    source_value = metadata 
    if isinstance(metadata, dict):
        source_value = metadata.get("source")

    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{doc_id}#{idx}"
        ids.append(chunk_id)
        
        # FIX: Ensure all non-essential fields are non-None strings/defaults
        meta = {
            "doc_id": doc_id,
            "chunk_index": idx,
            "task_id": str(task_id) if task_id is not None else "", # Non-None string
            "source": str(source_value) if source_value is not None else "", # Non-None string
            "created_at": time.time(),
            # Ensure custom metadata is merged only if it's a dict
            **(metadata if isinstance(metadata, dict) else {})
        }
        metadatas.append(meta)
        documents.append(chunk)
    # Use chroma client to add
    collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
    send_log(settings.SERVICE_NAME, task_id, "INFO", f"Remembered doc {doc_id} with {len(ids)} chunks", {"doc_id": doc_id})
    return {"doc_id": doc_id, "chunk_ids": ids}

def recall(query, k=3, model_name="all-MiniLM-L6-v2"):
    collection = _ensure_collection()
    emb = embed_text(query, model_name=model_name)
    # query with embedding (Chroma supports query_by_vector)
    results = collection.query(query_embeddings=[emb], n_results=k, include=['ids','metadatas','documents','distances'])
    # results is a dict with lists; results['ids'][0] is list of ids
    out = []
    if results and results.get('ids'):
        ids = results['ids'][0]
        docs = results.get('documents', [[]])[0]
        metas = results.get('metadatas', [[]])[0]
        dists = results.get('distances', [[]])[0]
        # convert distance to similarity if needed (Chroma distances are L2 by default in some configs)
        for cid, doc_text, meta, dist in zip(ids, docs, metas, dists):
            out.append({
                "id": cid,
                "text": doc_text,
                "metadata": meta,
                "score": float(dist)
            })
    send_log(settings.SERVICE_NAME, None, "INFO", f"Recall performed for query", {"query": query, "k": k, "results": len(out)})
    return out

def store_qa(question, answer, metadata=None, task_id=None, model_name="all-MiniLM-L6-v2"):
    """
    Save the Q&A as a document in long-term memory. This stores the combined text.
    """
    qa_text = f"Q: {question}\nA: {answer}"
    metadata = metadata or {}
    metadata.update({"source": "qa", "original_task_id": task_id})
    return remember_document(qa_text, metadata=metadata, task_id=task_id, model_name=model_name)