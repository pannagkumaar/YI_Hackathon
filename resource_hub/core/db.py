import sqlite3, time, threading
from core.config import settings

def init_db():
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS short_term_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        text TEXT,
        metadata TEXT,
        created_at REAL,
        ttl INTEGER
    )""")
    conn.commit()
    conn.close()

def cleanup_expired():
    while True:
        conn = sqlite3.connect(settings.DB_PATH)
        c = conn.cursor()
        now = time.time()
        c.execute("DELETE FROM short_term_memory WHERE created_at + ttl < ?", (now,))
        conn.commit()
        conn.close()
        time.sleep(600)  # every 10 min

def start_cleanup_thread():
    t = threading.Thread(target=cleanup_expired, daemon=True)
    t.start()
