# 📄 directory_service.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta
import uvicorn
from security import get_api_key # Import our new auth function

app = FastAPI(
    title="Directory Service",
    description="Central registry for all SHIVA services.",
    dependencies=[Depends(get_api_key)] # Apply auth to all endpoints
)

# In-memory database for services
services = {}

class ServiceRegistration(BaseModel):
    service_name: str
    service_url: str
    ttl_seconds: int = 300

class ServiceName(BaseModel):
    service_name: str

@app.post("/register", status_code=200)
def register(reg: ServiceRegistration):
    """Register a new service or update its heartbeat."""
    service_name = reg.service_name
    services[service_name] = {
        "url": reg.service_url,
        "last_seen": datetime.now(),
        "expires_at": datetime.now() + timedelta(seconds=reg.ttl_seconds)
    }
    print(f"[Directory] Registered/Updated: {service_name} at {reg.service_url}")
    return {"status": "Registered", "service_name": service_name, "url": reg.service_url}

@app.post("/deregister", status_code=200)
def deregister(name: ServiceName):
    """Deregister a service."""
    service_name = name.service_name
    if service_name in services:
        services.pop(service_name, None)
        print(f"[Directory] Deregistered: {service_name}")
        return {"status": "Deregistered", "service_name": service_name}
    return {"status": "Not found", "service_name": service_name}

@app.get("/discover", status_code=200)
def discover(service_name: str):
    """Discover the URL for a given service."""
    svc = services.get(service_name)
    
    if not svc:
        print(f"[Directory] Discovery FAILED: {service_name} not found.")
        raise HTTPException(404, detail=f"Service '{service_name}' not found")
        
    if svc["expires_at"] < datetime.now():
        print(f"[Directory] Discovery FAILED: {service_name} expired.")
        services.pop(service_name, None) # Clean up expired service
        raise HTTPException(404, detail=f"Service '{service_name}' found but registration is expired")
    
    print(f"[Directory] Discovery SUCCESS: {service_name} -> {svc['url']}")
    return {"service_name": service_name, "url": svc["url"]}

@app.get("/list", status_code=200)
def list_services():
    """List all currently registered and active services."""
    now = datetime.now()
    active_services = {
        name: data for name, data in services.items() 
        if data["expires_at"] > now
    }
    return active_services

@app.get("/healthz", dependencies=[], tags=["System"])
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}

if __name__ == "__main__":
    print("Starting Directory Service on port 8005...")
    uvicorn.run(app, host="0.0.0.0", port=8005)