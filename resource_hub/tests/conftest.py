import os
import sqlite3
import pytest
from fastapi.testclient import TestClient
from main import app
from app.core import config, db

@pytest.fixture(scope="function")
def client(tmp_path, monkeypatch):
    """
    Create a TestClient using a fresh temporary DB for each test.
    """
    # create a temp DB path
    tmp_db_path = tmp_path / "test.db"

    # override DB_PATH in settings
    monkeypatch.setattr(config.settings, "DB_PATH", str(tmp_db_path))

    # re-initialize the database on this new file
    db.init_db()

    # Return the test client
    with TestClient(app) as c:
        yield c

    # cleanup after test
    if os.path.exists(tmp_db_path):
        os.remove(tmp_db_path)
