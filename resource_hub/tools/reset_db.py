#!/usr/bin/env python3
"""
Utility script to reset Resource Hub data (SQLite + ITSM JSON).
Run this when you want a clean start for manual testing or demos.
"""

import os
import sqlite3
import json
from app.core.config import settings

def reset_sqlite():
    db_path = settings.DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑️  Deleted existing DB: {db_path}")
    else:
        print(f"✅ No DB found at {db_path} (nothing to delete).")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS short_term_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            text TEXT,
            metadata TEXT,
            created_at REAL,
            ttl INTEGER
        )
    """)
    conn.commit()
    conn.close()
    print(f"🆕 Re-created DB: {db_path}")

def reset_itsm():
    itsm_path = settings.ITSM_PATH
    os.makedirs(os.path.dirname(itsm_path), exist_ok=True)
    seed = [{"id": "CHG-1000", "state": "Scheduled", "desc": "Initial seed change"}]
    with open(itsm_path, "w") as f:
        json.dump(seed, f, indent=2)
    print(f"🆕 Recreated ITSM file with 1 seed record at {itsm_path}")

if __name__ == "__main__":
    print("🔄 Resetting Resource Hub data...")
    reset_sqlite()
    reset_itsm()
    print("✅ Reset complete.")
