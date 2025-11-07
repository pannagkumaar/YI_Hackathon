# resource_hub/app/routers/policy_router.py
from fastapi import APIRouter, Depends
from app.core.security import get_api_key # Use the same security

router = APIRouter(
    prefix="/policy", 
    tags=["Policy"],
    dependencies=[Depends(get_api_key)]
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
    # This is the endpoint the Guardian is looking for
    return {"policies": POLICY_DB.get(context, [])}