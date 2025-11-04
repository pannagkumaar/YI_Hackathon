import requests
import json
import time

MANAGER_URL = "http://localhost:8001"
OVERSEER_URL = "http://localhost:8004"

def print_header(title):
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)

def test_discovery():
    print_header("Test: Directory Discovery")
    try:
        r = requests.get("http://localhost:8005/list")
        r.raise_for_status()
        print("✅ Directory is online. Registered services:")
        print(json.dumps(r.json(), indent=2))
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED: Could not connect to Directory Service at http://localhost:8005")
        print(f"   Error: {e}")
        print("   Please ensure directory_service.py is running.")
        return False

def test_invoke():
    print_header("Test: Manager /invoke")
    try:
        payload = {
            "goal": "Deploy new model version 1.2.3 to production",
            "context": {"user": "admin", "priority": "high"}
        }
        response = requests.post(f"{MANAGER_URL}/invoke", json=payload)
        
        if response.status_code == 202:
            print("✅ Success! Manager accepted the task.")
            print("Response:")
            print(json.dumps(response.json(), indent=2))
        elif response.status_code == 503:
            print("⚠️ Task Rejected: System is in HALT state.")
            print("   Running kill-switch test...")
            test_kill_switch()
        else:
            print(f"❌ Error! Status Code: {response.status_code}")
            print(response.text)

    except requests.exceptions.ConnectionError as e:
        print(f"❌ FAILED: Could not connect to Manager Service at {MANAGER_URL}")
        print("   Please ensure all 5 services are running.")

def test_kill_switch():
    print_header("Test: Overseer Kill-Switch")
    
    # 1. Activate Kill Switch
    try:
        print("Activating HALT command...")
        r_kill = requests.post(f"{OVERSEER_URL}/control/kill")
        r_kill.raise_for_status()
        print(f"✅ {r_kill.json().get('message')}")
        
        print("\nAttempting to invoke task while HALTED...")
        payload = {"goal": "This task should fail"}
        r_invoke = requests.post(f"{MANAGER_URL}/invoke", json=payload)
        
        if r_invoke.status_code == 503:
            print("✅ Success! Manager correctly rejected task (503 Service Unavailable).")
        else:
            print(f"❌ FAILED! Manager responded with {r_invoke.status_code} instead of 503.")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED to contact Overseer/Manager: {e}")
        
    # 2. Resume System
    finally:
        print("\nResuming system...")
        try:
            r_resume = requests.post(f"{OVERSEER_URL}/control/resume")
            r_resume.raise_for_status()
            print(f"✅ {r_resume.json().get('message')}")
        except requests.exceptions.RequestException as e:
            print(f"❌ FAILED to resume system: {e}")

if __name__ == "__main__":
    print("Waiting 3 seconds for services to boot...")
    time.sleep(3)
    
    if test_discovery():
        test_invoke()
        test_kill_switch()
        
    print("\n" + "="*50)
    print("Test complete. Check all 5 service terminals")
    print("to see the full log of interactions!")
    print("="*50)
