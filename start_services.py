import subprocess
import time
import sys
import atexit
import os # Import os

# List of all 6 services.
services = [
    "directory_service.py",
    "overseer_service.py",
    # --- THIS IS THE FIX ---
    # "resource_hub_service.py", # <-- DELETE THIS OLD FILE
    "resource_hub/main.py",     # <-- ADD THIS NEW FILE
    # --- END FIX ---
    "guardian_service.py",
    "partner_service.py",
    "manager_service.py"
]

processes = []

def cleanup():
    """This function is called on script exit (e.g., Ctrl+C)"""
    print("\nShutting down all services...")
    for p in processes:
        p.terminate()  # Send terminate signal to all child processes
    
    # Wait for all processes to exit
    for p in processes:
        p.wait()
    print("All services stopped.")

# Register the cleanup function to run when the script exits
atexit.register(cleanup)

try:
    print("Starting all 6 SHIVA services in parallel...")
    print(f"Using Python executable: {sys.executable}\n")

    # --- ADDED: Change directory for the new hub ---
    # Get the directory of the current script
    current_dir = os.path.dirname(os.path.realpath(__file__))
    if not current_dir:
        current_dir = os.getcwd()
    # --- END ADD ---

    for service in services:
        print(f"Starting {service}...")
        
        # --- MODIFIED: Handle the new hub's path ---
        cmd = [sys.executable, service]
        cwd = current_dir # Default to current directory
        
        if service == "resource_hub/main.py":
            # The new hub needs to be run from *within* its folder
            # to find its 'app', 'data', etc.
            hub_dir = os.path.join(current_dir, "resource_hub")
            cmd = [sys.executable, "main.py"]
            cwd = hub_dir
            # Also ensure its dependencies are installed
            print("   (Ensuring resource_hub requirements are installed...)")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=hub_dir,
                check=True,
                capture_output=True,
                text=True
            )
        # --- END MODIFIED ---
            
        process = subprocess.Popen(cmd, cwd=cwd)
        processes.append(process)
        
        time.sleep(0.5) 

    print("\n===============================================")
    print("All 6 services are starting up in the background.")
    print("Press Ctrl+C in this terminal to stop ALL services.")
    print("===============================================")

    # Keep this main script alive so it can manage the child processes
    while True:
        time.sleep(60)

except KeyboardInterrupt:
    print("\nKeyboard interrupt received. Initiating shutdown...")
except Exception as e:
    print(f"\n--- FAILED TO START SERVICES ---")
    print(f"Error: {e}")
    if hasattr(e, 'stderr'):
        print(f"Details: {e.stderr}")
    print("Shutting down any processes that were started...")
    cleanup()