import requests, time
from core.config import settings

_cache = {}
_cache_expiry = {}

def discover(service_name: str):
    now = time.time()
    if service_name in _cache and now < _cache_expiry.get(service_name, 0):
        return _cache[service_name]
    try:
        resp = requests.get(f"{settings.DIRECTORY_URL}/discover?service={service_name}", timeout=2)
        data = resp.json()
        _cache[service_name] = data["base_url"]
        _cache_expiry[service_name] = now + 300
        return data["base_url"]
    except Exception:
        return None
