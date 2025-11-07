# 📄 security.py
# (This is a copy of the security.py from your project root)

from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

# --- INTEGRATION FIX ---
# Use the *exact same* key and header name as your other services
API_KEY = "mysecretapikey" 
API_KEY_NAME = "X-SHIVA-SECRET"
# --- END FIX ---

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def get_api_key(api_key: str = Security(api_key_header)):
    """Checks for the presence and validity of the shared secret."""
    if api_key == API_KEY:
        return api_key
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )