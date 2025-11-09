import requests, json, time

API_KEY = "mysecretapikey"
BASE = "http://localhost:8006"   # Guardian external mapped port
HEAD = {"X-SHIVA-SECRET": API_KEY}

def check_health():
    print("[1] Health check:")
    r = requests.get(f"{BASE}/healthz")
    print(r.status_code, r.text)

def test_safe():
    print("\n[2] SAFE action:")
    payload = {"task_id": "safe1", "proposed_action": "list logs", "context": {}}
    r = requests.post(f"{BASE}/guardian/validate_action", json=payload, headers=HEAD)
    print(r.status_code, json.dumps(r.json(), indent=2))

def test_risky():
    print("\n[3] RISKY action:")
    payload = {"task_id": "risky1", "proposed_action": "rm -rf /", "context": {}}
    r = requests.post(f"{BASE}/guardian/validate_action", json=payload, headers=HEAD)
    print(r.status_code, json.dumps(r.json(), indent=2))

def directory_list():
    print("\n[4] Directory list:")
    r = requests.get("http://localhost:8005/list", headers=HEAD)
    print(json.dumps(r.json(), indent=2))

if __name__ == "__main__":
    check_health()
    test_safe()
    test_risky()
    directory_list()
