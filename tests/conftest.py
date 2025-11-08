# tests/conftest.py
import pytest
import asyncio
import sys
from pathlib import Path
PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# async-compatible fake that mimics get_api_key and always returns the valid key
async def _fake_get_api_key(*args, **kwargs):
    return "mysecretapikey"

# List of module names we expect to exist in this repo that expose a FastAPI `app`.
_SERVICE_MODULES = [
    "guardian_service",
    "manager_service",
    "partner_service",
    "resource_hub_service",
    "overseer_service",
    "directory_service",
]

@pytest.fixture(autouse=True)
def override_api_key_dependency(monkeypatch):
    """
    Autouse fixture that tries to import each service module and, if found,
    injects a dependency override so that the FastAPI app will accept requests
    without the real API header.

    This does NOT modify security.py; it only changes test-time app dependency
    resolution via `app.dependency_overrides`.
    """
    for mod_name in _SERVICE_MODULES:
        try:
            mod = __import__(mod_name)
        except Exception:
            # Module might not be imported/needed for some tests — ignore failures.
            continue

        # Most services define `app` at module level.
        app = getattr(mod, "app", None)
        if app is None:
            continue

        # The original dependency function object used by Depends(...) is
        # security.get_api_key (or similar). We set an override for any callable
        # that matches the original reference name from the security module if available.
        try:
            import security
            # override specifically the original security.get_api_key callable
            if hasattr(security, "get_api_key"):
                app.dependency_overrides[security.get_api_key] = _fake_get_api_key
            else:
                # fallback: override any dependency key named 'get_api_key' if present
                # (this is defensive; most repos will hit the branch above)
                for k in list(app.dependency_overrides.keys()):
                    if getattr(k, "__name__", "") == "get_api_key":
                        app.dependency_overrides[k] = _fake_get_api_key
        except Exception:
            # If the security module import or override fails, keep going.
            continue

    # Also monkeypatch the security.get_api_key in case some tests call it directly.
    try:
        import security
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(security, "get_api_key", _fake_get_api_key, raising=False)
        yield
        monkeypatch.undo()
    except Exception:
        # if import failed, just yield to run tests normally (they'll fail if auth is required)
        yield
