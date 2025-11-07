# import os
# # These lines limit thread usage for underlying libraries (NumPy, OpenBLAS, MKL)
# os.environ["OMP_NUM_THREADS"] = "1"
# os.environ["MKL_NUM_THREADS"] = "1"
# os.environ["OPENBLAS_NUM_THREADS"] = "1"
# os.environ["NUMEXPR_NUM_THREADS"] = "1"
# os.environ["CUDA_VISIBLE_DEVICES"] = "" # Disables GPU for model loading

# from sentence_transformers import SentenceTransformer

# _MODEL = None
# _MODEL_NAME = None

# def get_model(model_name="all-MiniLM-L6-v2"):
#     global _MODEL, _MODEL_NAME
#     if _MODEL is None or _MODEL_NAME != model_name:
#         _MODEL = SentenceTransformer(model_name, device="cpu")
#         _MODEL_NAME = model_name
#     return _MODEL


# def embed_texts(texts, model_name="paraphrase-MiniLM-L3-v2"):
#     """
#     texts: list[str]
#     returns: list[list[float]] embeddings (numpy -> python list)
#     """
#     model = get_model(model_name)
#     embs = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
#     # ensure float lists
#     return [emb.tolist() for emb in embs]

# def embed_text(text, model_name="all-MiniLM-L6-v2"):
#     return embed_texts([text], model_name)[0]


# TEMPORARY SAFE MOCK for diagnostics — revert after debugging
import os
os.environ["OMP_NUM_THREADS"] = os.environ.get("OMP_NUM_THREADS", "1")
os.environ["MKL_NUM_THREADS"] = os.environ.get("MKL_NUM_THREADS", "1")
os.environ["OPENBLAS_NUM_THREADS"] = os.environ.get("OPENBLAS_NUM_THREADS", "1")
os.environ["NUMEXPR_NUM_THREADS"] = os.environ.get("NUMEXPR_NUM_THREADS", "1")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["CUDA_VISIBLE_DEVICES"] = ""

def embed_texts(texts, model_name="paraphrase-MiniLM-L3-v2"):
    return [[0.0]*8 for _ in texts]

def embed_text(text, model_name="paraphrase-MiniLM-L3-v2"):
    return [0.0]*8
