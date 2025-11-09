# 🕉️ PROJECT SHIVA
### Smart Hub for Intelligent Virtual Agents

**PROJECT SHIVA** is a modular, multi-agent orchestration framework built around six core microservices. It enables autonomous agent collaboration by providing service discovery, simulated planning, rule-based safety validation, in-memory storage, and real-time human oversight.

The system is built on a "loop-within-a-loop" architecture, as described in `What is happening.md`:
1.  **The Manager's "Plan Loop"**: A mock planner that generates a hard-coded, multi-step plan.
2.  **The Partner's "ReAct Loop"**: A mock worker that simulates a Thought-Action-Observation cycle to execute each step.

## 🏛️ Architecture & Core Services

The entire system is a network of six independent FastAPI services that communicate via secure, authenticated REST APIs.

| Service | File | Role | Port (Local) |
| :--- | :--- | :--- | :--- |
| **Directory** | `directory_service.py` | 📒 **Service Registry** | `8005` |
| **Overseer** | `overseer_service.py` | 🛰️ **Control Tower** | `8004` |
| **Manager** | `manager_service.py` | 👨‍💼 **Mock Team Lead** | `8001` |
| **Partner** | `partner_service.py` | 👷 **Mock Worker Agent** | `8002` |
| **Guardian** | `guardian_service.py` | 🛡️ **Mock Safety Officer** | `8003` |
| **Resource Hub** | `resource_hub_service.py` | 🧰 **Mock Armory & Library** | `8006` |

---

## ⚙️ Key Features

* **Mock AI Orchestration**: Services simulate intelligence using `use_agent` functions with Python logic.
    * **Manager**: Generates a plan for any goal.
    * **Partner**: Simulates execution by randomly choosing a tool and a result ("success" or "deviation").
    * **Guardian**: Uses simple string-matching to check for "Disallow:" keywords (e.g., "delete").
* **In-Memory Storage**: The Resource Hub uses a Python dictionary (`tasks_memory`) to store short-term "Thought-Action-Observation" memory. This memory is **not persistent** and will be lost when the service restarts.
* **Human-in-the-Loop (HITL)**: The Manager is designed to pause when the Partner's simulation returns a `"DEVIATION_DETECTED"`. A human operator can then intervene via API endpoints to **approve** and resume the task, or **replan** it.
* **Live Dashboard**: The Overseer provides a real-time web dashboard (`overseer_dashboard.html`) that streams logs from all six services via WebSockets.
* **Mock Tools & Policies**: The Resource Hub serves a hard-coded list of tools (e.g., `run_script`) and safety policies (e.g., `Disallow: delete`) that agents fetch at runtime.
* **Secure Communication**: All internal service-to-service communication is authenticated using a shared secret key (`X-SHIVA-SECRET`) defined in `security.py`.

---

## 🚀 Setup & Installation

1.  **Clone the Repository**
    ```bash
    git clone [https://github.com/pannagkumaar/YI_Hackathon.git](https://github.com/pannagkumaar/YI_Hackathon.git)
    cd YI_Hackathon
    ```

2.  **Install Dependencies**
    Install the required packages from the root `requirements.txt` file.
    ```bash
    # (Recommended) Create a virtual environment
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate

    # Install dependencies
    pip install -r requirements.txt
    ```

---

## 🏃‍♂️ How to Run the Demo

1.  **Start all services** in a single terminal using the launcher script:
    ```bash
    python start_services.py
    ```
    This script will launch all 6 Python services as background processes.

2.  **Open the Dashboard** in your browser to watch the live logs:
    * **URL:** `http://localhost:8004`
    *(This is the local port for the `overseer_service.py`)*

3.  **Run the Simulation** in a new terminal using the provided test scripts.

4.  **Stop all services** when you are done by pressing `Ctrl+C` in the terminal where you ran `start_services.py`.

---

## 🎭 Demo Scenarios

Run these scripts in a separate terminal *after* starting the services.

### Scenario 1: The "Happy Path" (test_invoke.py)
This test invokes a task and polls until it finishes. Since the Partner's result is random, this test may either **complete** or **pause on deviation**.

```bash
python test_invoke.py
