import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from sentence_transformers import SentenceTransformer

_MODEL = None
_MODEL_NAME = None

def get_model(model_name="all-MiniLM-L6-v2"):
    global _MODEL, _MODEL_NAME
    if _MODEL is None or _MODEL_NAME != model_name:
        _MODEL = SentenceTransformer(model_name, device="cpu")
        _MODEL_NAME = model_name
    return _MODEL


def embed_texts(texts, model_name="paraphrase-MiniLM-L3-v2"):
    """
    texts: list[str]
    returns: list[list[float]] embeddings (numpy -> python list)
    """
    model = get_model(model_name)
    embs = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    # ensure float lists
    return [emb.tolist() for emb in embs]

def embed_text(text, model_name="all-MiniLM-L6-v2"):
    return embed_texts([text], model_name)[0]
