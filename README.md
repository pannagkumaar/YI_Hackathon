# 🕉️ PROJECT SHIVA  
### Smart Hub for Intelligent Virtual Agents

**PROJECT SHIVA** is a modular, multi-agent orchestration framework built around five core microservices.  
It enables intelligent, autonomous coordination between agents using a service registry, safety validation, task execution, and oversight mechanisms.

---

## 🧩 Core Microservices

| Service | Role | Description |
|----------|------|-------------|
| **Directory Service** | 📒 Phone Book | Handles service registration and discovery. |
| **Overseer Service** | 🛰️ Control Tower | Provides logging and a global kill-switch for safety. |
| **Guardian Service** | 🛡️ Compliance Officer | Validates plans and actions for safety and correctness. |
| **Partner Service** | 👷 Worker | Executes individual task steps (ReAct-style). |
| **Manager Service** | 👨‍💼 Team Lead | Orchestrates the entire process from goal to execution. |

---

## ⚙️ 1. Setup

First, clone this repository and install dependencies.

```bash
git clone https://github.com/pannagkumaar/YI_Hackathon
cd YI_Hackathon

# (Recommended) Create a virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# Add gemini key to .env
GOOGLE_API_KEY= ,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,

# Install dependencies
pip install -r requirements.txt
```

---

## 🚀 2. Run the Services

You must start all **five** services in **separate terminal windows**.  
The **Directory Service** must be started **first**, so the others can register with it.

---

###  Alternatively can run the start_services.py instead of the below steps
```bash
python start_services.py
```
---
### 🧱 Terminal 1: Directory Service — "The Phone Book"

```bash
python directory_service.py
```

Wait for the message:

```text
Starting Directory Service on port 8005...
```

---

### 🛰️ Terminal 2: Overseer Service — "The Control Tower"

```bash
python overseer_service.py
```

You should see:

```text
[Overseer] Successfully registered with Directory...
```

---

### 🛡️ Terminal 3: Guardian Service — "The Compliance Officer"

```bash
python guardian_service.py
```

You should see:

```text
[Guardian] Successfully registered with Directory...
```

---

### 👷 Terminal 4: Partner Service — "The Worker"

```bash
python partner_service.py
```

You should see:

```text
[Partner] Successfully registered with Directory...
```

---

### 👨‍💼 Terminal 5: Manager Service — "The Team Lead"

```bash
python manager_service.py
```

You should see:

```text
[Manager] Successfully registered with Directory...
```
### 🧰 Terminal 6: Resource Hub — "The Armory"

```bash
python resource_hub_service.py
```

You should see:

```text
[ResourceHub] Successfully registered with Directory...
```

---

At this point, all **six services** are running and communicating successfully.

---

## 🧪 3. Test the System

With all services running, open a **sixth terminal** and run the test script:

```bash
python test_invoke.py
```

This script will:

1. Check the Directory to confirm all 6 services are registered.
2. Send a new task (e.g., "Deploy model") to the Manager.
3. The Manager will ask the Guardian to validate the plan.
4. The Guardian will fetch policies from the Resource Hub to approve it.
5. The Manager will ask the Partner to execute the task.
6. The Partner will ask the Guardian to validate its specific action.
7. All services will log their actions to the Overseer.
8. The test will then trigger the kill-switch to confirm the system halts.

---

### 👀 What to Watch

Look at all your terminals — you’ll see the chain of command unfold in real time:

1.  `test_invoke.py` sends a request to the Manager.
2.  Manager logs to the Overseer.
3.  Manager discovers the Guardian (via Directory).
4.  Manager asks Guardian to validate the plan.
5.  Guardian discovers the Resource Hub (via Directory).
6.  Guardian fetches policies from Resource Hub and logs to Overseer.
7.  Manager discovers the Partner (via Directory).
8.  Manager asks Partner to execute.
9.  Partner discovers the Guardian (via Directory).
10. Partner asks Guardian to validate its action.
11. Partner logs its execution (Reason → Validate → Act → Observe) to Overseer.
12. Manager logs the final result to the Overseer.

---

✅ When you see these interactions in your logs, your **PROJECT SHIVA** multi-agent system is fully operational!  

---

## 🧠 Architecture Overview

```text
         +------------------+
                     |  test_invoke.py  |
                     +--------+---------+
                              |
                              v
                     +--------+---------+
                     |     Manager      | (Orchestrator)
                     +------------------+
                              |
                +-------------+-------------+
(Validate Plan) |                           | (Execute Step)
                v                           v
          +-----------+               +-------------+
          |  Guardian |               |   Partner   | (Worker)
          +-----------+<--------------+-------------+
                |      (Validate Action)
    (Get Policy)|
                v
          +--------------+
          | Resource Hub | (Armory/Library)
          +--------------+

     (All 4 services above register/discover with Directory
      and log to Overseer)

               \      |      /      /
                \     |     /      /
                 \    |    /      /
                  v   v   v      v
                   +-------------+
                   |   Overseer  | (Logging)
                   +-------------+
                         ^
                         | (Discovery)
                   +-------------+
                   |  Directory  | (Registry)
                   +-------------+
```

---

## 🧰 Requirements

- Python 3.9+  
- Dependencies listed in `requirements.txt`  
- Localhost ports (default):
  - Manager: **8001**
  - Partner: **8002**
  - Guardian: **8003**
  - Overseer: **8004**
  - Directory: **8005**
  - Resource Hub: **8006**

---

## 🧾 License

This project is released under the **MIT License**.  
Feel free to use, modify, and extend it for your own multi-agent systems.

---

**PROJECT SHIVA**  
> *“A balanced mind directs intelligent agents — order through orchestration.”*
