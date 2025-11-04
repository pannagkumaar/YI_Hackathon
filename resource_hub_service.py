# 📄 resource_hub_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uvicorn
import requests
import threading
import time
from security import get_api_key # Import our new auth function

# --- Authentication & Service Constants ---
app = FastAPI(
    title="Resource Hub Service",
    description="Provides tools, policies, and memory for SHIVA agents.",
    dependencies=[Depends(get_api_key)] # Apply auth to all endpoints
)

API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
DIRECTORY_URL = "http://localhost:8005"
SERVICE_NAME = "resource-hub-service"
SERVICE_PORT = 8006 # New port
# --- End Authentication & Service Constants ---

# --- Mock Database ---
MOCK_POLICIES = {
    "global": [
        "Disallow: delete",
        "Disallow: shutdown",
        "Disallow: rm -rf"
    ]
}
MOCK_TOOLS = {
    "tools": [
        {"name": "run_script", "description": "Executes a python script."},
        {"name": "fetch_data", "description": "Fetches data from an API."}
    ]
}
# --- End Mock Database ---


# --- Service Discovery & Logging (Copied from Manager) ---
def discover(service_name: str) -> str:
    """Finds a service's URL from the Directory."""
    print(f"[ResourceHub] Discovering: {service_name}")
    try:
        r = requests.get(
            f"{DIRECTORY_URL}/discover",
            params={"service_name": service_name},
            headers=AUTH_HEADER # Auth
        )
        if r.status_code != 200:
            print(f"[ResourceHub] FAILED to discover {service_name}.")
            raise HTTPException(500, detail=f"Could not discover {service_name}")
        url = r.json()["url"]
        print(f"[ResourceHub] Discovered {service_name} at {url}")
        return url
    except requests.exceptions.ConnectionError:
        print(f"[ResourceHub] FAILED to connect to Directory at {DIRECTORY_URL}")
        raise HTTPException(500, detail="Could not connect to Directory Service")

def log_to_overseer(task_id: str, level: str, message: str, context: dict = {}):
    """Sends a log entry to the Overseer service."""
    try:
        overseer_url = discover("overseer-service")
        requests.post(f"{overseer_url}/log/event", json={
            "service": SERVICE_NAME,
            "task_id": task_id,
            "level": level,
            "message": message,
            "context": context
        }, headers=AUTH_HEADER) # Auth
    except Exception as e:
        print(f"[ResourceHub] FAILED to log to Overseer: {e}")
# --- End Service Discovery & Logging ---

# --- Service Registration (Copied from Manager) ---
def register_self():
    """Registers this service with the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        try:
            r = requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER) # Auth
            if r.status_code == 200:
                print(f"[ResourceHub] Successfully registered with Directory at {DIRECTORY_URL}")
                threading.Thread(target=heartbeat, daemon=True).start()
                break
            else:
                print(f"[ResourceHub] Failed to register. Status: {r.status_code}. Retrying in 5s...")
        except requests.exceptions.ConnectionError:
            print(f"[ResourceHub] Could not connect to Directory. Retrying in 5s...")
        time.sleep(5)

def heartbeat():
    """Sends a periodic heartbeat to the Directory."""
    service_url = f"http://localhost:{SERVICE_PORT}"
    while True:
        time.sleep(45)
        try:
            requests.post(f"{DIRECTORY_URL}/register", json={
                "service_name": SERVICE_NAME,
                "service_url": service_url,
                "ttl_seconds": 60
            }, headers=AUTH_HEADER) # Auth
            print("[ResourceHub] Heartbeat sent to Directory.")
        except requests.exceptions.ConnectionError:
            print("[ResourceHub] Failed to send heartbeat. Will retry registration.")
            register_self()
            break

@app.on_event("startup")
def on_startup():
    threading.Thread(target=register_self, daemon=True).start()
# --- End Service Registration ---


# --- API Endpoints ---
@app.get("/policy/list", status_code=200)
def get_policies(context: str = "global"):
    """Fetch compliance policies."""
    log_to_overseer("N/A", "INFO", f"Policy list requested for context: {context}")
    return {"policies": MOCK_POLICIES.get(context, [])}

@app.get("/tools/list", status_code=200)
def get_tools():
    """Fetch available tools for agents."""
    log_to_overseer("N/A", "INFO", "Tool list requested.")
    return MOCK_TOOLS

if __name__ == "__main__":
    print(f"Starting Resource Hub Service on port {SERVICE_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)