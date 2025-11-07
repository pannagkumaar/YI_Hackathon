import subprocess
import time
import sys
import atexit
import os

# List of all 6 services.
services = [
    "directory_service.py",
    "overseer_service.py",
    "resource_hub/main.py",  # <-- Corrected to point to the new hub
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

    current_dir = os.path.dirname(os.path.realpath(__file__))
    if not current_dir:
        current_dir = os.getcwd()

    # --- MODIFIED: One-time environment setup ---
    print("Verifying unified environment is installed...")
    # Install the *single* root requirements.txt
    # This command runs from the script's directory (current_dir)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=current_dir,
        check=True,
        capture_output=True,
        text=True
    )
    print("Environment verified.")
    # --- END MODIFIED ---


    for service in services:
        print(f"Starting {service}...")
        
        cmd = [sys.executable, service]
        cwd = current_dir # Default to current directory
        
        if service == "resource_hub/main.py":
            # The new hub must be run from *within* its folder
            hub_dir = os.path.join(current_dir, "resource_hub")
            cmd = [sys.executable, "main.py"]
            cwd = hub_dir
            # We no longer install requirements here
            
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
    if hasattr(e, 'stderr') and e.stderr:
        if isinstance(e.stderr, bytes):
            print(f"Details: {e.stderr.decode()}")
        else:
            print(f"Details: {e.stderr}")
    print("Shutting down any processes that were started...")
    cleanup()