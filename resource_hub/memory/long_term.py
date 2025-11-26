import chromadb
from chromadb.utils import embedding_functions
import uuid
from app.core.config import settings

client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
collection = client.get_or_create_collection("long_term_memory")

embedding_model = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=settings.EMBEDDING_MODEL
)

def remember_memory(memory_text: str, metadata: dict = None):
    memory_id = str(uuid.uuid4())
    collection.add(
        documents=[memory_text],
        metadatas=[metadata or {}],
        ids=[memory_id]
    )
    return {"status": "remembered", "memory_id": memory_id}

def recall_memory(query: str, top_k: int = 3):
    results = collection.query(query_texts=[query], n_results=top_k)
    response = []

    for doc, meta, score in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        response.append({
            "memory_text": doc,
            "metadata": meta,
            "similarity_score": float(score)
        })

    return {
        "query": query,
        "results": response
    }
