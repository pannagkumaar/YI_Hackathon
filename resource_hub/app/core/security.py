# 📄 security.py
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

API_KEY = "mysecretapikey" # This is your shared secret
API_KEY_NAME = "X-SHIVA-SECRET"

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