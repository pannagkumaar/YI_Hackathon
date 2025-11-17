import requests, time, asyncio
from app.core.config import settings
from core.logging_client import send_log

# --- Integration Fix ---
# Define the authentication header using the shared secret from settings
AUTH_HEADER = {"X-SHIVA-SECRET": settings.SHARED_SECRET}
# --- End Integration Fix ---

_cache = {}
_cache_expiry = {}

def discover(service_name: str):
    now = time.time()
    if service_name in _cache and now < _cache_expiry.get(service_name, 0):
        return _cache[service_name]
    if not settings.DIRECTORY_URL:
        return None
    try:
        # --- Integration Fix ---
        # Add auth header to discovery calls as well
        resp = requests.get(
            f"{settings.DIRECTORY_URL}/discover", 
            params={"service_name": service_name}, 
            timeout=2,
            headers=AUTH_HEADER
        )
        # --- End Integration Fix ---
        
        resp.raise_for_status()
        data = resp.json()
        # Directory may use 'url' or 'service_url' keys
        base = data.get("service_url") or data.get("url") or data.get("service_url")
        _cache[service_name] = base
        _cache_expiry[service_name] = now + 300
        return base
    except Exception as e:
        # optionally log failure
        send_log(settings.SERVICE_NAME, None, "WARN", f"Discovery failed for {service_name}: {e}")
        return None

def register_once():
    # register once - synchronous best-effort
    if not settings.DIRECTORY_URL:
        return False
    payload = {
        "service_name": settings.SERVICE_NAME,
        "service_url": settings.SERVICE_BASE_URL,
        "ttl_seconds": settings.DIRECTORY_TTL
    }
    try:
        # --- Integration Fix ---
        # Add the authentication header to the registration POST
        requests.post(
            f"{settings.DIRECTORY_URL}/register", 
            json=payload, 
            timeout=2,
            headers=AUTH_HEADER
        )
        # --- End Integration Fix ---
        send_log(settings.SERVICE_NAME, None, "INFO", "Registered with Directory")
        return True
    except Exception as e:
        send_log(settings.SERVICE_NAME, None, "WARN", f"Register attempt failed: {e}")
        return False

async def start_heartbeat_loop():
    # start by attempting registration, then periodically refresh registration
    loop_interval = max(30, settings.DIRECTORY_TTL // 2)
    # initial attempt
    register_once()
    while True:
        try:
            payload = {
                "service_name": settings.SERVICE_NAME,
                "service_url": settings.SERVICE_BASE_URL,
                "ttl_seconds": settings.DIRECTORY_TTL
            }
            try:
                # --- Integration Fix ---
                # Add the authentication header to the heartbeat POST
                requests.post(
                    f"{settings.DIRECTORY_URL}/register", 
                    json=payload, 
                    timeout=2,
                    headers=AUTH_HEADER
                )
                # --- End Integration Fix ---
                send_log(settings.SERVICE_NAME, None, "DEBUG", "Heartbeat: re-registered with Directory")
            except Exception as e:
                send_log(settings.SERVICE_NAME, None, "WARN", f"Heartbeat failed: {e}")
        except Exception:
            pass
        await asyncio.sleep(loop_interval)