import requests
import json
import time
from colorama import Fore, Style

DIRECTORY_URL = "http://localhost:8005"
GUARDIAN_URL = "http://localhost:8006"
RESOURCE_HUB_URL = "http://localhost:8007"
HEADERS = {"X-SHIVA-SECRET": "mysecretapikey"}


def section(title):
    print(f"\n{Fore.CYAN}=== {title} ==={Style.RESET_ALL}")


def print_result(label, result):
    color = Fore.GREEN if "Allow" in result or "Fetched" in result else Fore.RED
    print(f"{color}{label}: {result}{Style.RESET_ALL}")


def test_discovery():
    """Verify Guardian can discover Resource Hub in Directory."""
    section("1️⃣ Service Discovery Check")
    try:
        r = requests.get(f"{DIRECTORY_URL}/list", headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        if "guardian" in data and "resource_hub" in data:
            print_result("✅ Directory entries", "Both services registered")
        else:
            print_result("❌ Directory entries", "Missing one of the services")
        return data
    except Exception as e:
        print_result("❌ Discovery error", str(e))


def test_policy_fetch():
    """Confirm Guardian can contact Resource Hub to fetch policies."""
    section("2️⃣ Guardian Fetch Policies from Resource Hub")
    payload = {"task_id": "fetch1", "proposed_action": "delete temp file", "context": {}}

    try:
        res = requests.post(f"{GUARDIAN_URL}/guardian/validate_action",
                            json=payload, headers=HEADERS, timeout=5)
        print(f"Response: {res.status_code} → {res.text}")
        if "Disallow" in res.text or "policy" in res.text.lower():
            print_result("✅ Policy fetch", "Guardian is using Resource Hub policies")
        else:
            print_result("⚠️ Policy fetch", "Guardian did not reference any policy rules")
    except Exception as e:
        print_result("❌ Policy fetch error", str(e))


def test_policy_enforcement():
    """Send safe and dangerous actions to Guardian to verify decision logic."""
    section("3️⃣ Guardian Enforcement Test")

    # Safe action
    safe_action = {"task_id": "safe1", "proposed_action": "list logs", "context": {}}
    r_safe = requests.post(f"{GUARDIAN_URL}/guardian/validate_action",
                           json=safe_action, headers=HEADERS)
    print(f"Safe → {r_safe.status_code}: {r_safe.text}")

    # Dangerous action
    risky_action = {"task_id": "risky1", "proposed_action": "rm -rf /", "context": {}}
    r_risky = requests.post(f"{GUARDIAN_URL}/guardian/validate_action",
                            json=risky_action, headers=HEADERS)
    print(f"Risky → {r_risky.status_code}: {r_risky.text}")

    if "Deny" in r_risky.text and "Allow" in r_safe.text:
        print_result("✅ Enforcement", "Guardian correctly enforced policies")
    else:
        print_result("⚠️ Enforcement", "Guardian enforcement not consistent")


def test_policy_list_from_hub():
    """Verify that Resource Hub can return the current policy list."""
    section("4️⃣ Resource Hub Policy List Check")
    try:
        res = requests.get(f"{RESOURCE_HUB_URL}/policy/list", headers=HEADERS)
        print(f"Response: {res.status_code} → {res.text[:200]}...")
        if res.ok and "Disallow" in res.text:
            print_result("✅ Resource Hub policies", "Policies returned successfully")
        else:
            print_result("⚠️ Resource Hub policies", "Empty or inaccessible policy list")
    except Exception as e:
        print_result("❌ Policy list error", str(e))


def main():
    print(f"{Fore.YELLOW}\n🚀 Guardian ↔ Resource Hub Integration Validation\n{Style.RESET_ALL}")
    test_discovery()
    test_policy_list_from_hub()
    time.sleep(1)
    test_policy_fetch()
    time.sleep(1)
    test_policy_enforcement()
    print(f"\n{Fore.GREEN}✅ Test run complete. Review all ❌ or ⚠️ for missing links.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
