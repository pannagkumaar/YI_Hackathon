from .short_term import init_short_term_db

def init_all_memory():
    init_short_term_db()
    print("Short-term memory DB initialized.")
