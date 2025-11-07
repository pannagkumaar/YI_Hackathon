# 📄 test_invoke.py
import requests
import json
import time

MANAGER_URL = "http://localhost:8001"
OVERSEER_URL = "http://localhost:8004"
DIRECTORY_URL = "http://localhost:8005"

# --- Authentication ---
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
# ---

def print_header(title):
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)

def test_discovery():
    print_header("Test: Directory Discovery")
    try:
        r = requests.get(f"{DIRECTORY_URL}/list", headers=AUTH_HEADER)
        r.raise_for_status()
        print("✅ Directory is online. Registered services (should be 5):")
        print(json.dumps(r.json(), indent=2))
        
        # --- THE FIX IS HERE ---
        # The list contains 5 services (not 6, because the Directory doesn't list itself)
        if len(r.json()) < 5:
             print("⚠️  WARNING: Not all 5 services are registered.")
             print("   Ensure Manager, Partner, Guardian, Overseer, and Resource Hub are running.")
             return False
        
        print("✅ All 5 services are registered with the Directory.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED: Could not connect to Directory Service at {DIRECTORY_URL}")
        print(f"   Error: {e}")
        return False

# --- UPDATED: test_invoke for async manager ---
def test_invoke():
    print_header("Test: Manager /invoke (Async)")
    
    # NEW INSTRUCTION
    print("--- 💡 OPEN THIS IN YOUR BROWSER NOW! ---")
    print(f"--- http://localhost:{OVERSEER_URL.split(':')[-1]} ---")
    print("------------------------------------------")
    time.sleep(2) # Give user time to read
    
    try:
        payload = {
            "goal": "should we shutdown system now?",
            "context": {"user": "admin", "priority": "high"}
        }
        # 1. Send the initial request
        response = requests.post(
            f"{MANAGER_URL}/invoke",
            json=payload,
            headers=AUTH_HEADER
        )
        response.raise_for_status()
        
        if response.status_code == 202:
            print("✅ Success! Manager accepted the task (202 Accepted).")
            data = response.json()
            task_id = data.get("task_id")
            status_url = f"{MANAGER_URL}{data.get('status_url')}"
            print(f"   Task ID: {task_id}")
            print(f"   Status URL: {status_url}")
            
            # 2. Poll the status URL
            print("\nPolling task status... (Check the Overseer dashboard!)")
            current_status = ""
            while current_status not in ["COMPLETED", "REJECTED", "FAILED", "PAUSED_DEVIATION"]:
                time.sleep(0.5)
                r_status = requests.get(status_url, headers=AUTH_HEADER)
                status_data = r_status.json()
                new_status = status_data.get("status")
                
                if new_status != current_status:
                    current_status = new_status
                    print(f"   [Task: {task_id}] Status updated to: {current_status}")
            
            print("\n--- Final Task Status ---")
            print(json.dumps(status_data, indent=2))
            print("-------------------------")

        elif response.status_code == 503:
            print("⚠️ Task Rejected: System is in HALT state.")
            print("   Running kill-switch test...")
            test_kill_switch()
        else:
            print(f"❌ Error! Status Code: {response.status_code}")
            print(response.text)

    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED: Could not connect to Manager Service at {MANAGER_URL}")
        print(f"   Error: {e}")
        print("   Please ensure all 6 services are running.")

# --- test_kill_switch (no change, but ensure it runs after) ---
def test_kill_switch():
    print_header("Test: Overseer Kill-Switch")
    
    try:
        print("Activating HALT command...")
        r_kill = requests.post(f"{OVERSEER_URL}/control/kill", headers=AUTH_HEADER) # Auth
        r_kill.raise_for_status()
        print(f"✅ {r_kill.json().get('message')}")
        
        print("\nAttempting to invoke task while HALTED...")
        payload = {"goal": "This task should fail"}
        r_invoke = requests.post(
            f"{MANAGER_URL}/invoke",
            json=payload,
            headers=AUTH_HEADER
        )
        
        if r_invoke.status_code == 202:
            print("✅ Manager accepted task (202). Now polling for 'REJECTED' status...")
            task_id = r_invoke.json().get("task_id")
            status_url = f"{MANAGER_URL}{r_invoke.json().get('status_url')}"
            
            time.sleep(1) # Give background task time to check status
            
            r_status = requests.get(status_url, headers=AUTH_HEADER)
            status_data = r_status.json()
            
            if status_data.get("status") == "REJECTED":
                print("✅ Success! Background task correctly rejected (HALT state).")
                print(json.dumps(status_data, indent=2))
            else:
                print(f"❌ FAILED! Task status is {status_data.get('status')}, expected REJECTED.")
                
        else:
            print(f"❌ FAILED! Manager responded with {r_invoke.status_code} instead of 202.")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED to contact Overseer/Manager: {e}")
        
    finally:
        print("\nResuming system...")
        try:
            r_resume = requests.post(f"{OVERSEER_URL}/control/resume", headers=AUTH_HEADER)
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
    print("Test complete. Check all 6 service terminals")
    print("and the Overseer dashboard at http://localhost:8004")
    print("to see the full log of interactions!")
    print("="*50)