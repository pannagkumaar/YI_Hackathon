# 🕉️ PROJECT SHIVA
### Smart Hub for Intelligent Virtual Agents

**PROJECT SHIVA** is a modular, multi-agent orchestration framework built around six core microservices. It enables intelligent, autonomous agents to collaborate on complex tasks by providing service discovery, AI-driven planning, safety validation, persistent memory, and real-time human oversight.

The system is built on a "loop-within-a-loop" architecture:
1.  **The Manager's "Plan Loop"**: An AI planner that breaks a high-level goal into a multi-step plan.
2.  **The Partner's "ReAct Loop"**: An AI worker that autonomously executes each step from the Manager's plan using a Thought-Action-Observation cycle.

## 🏛️ Architecture & Core Services

The entire system is a network of six independent FastAPI services that communicate via secure, authenticated REST APIs.

| Service | File | Role | Port (Local) | Port (Docker) |
| :--- | :--- | :--- | :--- | :--- |
| **Directory** | `directory_service.py` | 📒 **Service Registry** | `8005` | `8005` |
| **Overseer** | `overseer_service.py` | 🛰️ **Control Tower** | `8004` | `8002` |
| **Manager** | `manager_service.py` | 👨‍💼 **AI Team Lead** | `8001` | `8003` |
| **Partner** | `partner_service.py` | 👷 **AI Worker Agent** | `8002` | `8004` |
| **Guardian** | `guardian_service.py` | 🛡️ **AI Safety Officer** | `8003` | `8006` |
| **Resource Hub** | `resource_hub/main.py` | 🧰 **The Armory & Library** | `8006` | `8007` |

---

## ⚙️ Key Features

* **Real AI Orchestration**: Uses Google's Gemini models for high-level planning (`manager_service.py`), ReAct-style execution (`partner_service.py`), and safety validation (`guardian_service.py`).
* **Persistent Memory**: The Resource Hub provides a persistent **SQLite** database for agents to store short-term "Thought-Action-Observation" memories.
* **Retrieval-Augmented Generation (RAG)**: The Resource Hub uses a **ChromaDB** vector store and **SentenceTransformers** to provide long-term, searchable knowledge for all agents.
* **Human-in-the-Loop (HITL)**: The Manager is designed to pause on failure (`PAUSED_DEVIATION`). A human operator can then intervene via API endpoints to **approve** the task and resume from the failed step, or **replan** the task entirely.
* **Live Dashboard**: The Overseer provides a real-time web dashboard (`overseer_dashboard.html`) that streams logs from all six services via WebSockets.
* **Dynamic Tools & Policies**: The Resource Hub serves tools (e.g., `get_itsm_ticket`) and safety policies (e.g., `Disallow: delete`) that agents fetch and use at runtime.
* **Secure Communication**: All internal service-to-service communication is authenticated using a shared secret key (`X-SHIVA-SECRET`).

---

## 🚀 Setup & Installation

1.  **Clone the Repository**
    ```bash
    git clone [https://github.com/pannagkumaar/YI_Hackathon.git](https://github.com/pannagkumaar/YI_Hackathon.git)
    cd YI_Hackathon
    ```

2.  **Install Dependencies**
    The project has two `requirements.txt` files. Install both to ensure all services have their dependencies.
    ```bash
    # Install root dependencies (for Manager, Partner, etc.)
    pip install -r requirements.txt
    
    # Install Resource Hub dependencies (ChromaDB, SQLite, etc.)
    pip install -r resource_hub/requirements.txt
    ```

3.  **Set Environment Variables**
    This project requires two critical environment variables to function:

    * **`GOOGLE_API_KEY`**: Your API key for the Gemini models.
    * **`SHARED_SECRET`**: A secret password to secure service communication.

    The easiest way to set these is to create a `.env` file in the project's **root** directory:

    **`.env`**
    ```ini
    # Root .env file
    GOOGLE_API_KEY="your-google-api-key-here"
    SHARED_SECRET="mysecretapikey"
    ```
    The services will automatically load these variables.

    **Note:** The `resource_hub` also has its own `.env` file. You can edit this file to configure database paths or other `resource_hub` specifics.

---

## 🏃‍♂️ How to Run

### Option 1: Run Locally (Recommended for Demo)

1.  **Start all services** in a single terminal using the launcher script:
    ```bash
    python start_services.py
    ```
    This script will launch all 6 Python services as background processes.

2.  **Open the Dashboard** in your browser to watch the live logs:
    * **URL:** `http://localhost:8004`
    *(This is the local port for the `overseer_service.py`)*

3.  **Run the Simulation** in a new terminal using the provided test script:
    ```bash
    python test_invoke.py
    ```

4.  **Stop all services** when you are done by pressing `Ctrl+C` in the terminal where you ran `start_services.py`.

### Option 2: Run with Docker Compose

1.  **Build the base image** (one-time setup):
    ```bash
    docker build -t shiva-base -f Dockerfile.base .
    ```

2.  **Start the stack** using the integration compose file:
    ```bash
    docker-compose -f integration-compose.yml up --build -d
    ```

3.  **Open the Dashboard** in your browser. Note the port mapping from the `.yml` file:
    * **URL:** `http://localhost:8002`

4.  **Run the Simulation** from your host machine.
    * **Important:** You must use the `test_invoke.py` script that is corrected for Docker's port mappings (pointing to `localhost:8003` for the Manager, etc.).
    ```bash
    python test_invoke.py
    ```

5.  **Stop all containers** when finished:
    ```bash
    docker-compose -f integration-compose.yml down
    ```

---

## 🎭 Demo Scenarios

The `test_invoke.py` script is designed to run two key simulations that showcase the system's capabilities.

### Scenario 1: The "Success" Path
* **Goal**: "A user named Bob Smith is having VPN issues. Please find his ticket, query the knowledge base for a solution, and provide a summary of the next steps."
* **Action**:
    1.  The **Manager** AI creates a plan (e.g., `get_itsm_ticket`, `query_knowledge_base`).
    2.  The **Guardian** AI approves the plan.
    3.  The **Partner** AI executes the plan, calling the **Resource Hub**'s tools.
    4.  The Resource Hub's tools read from the dummy `itsm_data.json` file to find Bob's ticket.
    5.  The task completes successfully.

### Scenario 2: The "Guardian Deny" Path
* **Goal**: "The system is slow. Please delete all old log files on the production server to free up space."
* **Action**:
    1.  The **Manager** AI creates a plan (e.g., `list_log_files`, `delete_files`).
    2.  The **Guardian** AI fetches policies from the **Resource Hub**, finds the `"Disallow: delete"` rule, and **Denies** the plan.
    3.  The **Manager** receives the denial and immediately sets the task status to `REJECTED`.
    4.  The system is protected from a harmful action.
