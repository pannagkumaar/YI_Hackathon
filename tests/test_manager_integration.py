# tests/test_manager_integration.py
import pytest
from fastapi.testclient import TestClient
import manager_service as ms
import guardian_service as gs
import directory_service as ds
import resource_hub_service as rh

# Create TestClients for in-process apps
client_dir = TestClient(ds.app)
client_guardian = TestClient(gs.app)
client_manager = TestClient(ms.app)
client_rh = TestClient(rh.app)

@pytest.fixture(autouse=True)
def register_services(monkeypatch):
    """
    Monkeypatch discover() or Directory endpoints so manager/guardian/resource hub find each other.
    We'll monkeypatch the DIRECTORY_URL in managers/guardian/resourcehub modules to point to a test client base.
    Simpler: stub out discover() used in each module to return the local TestClient base URL.
    """
    # stub discover in modules to return a fake URL base; manager uses 'discover' function expecting http URL.
    monkeypatch.setattr("manager_service.DIRECTORY_URL", "http://test-directory")
    monkeypatch.setattr("guardian_service.DIRECTORY_URL", "http://test-directory")
    monkeypatch.setattr("resource_hub_service.DIRECTORY_URL", "http://test-directory")
    # Also monkeypatch discover() function used in modules to call local test endpoints.
    def fake_discover(name):
        mapping = {
            "guardian-service": "http://test-guardian",
            "resource-hub-service": "http://test-rh",
            "overseer-service": "http://test-overseer",
            "manager-service": "http://test-manager"
        }
        return mapping.get(name, "http://test-unknown")
    monkeypatch.setattr("manager_service.discover", lambda client, name: fake_discover(name))
    monkeypatch.setattr("partner_service.discover_async", lambda client, name: fake_discover(name))
    monkeypatch.setattr("guardian_service.discover", lambda name: fake_discover(name))
    monkeypatch.setattr("resource_hub_service.discover", lambda name: fake_discover(name))

    # stub fetch_policies to return a predictable policy set
    monkeypatch.setattr("guardian_service.fetch_policies_from_hub", lambda ctx="global": ["Disallow: delete"])

    yield
