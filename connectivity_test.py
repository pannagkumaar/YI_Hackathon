import requests, json, time

SECRET = {"X-SHIVA-SECRET": "mysecretapikey"}
DIR = "http://localhost:8005"

def test_directory_lists_services():
    r = requests.get(f"{DIR}/list", headers=SECRET)
    assert r.status_code == 200
    data = r.json()
    assert "manager" in data and "resource_hub" in data

def test_overseer_log_event():
    entry = {"service":"manager","task_id":"demo","level":"INFO","message":"integration test"}
    r = requests.post("http://localhost:8004/log/event", headers=SECRET, json=entry)
    assert r.status_code in (200,201)

def test_directory_auth_rejects_invalid():
    r = requests.get(f"{DIR}/list", headers={"X-SHIVA-SECRET":"bad"})
    assert r.status_code == 403
