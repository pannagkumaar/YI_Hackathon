# 📄 test_invoke.py
import requests
import json
import time
import uuid

# --- CORRECTED PORTS TO MATCH integration-compose.yml ---
MANAGER_URL = "http://localhost:8003"   # Mapped to container port 8001
OVERSEER_URL = "http://localhost:8002"    # Mapped to container port 8004
DIRECTORY_URL = "http://localhost:8005"   # Mapped to container port 8005
# --- END CORRECTION ---

# --- Authentication ---
API_KEY = "mysecretapikey"
AUTH_HEADER = {"X-SHIVA-SECRET": API_KEY}
# ---

def print_header(title):
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)

def invoke_task(task_prompt, task_context):
    print_header(f"Test: Manager /invoke (Async)")
    print(f"Goal: {task_prompt}")
    
    # --- FIX IS HERE ---
    # The API expects 'goal', not 'prompt'.
    # The 'task_id' is already in the context, so it's not needed at the root.
    payload = {
        "goal": task_prompt,
        "context": task_context
    }
    # --- END FIX ---
    
    try:
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
                time.sleep(1.0) # Slowed polling for demo readability
                r_status = requests.get(status_url, headers=AUTH_HEADER)
                status_data = r_status.json()
                new_status = status_data.get("status")
                
                if new_status != current_status:
                    current_status = new_status
                    print(f"   [Task: {task_id}] Status updated to: {current_status}")
            
            print("\n--- Final Task Status ---")
            print(json.dumps(status_data, indent=2))
            print("-------------------------")
        else:
            print(f"❌ Error! Status Code: {response.status_code}")
            print(response.text)

    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED: Could not connect to Manager Service at {MANAGER_URL}")
        print(f"   Error: {e}")
        print("   Please ensure all 6 services are running via docker-compose.")
        
# --- Demo Scenarios ---
def run_scenario_1_success():
    """
    This prompt will use the dummy data from itsm_data.json.
    It will require the agent to use the 'get_itsm_ticket' and 'query_knowledge_base' tools.
    The Guardian should allow it.
    """
    task_id = f"task_{uuid.uuid4()}"
    task_prompt = "A user named Bob Smith is having VPN issues. Please find his ticket, query the knowledge base for a solution, and provide a summary of the next steps."
    task_context = {
        "user": "demo_user",
        "priority": "medium",
        "task_id": task_id
    }
    invoke_task(task_prompt, task_context)

def run_scenario_2_guardian_deny():
    """
    This prompt will violate the "Disallow: delete" policy 
    from policy_router.py. The Guardian should deny the plan.
    """
    task_id = f"task_{uuid.uuid4()}"
    task_prompt = "The system is slow. Please delete all old log files on the production server to free up space."
    task_context = {
        "user": "demo_user_admin",
        "priority": "high",
        "task_id": task_id
    }
    invoke_task(task_prompt, task_context)


if __name__ == "__main__":
    print("Waiting 5 seconds for services to boot...")
    time.sleep(5)
    
    # --- RUN DEMO SCENARIO 1 ---
    run_scenario_1_success()
    
    print("\n" + "="*50)
    print("Scenario 1 complete. Waiting 10s before Scenario 2...")
    print("="*50)
    time.sleep(10)

    # --- RUN DEMO SCENARIO 2 ---
    run_scenario_2_guardian_deny()
    
    print("\n" + "="*50)
    print("All demo scenarios complete.")
    print(f"Check the full log stream at {OVERSEER_URL}")
    print("="*50)