import sqlite3
import json
import time
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "short_term.db")
TTL_SECONDS = 600  # 10 minutes default

def init_short_term_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        data TEXT,
        saved_at REAL
    )
    """)
    conn.commit()
    conn.close()

def save_short_term(task_id: str, data: dict):
    init_short_term_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory (task_id, data, saved_at) VALUES (?, ?, ?)",
        (task_id, json.dumps(data), time.time())
    )
    conn.commit()
    conn.close()
    return {"status": "saved", "task_id": task_id}

def cleanup_expired():
    init_short_term_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cutoff = time.time() - TTL_SECONDS
    cur.execute("DELETE FROM memory WHERE saved_at < ?", (cutoff,))
    conn.commit()
    conn.close()

def recall_short_term(task_id: str):
    init_short_term_db()
    cleanup_expired()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT data FROM memory WHERE task_id=? ORDER BY saved_at DESC LIMIT 1",
        (task_id,)
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return json.loads(row[0])
