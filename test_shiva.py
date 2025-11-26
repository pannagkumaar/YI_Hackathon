#!/usr/bin/env python3
"""
SHIVA FULL WORKFLOW TEST HARNESS (Updated for approved_once + pending_action)
"""

import time
import requests
import json
import sys

API_KEY = "mysecretapikey"
H = {"X-SHIVA-SECRET": API_KEY, "Content-Type": "application/json"}

MANAGER = "http://127.0.0.1:8001"
GUARDIAN = "http://127.0.0.1:8003"
PARTNER = "http://127.0.0.1:8002"
HUB     = "http://127.0.0.1:8006"
OVERSEER = "http://127.0.0.1:8004"

def pretty(o): print(json.dumps(o, indent=2))


print("\n============================================")
print("🔥 SHIVA FULL WORKFLOW TEST HARNESS RUNNING")
print("============================================\n")


# -------------------------------------------------------------------
# STEP 1 — MANAGER INVOKE
# -------------------------------------------------------------------
goal = "Check connectivity to 8.8.8.8"
print(f"→ Invoking Manager with goal: '{goal}'")

resp = requests.post(
    f"{MANAGER}/invoke",
    headers=H,
    json={"goal": goal, "context": {}}
)

try:
    invoke = resp.json()
except:
    print("❌ Manager returned non-JSON:", resp.text)
    sys.exit()

pretty(invoke)

task_id = invoke["task_id"]
print(f"\n→ Extracted task_id: {task_id}\n")


# -------------------------------------------------------------------
# STEP 2 — POLL MANAGER
# -------------------------------------------------------------------
print("→ Polling Manager for task status...\n")

count = 0
status = None

while True:
    r = requests.get(f"{MANAGER}/task/{task_id}/status", headers=H)
    status = r.json()
    count += 1

    print(f"   [{count}] Status =", status["status"])

    if status["status"] in (
        "FAILED", "REJECTED", "COMPLETED",
        "WAITING_APPROVAL", "PAUSED_DEVIATION"
    ):
        break

    time.sleep(1)


# -------------------------------------------------------------------
# STEP 3 — APPROVAL FLOW
# -------------------------------------------------------------------
if status["status"] == "WAITING_APPROVAL":
    print("\n⚠️ Guardian requires approval. Sending APPROVE...")

    a = requests.post(
        f"{MANAGER}/task/{task_id}/approve",
        headers=H
    )
    print("→ Approve response:")
    pretty(a.json())

    print("\n→ Re-polling after approval...\n")
    for i in range(20):
        s2 = requests.get(f"{MANAGER}/task/{task_id}/status", headers=H).json()
        print(f"   [{i}] Status =", s2["status"])
        status = s2
        if status["status"] in ("COMPLETED", "FAILED", "REJECTED"):
            break
        time.sleep(1)


# -------------------------------------------------------------------
# STEP 4 — FINAL STATUS
# -------------------------------------------------------------------
print("\n====================================")
print(" FINAL TASK STATUS")
print("====================================")
pretty(status)


# -------------------------------------------------------------------
# STEP 5 — RESOURCE HUB TEST
# -------------------------------------------------------------------
print("\n-------------------------------------")
print(" RESOURCE HUB: /tools/list")
print("-------------------------------------")
pretty(requests.get(f"{HUB}/tools/list", headers=H).json())

print("\n→ Executing tool: ping_host(8.8.8.8)")
pretty(
    requests.post(
        f"{HUB}/tools/execute",
        headers=H,
        json={"tool_name": "ping_host", "parameters": {"host": "8.8.8.8"}}
    ).json()
)


# -------------------------------------------------------------------
# STEP 6 — GUARDIAN DIRECT TEST
# -------------------------------------------------------------------
print("\n-------------------------------------")
print(" GUARDIAN: /guardian/validate_action DIRECT TEST")
print("-------------------------------------")

gtest = requests.post(
    f"{GUARDIAN}/guardian/validate_action",
    headers=H,
    json={
        "task_id": "debug-test",
        "proposed_action": "ping_host",
        "action_input": {"host": "8.8.8.8"},
        "context": {}
    }
)
pretty(gtest.json())


# -------------------------------------------------------------------
# STEP 7 — PARTNER DIRECT TEST (Updated)
# -------------------------------------------------------------------
print("\n-------------------------------------")
print(" PARTNER: /partner/execute_goal DIRECT TEST")
print("-------------------------------------")

ptest = requests.post(
    f"{PARTNER}/partner/execute_goal",
    headers=H,
    json={
        "task_id": "debug-test2",
        "current_step_goal": "Ping test to 8.8.8.8",
        "approved_plan": {"steps": [{"step_id": 1}]},
        "context": {},
        "pending_action": {
            "action": "ping_host",
            "action_input": {"host": "8.8.8.8"},
            "step_goal": "Ping test to 8.8.8.8"
        }
    }
)
pretty(ptest.json())


# -------------------------------------------------------------------
# STEP 8 — OVERSEER LOG DUMP
# -------------------------------------------------------------------
print("\n-------------------------------------")
print(" OVERSEER: last 50 logs")
print("-------------------------------------")
pretty(requests.get(f"{OVERSEER}/logs?limit=50", headers=H).json())


print("\n============================================")
print("🎉 SHIVA END-TO-END TEST COMPLETED")
print("============================================\n")
