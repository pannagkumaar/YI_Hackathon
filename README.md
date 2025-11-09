# 🕉️ PROJECT SHIVA  
### Smart Hub for Intelligent Virtual Agents  

> “A balanced mind directs intelligent agents — order through orchestration.”

---

## 🌌 Overview  

**PROJECT SHIVA** is a **modular, multi-agent orchestration framework** designed to enable intelligent, autonomous coordination between virtual agents.  
Built around **six core microservices**, SHIVA brings structure and safety to multi-agent collaboration — integrating reasoning, compliance validation, execution, and human-in-the-loop (HITL) oversight.

---

## 🧩 Core Microservices  

| Service | Port | Role | Description |
|---|---|---|---|
| **Directory Service** | `8005` | 📒 *Phone Book* | Handles service registration and discovery. All services find each other here. |
| **Overseer Service** | `8004` | 🛰️ *Control Tower* | Central logging feed and **main web dashboard** for monitoring and HITL control. |
| **Guardian Service** | `8003` | 🛡️ *Compliance Officer* | Validates plans and actions against policies. |
| **Partner Service** | `8002` | 👷 *Worker* | Executes task steps using a ReAct-style (Reason → Act → Observe) loop. |
| **Manager Service** | `8001` | 👨‍💼 *Team Lead* | Orchestrates the entire process — breaks down high-level goals into executable plans. |
| **Resource Hub** | `8006` | 🧰 *The Armory* | Provides tools, long-term memory (RAG), and short-term storage for agents. |

---

## 🧠 Architecture Overview  

The system follows a **loop-within-a-loop** design:  
- The **Manager Service** iterates through high-level plans.  
- Each step is handled by the **Partner Service**, which runs its own ReAct loop.  
- The **Resource Hub** powers agents with tools, memory, and context.  
- The **Guardian** enforces policies before actions.  
- The **Overseer** supervises everything through the live dashboard.  

```text
               +----------------------+
               | User (Web Dashboard) |
               | http://localhost:8004|
               +-----------+----------+
                           | (Approve/Replan)
(View Logs)                v
+-----------+    +---------+---------+    +------------------+
|  Overseer |<---+   Manager Service   +--->|  Guardian Service|
| (Logging) |    +--+----------------+    +---------+--------+
+-----------+       | (Execute Step)                 | (Get Policies)
     ^              |                                v
     | (Logs)       | (Register/Discover)      +-------------+
     |              v                          | Resource Hub|
+----+----+    +---------+---------+    +------> (Tools, Mem) |
| Partner |<---+ Directory Service +<---+      +-------------+
| (Worker)|    |   (Registry)    |    | (Get Tools, Log Mem)
+--+------+    +-----------------+    +-------------+
   |                                              ^
   | (Validate Action)                            |
   +----------------------------------------------+
```

---

## ⚙️ 1. Setup  

### Clone the Repository  

```bash
git clone https://github.com/pannagkumaar/YI_Hackathon
cd YI_Hackathon
```

### (Optional) Create a Virtual Environment  

```bash
python -m venv venv
source venv/bin/activate     # On Windows: venv\Scripts\activate
```

### Install Dependencies  

```bash
pip install -r requirements.txt
```

---

## 🔑 2. Configure Your API Key  

SHIVA uses the **Gemini API** for agent reasoning.  

Create a `.env` file in the project’s root directory and add your key:  

```ini
# .env
GOOGLE_API_KEY="your-google-api-key-here"
```

All services will automatically load this key at startup.

---

## 🚀 3. Run the Services  

You can launch, monitor, and stop all six services from one script.

### Start All Services  

```bash
python start_services.py
```

This script will:  
✅ Verify dependencies  
✅ Launch all six microservices  
✅ Stream startup logs  

To stop all services, press **Ctrl+C** in the terminal running the script.

---

## 🧪 4. Use the System  

### Step 1: Open the Dashboard  

Open your browser and visit:  
👉 [http://localhost:8004](http://localhost:8004)

You’ll see a **live log stream** and an initially empty task dashboard.

---

### Step 2: Run a Standard Task  

With all services running, open a new terminal and execute:  

```bash
python test_invoke.py
```

This script will:  
- Confirm all 6 services are registered.  
- Submit a sample task:  
  > “Deploy new model version 1.2.3 to production.”  
- Poll task status until it completes.  

Watch your dashboard and logs — you’ll see real-time collaboration between services.

---

### Step 3: Test Human-in-the-Loop (Pause & Approve)  

This test simulates a deviation that requires manual intervention.  

Run:  

```bash
python test_pause_and_approve.py
```

Then go to the [Overseer Dashboard](http://localhost:8004):  
- You’ll see a task with status **PAUSED_DEVIATION** (yellow).  
- Click **“Retry/Resume”** to approve continuation.  

Your test script will detect the status change and proceed until **COMPLETED**.

---

## 🧾 License  

This project is released under the **MIT License**.  
Feel free to use, modify, and extend it for your own multi-agent systems.

---

## ⚡ Quick Summary  

| Component | Purpose |
|------------|----------|
| Manager | Plans & delegates tasks |
| Partner | Executes with reasoning |
| Guardian | Validates actions |
| Directory | Connects services |
| Resource Hub | Provides tools & memory |
| Overseer | Logs & human oversight |

---

### 🕉️ PROJECT SHIVA  
> “A balanced mind directs intelligent agents — order through orchestration.”
