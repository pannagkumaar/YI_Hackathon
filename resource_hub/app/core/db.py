import sqlite3, os, time, threading, json
from app.core.config import settings

def init_db():
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS short_term_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        text TEXT,
        metadata TEXT,
        created_at REAL,
        ttl INTEGER
    )
    ''')
    conn.commit()
    conn.close()

    # ensure itsm file exists
    if not os.path.exists(settings.ITSM_PATH):
        os.makedirs(os.path.dirname(settings.ITSM_PATH), exist_ok=True)
        with open(settings.ITSM_PATH, "w") as f:
            json.dump([], f)

def save_short_term(task_id: str, text: str, metadata: dict, ttl: int):
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO short_term_memory(task_id, text, metadata, created_at, ttl) VALUES (?,?,?,?,?)',
              (task_id, text, json.dumps(metadata or {}), time.time(), ttl))
    conn.commit()
    conn.close()

def get_short_term(task_id: str):
    conn = sqlite3.connect(settings.DB_PATH)
    c = conn.cursor()
    c.execute('SELECT text, metadata, created_at FROM short_term_memory WHERE task_id=?', (task_id,))
    rows = c.fetchall()
    conn.close()
    result = []
    for (text, metadata, created_at) in rows:
        try:
            meta = json.loads(metadata) if metadata else {}
        except Exception:
            meta = {}
        result.append({"text": text, "metadata": meta, "created_at": created_at})
    return result

def cleanup_expired():
    while True:
        try:
            conn = sqlite3.connect(settings.DB_PATH)
            c = conn.cursor()
            now = time.time()
            c.execute('DELETE FROM short_term_memory WHERE (created_at + ttl) < ?', (now,))
            conn.commit()
            conn.close()
        except Exception:
            pass
        time.sleep(600)

def start_cleanup_thread():
    t = threading.Thread(target=cleanup_expired, daemon=True)
    t.start()
