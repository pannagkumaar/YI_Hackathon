# 📄 test_pause_and_approve.py
import requests
import json
import time

MANAGER_URL = "http://localhost:8001"
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}

def print_header(title):
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)

def poll_status(status_url, target_statuses, poll_interval=1, timeout=30):
    """
    Polls a task status URL until a status in target_statuses is reached
    or timeout occurs.
    """
    start_time = time.time()
    current_status = ""
    
    while time.time() - start_time < timeout:
        try:
            r_status = requests.get(status_url, headers=AUTH_HEADER)
            r_status.raise_for_status()
            status_data = r_status.json()
            new_status = status_data.get("status")

            if new_status != current_status:
                current_status = new_status
                print(f"   [Task Status] {current_status}")
            
            if current_status in target_statuses:
                return status_data
                
        except requests.exceptions.RequestException as e:
            print(f"   [Poll Error] {e}")
            
        time.sleep(poll_interval)
        
    return {"status": "TIMEOUT", "reason": "Polling timed out"}

def test_pause_and_approve():
    print_header("Test: Pause and Approve")
    
    print("--- 💡 OPEN THE OVERSEER DASHBOARD IN YOUR BROWSER! ---")
    print("--- http://localhost:8004 ---")
    print("----------------------------------------------------------")
    
    task_id = None
    try:
        # 1. Invoke a new task
        payload = {
            "goal": "Deploy new model, please try to cause a deviation",
            "context": {"user": "test_approve_script"}
        }
        response = requests.post(
            f"{MANAGER_URL}/invoke",
            json=payload,
            headers=AUTH_HEADER
        )
        response.raise_for_status()
        
        data = response.json()
        task_id = data.get("task_id")
        status_url = f"{MANAGER_URL}{data.get('status_url')}"
        print(f"✅ Task submitted. Task ID: {task_id}")
        
        # 2. Poll until it PAUSES or COMPLETES (if no deviation)
        print("\nPolling for PAUSED_DEVIATION or COMPLETED...")
        final_data = poll_status(
            status_url, 
            ["PAUSED_DEVIATION", "COMPLETED", "FAILED", "REJECTED"]
        )
        
        final_status = final_data.get("status")

        if final_status == "COMPLETED":
            print("\n⚠️  SKIPPED: Task completed without deviation.")
            print("   This is OK, it means the random choice was 'success'.")
            return
        
        if final_status in ["FAILED", "REJECTED"]:
            print(f"\n❌ FAILED: Task entered {final_status} state unexpectedly.")
            print(json.dumps(final_data, indent=2))
            return
            
        if final_status == "PAUSED_DEVIATION":
            print("\n✅ SUCCESS! Task paused due to deviation.")
            print(json.dumps(final_data, indent=2))
        
        # 3. If paused, approve the task
        print(f"\nApproving task {task_id}...")
        approve_url = f"{MANAGER_URL}/task/{task_id}/approve"
        r_approve = requests.post(approve_url, headers=AUTH_HEADER)
        r_approve.raise_for_status()
        print("✅ Task approved. Now polling for COMPLETED...")

        # 4. Poll until COMPLETED
        final_data = poll_status(
            status_url, 
            ["COMPLETED", "FAILED", "PAUSED_DEVIATION"] # It might pause again
        )

        if final_data.get("status") == "COMPLETED":
            print("\n✅✅✅ TEST SUCCEEDED! ✅✅✅")
            print("   Task was successfully paused, approved, and completed.")
        elif final_data.get("status") == "PAUSED_DEVIATION":
            print("\n⚠️  Partial Success: Task paused *again*.")
            print("   This is OK, but the test won't complete.")
        else:
            print(f"\n❌ FAILED: Task did not complete. Final status: {final_data.get('status')}")

    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    print("Waiting 3s for services...")
    time.sleep(3)
    test_pause_and_approve()
    print("\n" + "="*50)
    print("Test complete. Check the Overseer dashboard.")
    print("="*50)