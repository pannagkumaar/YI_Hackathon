from .long_term import recall_memory

def rag_query(query: str, top_k: int = 3):
    results = recall_memory(query, top_k=top_k)
    docs = [r["memory_text"] for r in results["results"]]

    answer = ""
    if docs:
        answer = f"Based on memory: {docs[0]}"

    return {
        "answer": answer,
        "sources": results["results"]
    }
