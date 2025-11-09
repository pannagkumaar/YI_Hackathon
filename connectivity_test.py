#!/usr/bin/env python3
import requests
import json
import time
from colorama import Fore, Style, init

init(autoreset=True)

SHARED_SECRET = "mysecretapikey"

# Define all service URLs (Docker-mapped ports)
SERVICES = {
    "directory": "http://localhost:8005",
    "overseer": "http://localhost:8002",
    "manager": "http://localhost:8003",
    "partner": "http://localhost:8004",
    "guardian": "http://localhost:8006",
    "resource_hub": "http://localhost:8007"
}

def print_header(title):
    print(Fore.CYAN + f"\n=== {title} ===" + Style.RESET_ALL)

def safe_get(url, headers=None):
    try:
        r = requests.get(url, headers=headers, timeout=5)
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)

def safe_post(url, json_data=None):
    try:
        r = requests.post(url, json=json_data, headers={"X-SHIVA-SECRET": SHARED_SECRET}, timeout=100)
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)

def health_check():
    print_header("1️⃣ HEALTH CHECK")
    for name, url in SERVICES.items():
        endpoint = f"{url}/healthz"
        status, body = safe_get(endpoint)
        if status == 200:
            print(Fore.GREEN + f"✅ {name:<12} → {endpoint} OK" + Style.RESET_ALL)
        elif status == 404:
            print(Fore.YELLOW + f"⚠️  {name:<12} → {endpoint} (404 Not Found)" + Style.RESET_ALL)
        else:
            print(Fore.RED + f"❌ {name:<12} → {endpoint} failed ({body})" + Style.RESET_ALL)

def directory_check():
    print_header("2️⃣ DIRECTORY REGISTRATION")
    url = f"{SERVICES['directory']}/list"
    try:
        r = requests.get(url, headers={"X-SHIVA-SECRET": SHARED_SECRET}, timeout=5)
        data = r.json()
        print(json.dumps(data, indent=2))
        for name in ["overseer", "guardian", "partner", "manager", "resource_hub"]:
            if any(k.startswith(name) for k in data.keys()):
                print(Fore.GREEN + f"✅ Registered: {name}" + Style.RESET_ALL)
            else:
                print(Fore.RED + f"❌ Missing: {name}" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.RED + f"❌ Directory unreachable: {e}")

def overseer_test():
    print_header("3️⃣ OVERSEER LOGGING")
    url = f"{SERVICES['overseer']}/log/event"
    payload = {
        "service": "test-suite",
        "task_id": "integration-check",
        "level": "INFO",
        "message": "Integration test log",
        "context": {"phase": "logging-test"}
    }
    status, body = safe_post(url, payload)
    if status == 201:
        print(Fore.GREEN + f"✅ Overseer log accepted (201)" + Style.RESET_ALL)
    else:
        print(Fore.YELLOW + f"⚠️ Overseer log response: {status} → {body}" + Style.RESET_ALL)

def guardian_test():
    print_header("4️⃣ GUARDIAN POLICY VALIDATION")
    safe_action = {"task_id": "safe1", "proposed_action": "list logs", "context": {}}
    risky_action = {"task_id": "risky1", "proposed_action": "rm -rf /", "context": {}}

    for test_case, payload in [("SAFE", safe_action), ("RISKY", risky_action)]:
        status, body = safe_post(f"{SERVICES['guardian']}/guardian/validate_action", payload)
        if status == 200:
            print(Fore.GREEN + f"✅ Guardian {test_case:<6} → allowed (200)")
        elif status == 403:
            print(Fore.RED + f"🛑 Guardian {test_case:<6} → blocked (403)")
        else:
            print(Fore.YELLOW + f"⚠️ Guardian {test_case:<6} → {status} {body}")

def resource_hub_test():
    print_header("5️⃣ RESOURCE HUB FUNCTIONALITY")

    # Tools
    status, tools_body = safe_get(f"{SERVICES['resource_hub']}/tools/list", headers={"X-SHIVA-SECRET": SHARED_SECRET})
    tools = []
    if status == 200:
        tools = json.loads(tools_body).get("tools", [])
        print(Fore.GREEN + f"✅ Tools list: {len(tools)} tools available")
    else:
        print(Fore.YELLOW + f"⚠️ Tools endpoint returned {status}")

    # Policies
    status, policies_body = safe_get(f"{SERVICES['resource_hub']}/policy/list", headers={"X-SHIVA-SECRET": SHARED_SECRET})
    if status == 200:
        print(Fore.GREEN + f"✅ Policies list: {policies_body[:80]}")
    else:
        print(Fore.YELLOW + f"⚠️ Policy list returned {status}")

    # RAG query test
    query_payload = {"question": "What tool can summarize text?"}
    status, rag_body = safe_post(f"{SERVICES['resource_hub']}/rag/query", query_payload)
    if status == 200:
        print(Fore.GREEN + f"✅ RAG query success: {rag_body[:100]}")
    else:
        print(Fore.YELLOW + f"⚠️ RAG query failed ({status}) → {rag_body}")

def manager_task_test():
    print_header("6️⃣ MANAGER TASK CREATION")
    payload = {"goal": "Verify system flow", "context": {"source": "integration-test"}}
    status, body = safe_post(f"{SERVICES['manager']}/task/create", payload)
    if status == 200 or status == 201:
        print(Fore.GREEN + f"✅ Task created successfully")
    else:
        print(Fore.YELLOW + f"⚠️ Task creation failed → {status} {body}")

def final_summary():
    print_header("✅ TEST RUN COMPLETE")
    print("All key interactions validated. Review ⚠️ or ❌ for issues.")
    print("Use `docker logs` on failing containers for detailed traces.")

if __name__ == "__main__":
    print(Fore.YELLOW + "\n🚀 Starting SHIVA Docker Integration Test\n" + Style.RESET_ALL)
    health_check()
    directory_check()
    overseer_test()
    guardian_test()
    resource_hub_test()
    manager_task_test()
    final_summary()
