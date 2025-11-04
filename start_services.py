import subprocess
import time
import sys
import atexit

# List of all 6 services.
# Directory should start first to be safe, though the others will retry.
services = [
    "directory_service.py",
    "overseer_service.py",
    "resource_hub_service.py",
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

    for service in services:
        print(f"Starting {service}...")
        
        # Use sys.executable to ensure we use the same Python
        # (e.g., from the virtual environment)
        process = subprocess.Popen([sys.executable, service])
        processes.append(process)
        
        # Stagger starts slightly to make the startup logs readable
        time.sleep(0.5) 

    print("\n===============================================")
    print("All 6 services are starting up in the background.")
    print("Logs will be printed to their respective terminals (if any) or here.")
    print("Press Ctrl+C in this terminal to stop ALL services.")
    print("===============================================")

    # Keep this main script alive so it can manage the child processes
    while True:
        time.sleep(60)

except KeyboardInterrupt:
    # This block is triggered on Ctrl+C.
    # The atexit handler will take care of the cleanup.
    print("\nKeyboard interrupt received. Initiating shutdown...")