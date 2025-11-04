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
git clone <your-repo-url>
cd project-shiva

# (Recommended) Create a virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## 🚀 2. Run the Services

You must start all **five** services in **separate terminal windows**.  
The **Directory Service** must be started **first**, so the others can register with it.

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

---

At this point, all **five services** are running and communicating successfully.

---

## 🧪 3. Test the System

With all services running, open a **sixth terminal** and run the test script:

```bash
python test_invoke.py
```

This script will:

1. Check the Directory to confirm all services are registered  
2. Send a new task to the Manager  
3. Validate that the Guardian approves the plan  
4. Have the Partner execute the task  
5. Test the Overseer’s **kill-switch** functionality  

---

### 👀 What to Watch

Look at all your terminals — you’ll see the **chain of command** unfold in real time:

1. `test_invoke.py` sends a request to the **Manager**  
2. **Manager** logs to the **Overseer**  
3. **Manager** discovers the **Guardian** via the **Directory**  
4. **Manager** asks the **Guardian** to validate the plan  
5. **Guardian** logs its validation  
6. **Manager** discovers the **Partner** via the **Directory**  
7. **Manager** asks the **Partner** to execute the first step  
8. **Partner** logs its execution *(Reason → Act → Observe)*  
9. **Manager** logs the final result to the **Overseer**  
10. `test_invoke.py` then tests the **kill-switch**, and the **Manager** rejects a new task  

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
         |    Manager        |
         +--------+---------+
                  |
        +---------+----------+
        |                    |
        v                    v
  +-----------+        +-------------+
  |  Guardian  |        |   Partner   |
  +-----------+        +-------------+
        \                    /
         \                  /
          \                /
           v              v
            +-------------+
            |   Overseer  |
            +-------------+
                  ^
                  |
         +--------+---------+
         |    Directory     |
         +------------------+
```

---

## 🧰 Requirements

- Python 3.9+  
- Dependencies listed in `requirements.txt`  
- Localhost ports (default):
  - Directory: **8005**
  - Overseer: **8006**
  - Guardian: **8007**
  - Partner: **8008**
  - Manager: **8009**

---

## 🧾 License

This project is released under the **MIT License**.  
Feel free to use, modify, and extend it for your own multi-agent systems.

---

**PROJECT SHIVA**  
> *“A balanced mind directs intelligent agents — order through orchestration.”*
