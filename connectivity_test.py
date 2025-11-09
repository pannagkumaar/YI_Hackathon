import requests
import time
import json
from colorama import Fore, Style

SERVICES = {
    "directory": "http://localhost:8005",
    "overseer": "http://localhost:8002",
    "manager": "http://localhost:8003",
    "partner": "http://localhost:8004",
    "guardian": "http://localhost:8006",
    "resource_hub": "http://localhost:8007",
}

HEADERS = {"X-SHIVA-SECRET": "mysecretapikey"}

def check(endpoint, name):
    """Helper for GET health endpoints."""
    try:
        res = requests.get(endpoint, headers=HEADERS, timeout=5)
        if res.ok:
            print(f"{Fore.GREEN}✅ {name:<15} → {endpoint} OK{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}❌ {name:<15} → {endpoint} ({res.status_code}){Style.RESET_ALL}")
            return False
    except Exception as e:
        print(f"{Fore.RED}❌ {name:<15} → {endpoint} ({e}){Style.RESET_ALL}")
        return False


def section(title):
    print(f"\n{Fore.CYAN}=== {title} ==={Style.RESET_ALL}")


def main():
    print(f"\n{Fore.YELLOW}🚀 Starting SHIVA Docker Integration Test{Style.RESET_ALL}\n")

    # 1️⃣ Service Health Checks
    section("Health Check")
    for name, base in SERVICES.items():
        check(f"{base}/healthz", name)

    # 2️⃣ Directory registration verification
    section("Directory Registration")
    try:
        res = requests.get(f"{SERVICES['directory']}/list", headers=HEADERS)
        data = res.json()
        print(json.dumps(data, indent=2))
        for s in ["overseer", "manager", "partner", "guardian", "resource_hub"]:
            if s in data:
                print(f"{Fore.GREEN}✅ Registered: {s}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}❌ Missing: {s}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Error fetching Directory list: {e}{Style.RESET_ALL}")

    # 3️⃣ Overseer log event test
    section("Overseer Logging Test")
    payload = {
        "service": "manager",
        "task_id": "integration-demo",
        "level": "INFO",
        "message": "Integration test log event",
    }
    try:
        r = requests.post(f"{SERVICES['overseer']}/log/event", json=payload, headers=HEADERS)
        print(f"Overseer log status: {r.status_code} → {r.text}")
    except Exception as e:
        print(f"{Fore.RED}Logging test failed: {e}{Style.RESET_ALL}")

    # 4️⃣ Resource Hub Tool & Policy tests
    section("Resource Hub Functional Test")
    try:
        tools = requests.get(f"{SERVICES['resource_hub']}/tools/list", headers=HEADERS)
        print(f"Tools: {tools.status_code} → {len(tools.json().get('tools', []))} entries")
        policies = requests.get(f"{SERVICES['guardian']}/policy/list", headers=HEADERS)
        print(f"Policies: {policies.status_code} → {len(policies.json().get('policies', []))} entries")
    except Exception as e:
        print(f"{Fore.RED}Resource Hub test failed: {e}{Style.RESET_ALL}")

    section("Guardian Policy Enforcement Test")
    try:
        payload = {"action": "delete", "context": {"resource": "critical_system"}}
        res = requests.post(f"{SERVICES['guardian']}/guardian/validate_action",
                            json=payload, headers=HEADERS)
        print(f"Validate action: {res.status_code} → {res.text}")
    except Exception as e:
        print(f"{Fore.RED}Guardian enforcement test failed: {e}{Style.RESET_ALL}")

    # 5️⃣ Manager task test
    section("Manager Task Creation")
    try:
        new_task = requests.post(
            f"{SERVICES['manager']}/task/create",
            json={"goal": "Verify integration", "context": {"mode": "integration"}},
            headers=HEADERS,
        )
        print(f"Task create: {new_task.status_code} → {new_task.text}")
    except Exception as e:
        print(f"{Fore.RED}Task creation failed: {e}{Style.RESET_ALL}")

    # 6️⃣ Partner Directory discovery test
    section("Partner Directory Discovery")
    try:
        discover = requests.get(
            f"{SERVICES['directory']}/discover?service_name=manager", headers=HEADERS
        )
        print(f"Partner discover: {discover.status_code} → {discover.text}")
    except Exception as e:
        print(f"{Fore.RED}Discovery failed: {e}{Style.RESET_ALL}")

    print(f"\n{Fore.GREEN}✅ Integration test complete. Review outputs for any ❌.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
