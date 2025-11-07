from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException
from app.core.config import settings

OPEN_PATHS = ["/health", "/open"]

class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow open paths
        path = request.url.path
        if any(path.startswith(p) for p in OPEN_PATHS):
            return await call_next(request)

        auth = request.headers.get("authorization")
        if not auth or not auth.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        token = auth.split(" ", 1)[1].strip()
        if token != settings.SHARED_SECRET:
            raise HTTPException(status_code=401, detail="Invalid token")

        request.state.task_id = None
        # Extract task_id lightly for JSON bodies
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
                if isinstance(body, dict):
                    request.state.task_id = body.get("task_id")
            except Exception:
                request.state.task_id = None

        return await call_next(request)
