# resource_hub/app/routers/policy_router.py
from fastapi import APIRouter, Depends
from app.core.security import get_api_key # Use the new security file
from core.logging_client import send_log
from app.core.config import settings

router = APIRouter(
    prefix="/policy", 
    tags=["Policy"],
    dependencies=[Depends(get_api_key)] # Secure this router
)

# Mock Database for policies, just like your old hub
POLICY_DB = {
    "global": [
        "Disallow: delete",
        "Disallow: shutdown",
        "Disallow: rm -rf"
    ]
}

@router.get("/list", status_code=200)
def get_policies(context: str = "global"):
    """
    (Compatibility) Provides the policy list that the 
    Guardian service depends on.
    """
    send_log(settings.SERVICE_NAME, None, "INFO", "Policy list requested")
    return {"policies": POLICY_DB.get(context, [])}