from fastapi import Header, HTTPException, status
from core.config import settings

def verify_auth(authorization: str = Header(...)):
    try:
        scheme, token = authorization.split()
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid auth header format")
    if scheme.lower() != "bearer" or token != settings.SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")
