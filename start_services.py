#!/usr/bin/env python3
"""
start_services.py

Robust launcher for the SHIVA microservices during local development.

Usage:
    python start_services.py

Features:
 - Starts ASGI services with `python -m uvicorn ...` so background tasks run.
 - Streams and prefixes logs per-service.
 - Waits for /healthz before moving on.
 - Clean shutdown on Ctrl+C.
"""

import os
import sys
import time
import atexit
import signal
import threading
import subprocess
import requests
from typing import List, Dict, Any

ROOT = os.path.dirname(os.path.realpath(__file__))
os.chdir(ROOT)

PY = sys.executable  # use same python interpreter as venv

# Configure each service:
# - name: human name + prefix for logs
# - cmd: list (Popen)
# - cwd: working dir (None -> project root)
# - health: full URL to poll for readiness
# - restart: whether to automatically restart on crash (bool)
SERVICES: List[Dict[str, Any]] = [
    # Directory service is a simple python script (keeps it as python file)
    {
        "name": "directory",
        "cmd": [PY, "directory_service.py"],
        "cwd": ROOT,
        "health": "http://127.0.0.1:8005/healthz",
        "restart": False,
    },
    # Overseer (ASGI) - run via uvicorn module for stable ASGI behavior
    {
        "name": "overseer",
        "cmd": [PY, "-m", "uvicorn", "overseer_service:app", "--host", "0.0.0.0", "--port", "8004"],
        "cwd": ROOT,
        "health": "http://127.0.0.1:8004/healthz",
        "restart": False,
    },
    # Resource hub - it's inside resource_hub package; use --app-dir to ensure imports work
    {
        "name": "resource_hub",
        "cmd": [PY, "-m", "uvicorn", "resource_hub.main:app", "--host", "0.0.0.0", "--port", "8006", "--app-dir", "resource_hub"],
        "cwd": ROOT,
        "health": "http://127.0.0.1:8006/healthz",
        "restart": False,
    },
    {
        "name": "guardian",
        "cmd": [PY, "-m", "uvicorn", "guardian_service:app", "--host", "0.0.0.0", "--port", "8003"],
        "cwd": ROOT,
        "health": "http://127.0.0.1:8003/healthz",
        "restart": False,
    },
    {
        "name": "partner",
        "cmd": [PY, "-m", "uvicorn", "partner_service:app", "--host", "0.0.0.0", "--port", "8002"],
        "cwd": ROOT,
        "health": "http://127.0.0.1:8002/healthz",
        "restart": False,
    },
    {
        "name": "manager",
        "cmd": [PY, "-m", "uvicorn", "manager_service:app", "--host", "0.0.0.0", "--port", "8001"],
        "cwd": ROOT,
        "health": "http://127.0.0.1:8001/healthz",
        "restart": False,
    },
]

# If you want to auto-restart a service on crash (use with care), set restart=True above.
RESTART_DELAY = 2.0  # seconds before restart

process_map: Dict[str, subprocess.Popen] = {}
stop_event = threading.Event()


def stream_process_output(proc: subprocess.Popen, name: str):
    """Read stdout line-by-line and print with a service prefix."""
    try:
        # text mode; universal newlines; iterate lines
        for line in proc.stdout:
            if line is None:
                break
            # strip but keep newline spacing
            print(f"[{name}] {line.rstrip()}")
    except Exception as e:
        print(f"[{name}] (log streamer crashed) {e}")


def start_service(entry: Dict[str, Any]):
    name = entry["name"]
    cmd = entry["cmd"]
    cwd = entry.get("cwd") or ROOT

    print(f"\n[start_services] Starting {name} with: {cmd} (cwd={cwd})")

    # spawn process
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    # start a thread that streams the process' stdout
    t = threading.Thread(target=stream_process_output, args=(proc, name), daemon=True)
    t.start()

    process_map[name] = proc
    return proc


def stop_all():
    if stop_event.is_set():
        return
    stop_event.set()
    print("\n[start_services] Shutting down all services...")
    for n, p in list(process_map.items()):
        try:
            print(f"[start_services] Terminating {n} (pid={p.pid})")
            p.terminate()
        except Exception as e:
            print(f"[start_services] Failed to terminate {n}: {e}")

    # wait
    for n, p in list(process_map.items()):
        try:
            p.wait(timeout=5)
            print(f"[start_services] {n} stopped.")
        except Exception:
            try:
                print(f"[start_services] Killing {n}")
                p.kill()
            except Exception:
                pass
    print("[start_services] All services stopped.")


atexit.register(stop_all)


def wait_for_health(url: str, timeout: float = 10.0, interval: float = 0.4) -> bool:
    """Poll health endpoint until success or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def bring_up_services(services: List[Dict[str, Any]]):
    """
    Start in sequence:
     - start the Directory first (index 0) and wait for health
     - then start the rest in parallel, waiting for each health
    """
    # Start first service(s) that must be up early (directory)
    if not services:
        return

    # Start directory first (assumed index 0)
    first = services[0]
    proc = start_service(first)

    # wait for directory health
    print("[start_services] Waiting for Directory to be ready...")
    ok = wait_for_health(first["health"], timeout=15.0)
    if not ok:
        print("[start_services] WARNING: Directory did not respond within timeout. Continuing but discovery may fail.")
    else:
        print("[start_services] Directory is READY.")

    # Start remaining services (parallel)
    for entry in services[1:]:
        start_service(entry)
        # Wait for that service's health before continuing to start the next one
        print(f"[start_services] Waiting for {entry['name']} to report /healthz ...")
        ok = wait_for_health(entry["health"], timeout=15.0)
        if not ok:
            print(f"[start_services] WARNING: {entry['name']} did not respond in time (health check failed).")
        else:
            print(f"[start_services] {entry['name']} is READY.")


def monitor_crashes(services: List[Dict[str, Any]]):
    """
    Optionally watch for crashes and restart services with restart=True.
    Runs in background thread.
    """
    while not stop_event.is_set():
        for entry in services:
            name = entry["name"]
            restart_allowed = entry.get("restart", False)
            proc = process_map.get(name)
            if proc is None:
                continue
            ret = proc.poll()
            if ret is not None:
                # process exited
                print(f"[start_services] {name} exited with code {ret}")
                # remove from map
                process_map.pop(name, None)
                if restart_allowed and not stop_event.is_set():
                    print(f"[start_services] Restarting {name} in {RESTART_DELAY}s (restart enabled)")
                    time.sleep(RESTART_DELAY)
                    start_service(entry)
        time.sleep(1.0)


def main():
    print("=====================================================")
    print("Starting SHIVA services...")
    print(f"Using Python executable: {PY}")
    print(f"Project root: {ROOT}")
    print("=====================================================")

    bring_up_services(SERVICES)

    # Launch crash monitor thread (only used if any restart=True)
    t = threading.Thread(target=monitor_crashes, args=(SERVICES,), daemon=True)
    t.start()

    print("\n=====================================================")
    print("All services launched. Press Ctrl+C in this terminal to stop ALL services.")
    print("=====================================================")

    # Block until CTRL+C
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[start_services] CTRL+C received, shutting down...")
        stop_all()


if __name__ == "__main__":
    main()
