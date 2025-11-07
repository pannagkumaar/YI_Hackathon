import os
import sqlite3
import pytest
from fastapi.testclient import TestClient
import random
import sys
import types

# --------------------------------------------------------------------------
# CRITICAL FIX: PATCH EMBEDDING MODULE BEFORE APP IMPORT
# This code runs before 'from main import app', ensuring the model never loads.
# --------------------------------------------------------------------------

# Define mock functions (MiniLM uses 384 dimensions)
def mock_embed_texts(texts, model_name=None):
    # Returns random vectors of the expected dimension
    return [[random.uniform(-1, 1) for _ in range(384)] for _ in texts]

def mock_embed_text(text, model_name=None):
    # Returns a single random vector
    return [random.uniform(-1, 1) for _ in range(384)]

# 1. Create a dummy module
dummy_embeddings = types.ModuleType("app.core.embeddings")
dummy_embeddings.embed_texts = mock_embed_texts
dummy_embeddings.embed_text = mock_embed_text
dummy_embeddings.get_model = lambda *args, **kwargs: None 

# 2. Manually insert the dummy module into sys.modules 
# This tells Python to use our mock whenever the app tries to import 'app.core.embeddings'
sys.modules['app.core.embeddings'] = dummy_embeddings
sys.modules['resource_hub.app.core.embeddings'] = dummy_embeddings # Patch both possible paths


# Now, import the application and its dependencies, which will safely use the mocked module
from main import app 
from app.core import config, db

# --------------------------------------------------------------------------
# END CRITICAL FIX
# --------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client(tmp_path, monkeypatch):
    """
    Creates a TestClient using a fresh temporary DB for each test.
    The embeddings are already mocked globally via sys.modules.
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