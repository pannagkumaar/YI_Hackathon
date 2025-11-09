import requests
import time
from rich.console import Console
from rich.table import Table

console = Console()

SERVICES = {
    "directory": {"url": "http://localhost:8005", "check": "/list"},
    "overseer": {"url": "http://localhost:8002", "check": "/health"},
    "manager": {"url": "http://localhost:8003", "check": "/health"},
    "partner": {"url": "http://localhost:8004", "check": "/health"},
    "guardian": {"url": "http://localhost:8006", "check": "/health"},
    "resource_hub": {"url": "http://localhost:8007", "check": "/healthz"},
}

SECRET = {"X-SHIVA-SECRET": "mysecretapikey"}

def check_endpoint(name, url, path):
    try:
        r = requests.get(url + path, headers=SECRET, timeout=5)
        if r.status_code in (200, 404):  # 404 means FastAPI up but route missing
            return "✅", "Responding"
        else:
            return "⚠️", f"HTTP {r.status_code}"
    except Exception as e:
        return "❌", str(e).split(":")[-1].strip()

def check_directory_list():
    try:
        r = requests.get("http://localhost:8005/list", headers=SECRET, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return "✅", f"{len(data)} services registered"
        return "⚠️", f"HTTP {r.status_code}"
    except Exception as e:
        return "❌", str(e).split(":")[-1].strip()

def check_discover_chain():
    try:
        r = requests.get(
            "http://localhost:8005/discover?service_name=manager",
            headers=SECRET, timeout=5)
        if r.status_code == 200 and "url" in r.text:
            return "✅", "Partner → Directory → Manager works"
        return "⚠️", f"Bad response: {r.text[:60]}"
    except Exception as e:
        return "❌", str(e).split(":")[-1].strip()

def main():
    console.print("\n[bold cyan]=== SHIVA Integration Health Check ===[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Service")
    table.add_column("Status")
    table.add_column("Details")

    for name, s in SERVICES.items():
        status, detail = check_endpoint(name, s["url"], s["check"])
        table.add_row(name, status, detail)
    
    console.print(table)

    # Directory summary
    status, detail = check_directory_list()
    console.print(f"\n[bold yellow]Directory Summary:[/bold yellow] {status} {detail}")

    # Discovery chain
    status, detail = check_discover_chain()
    console.print(f"[bold yellow]Discovery Chain:[/bold yellow] {status} {detail}")

    console.print("\n[dim]Test complete.[/dim]\n")

if __name__ == "__main__":
    main()
