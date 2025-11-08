# resource_hub/app/auto_rag.py
import time
import threading
import logging
from app.services import rag_service

logger = logging.getLogger("auto_rag")

def safe_init_chroma(retries=5, delay=2):
    for i in range(retries):
        try:
            # _get_collection will trigger client init
            rag_service._get_collection()
            logger.info("Chroma ready")
            return True
        except Exception as e:
            logger.warning(f"Chroma init attempt {i+1}/{retries} failed: {e}")
            time.sleep(delay)
    logger.error("Chroma not ready after retries")
    return False

def background_populator(stop_event: threading.Event):
    if not safe_init_chroma():
        return
    while not stop_event.is_set():
        try:
            # your population logic here: ingest initial domain docs
            # rag_service.remember_document(...)
            logger.debug("AutoRAG cycle complete")
            # sleep longer between cycles
            time.sleep(60)
        except Exception as e:
            logger.exception("AutoRAG cycle failed")
            time.sleep(5)

def start_background_populator():
    stop_event = threading.Event()
    t = threading.Thread(target=background_populator, args=(stop_event,), daemon=True)
    t.start()
    return stop_event
