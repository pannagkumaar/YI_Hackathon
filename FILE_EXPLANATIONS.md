# 📚 PROJECT SHIVA - Complete File Documentation

This document provides a detailed explanation of every file in the PROJECT SHIVA codebase, what it does, and why it's important to the system.

---

## 🏗️ **CORE MICROSERVICES** (The Foundation)

### 1. `directory_service.py` - The Service Registry
**Purpose**: Acts as the central phone book for all services in the SHIVA ecosystem.

**What it does**:
- Maintains an in-memory registry of all active services (Manager, Partner, Guardian, Overseer, Resource Hub)
- Provides service discovery: other services can query it to find the URL of any registered service
- Implements TTL (Time-To-Live) based registration with automatic expiration
- Handles service registration, deregistration, and heartbeat updates

**Why it's important**:
- **Decoupling**: Services don't need to know each other's URLs in advance
- **Dynamic Discovery**: New services can join the system without code changes
- **Health Monitoring**: Expired registrations indicate dead services
- **Scalability**: Foundation for horizontal scaling (multiple instances of the same service)

**Key Features**:
- `/register` - Services register themselves with a TTL
- `/discover` - Find a service by name
- `/list` - View all active services
- `/deregister` - Remove a service from the registry

**Port**: 8005

---

### 2. `overseer_service.py` - The Control Tower
**Purpose**: Provides observability, logging, and a global kill-switch for the entire system.

**What it does**:
- Collects and stores logs from all services in real-time
- Provides a WebSocket-based live log stream for the dashboard
- Implements a global kill-switch (`/control/kill`) that halts all new tasks
- Serves an HTML dashboard (`overseer_dashboard.html`) for monitoring
- Acts as a proxy for UI actions (approve, replan tasks)

**Why it's important**:
- **Observability**: Centralized logging makes debugging easier
- **Safety**: Kill-switch provides emergency stop capability
- **Monitoring**: Dashboard gives real-time visibility into system state
- **Audit Trail**: All decisions and actions are logged for compliance

**Key Features**:
- `/log/event` - Services send logs here
- `/control/kill` - Emergency halt all tasks
- `/control/resume` - Resume system after halt
- `/control/status` - Check if system is RUNNING or HALT
- `/ui/tasks` - Proxy to fetch tasks for dashboard
- `/ui/approve_task/{task_id}` - Proxy to approve tasks
- WebSocket `/ws/logs` - Real-time log streaming

**Port**: 8004

---

### 3. `guardian_service.py` - The Compliance Officer
**Purpose**: Validates plans and actions for safety, compliance, and correctness before execution.

**What it does**:
- Validates high-level execution plans before they're executed
- Validates individual actions before the Partner executes them
- Uses a two-tier validation system:
  1. **Deterministic rules** (fast, rule-based checks in `guardian_rules.py`)
  2. **LLM fallback** (for ambiguous cases using Gemini)
- Integrates with Resource Hub to fetch policies and runbook snippets via RAG
- Detects plan deviations (actions that don't match approved plans)
- Detects prompt injection attempts
- Audits all decisions to the Overseer

**Why it's important**:
- **Safety**: Prevents destructive actions (rm -rf, shutdown, etc.)
- **Compliance**: Enforces organizational policies
- **Security**: Blocks prompt injection and malicious commands
- **Trust**: Provides a "buddy check" before any action executes
- **Audit**: All decisions are logged for compliance

**Key Features**:
- `/guardian/validate_plan` - Validate execution plans
- `/guardian/validate_action` - Validate individual actions
- Returns `403 Forbidden` for denied actions (API contract compliance)
- Returns `200 OK` with warnings array for allowed plans
- Plan deviation detection
- Prompt injection detection
- Policy-based validation

**Port**: 8003

---

### 4. `manager_service.py` - The Team Lead
**Purpose**: Orchestrates the entire task execution lifecycle from goal to completion.

**What it does**:
- Receives high-level goals from users (via `/invoke`)
- Uses Gemini AI to break down goals into step-by-step execution plans
- Validates plans with the Guardian before execution
- Coordinates with Partner service to execute each step
- Handles task state management (PENDING, PLANNING, EXECUTING, COMPLETED, etc.)
- Manages pause/resume functionality for deviations
- Provides task status tracking and replanning capabilities

**Why it's important**:
- **Orchestration**: Central coordinator for the entire multi-agent system
- **Planning**: Breaks down complex goals into executable steps
- **State Management**: Tracks task progress and handles errors
- **User Interface**: Main entry point for task submission
- **Recovery**: Handles deviations and allows human intervention

**Key Features**:
- `/invoke` - Submit a new task with a goal
- `/task/{task_id}/status` - Get current task status
- `/task/{task_id}/approve` - Resume a paused task
- `/task/{task_id}/replan` - Replan a task with a new goal
- `/tasks/list` - Get all tasks (for dashboard)

**Port**: 8001

---

### 5. `partner_service.py` - The Worker
**Purpose**: Executes individual task steps using a ReAct (Reasoning + Acting) loop.

**What it does**:
- Implements a ReAct-style execution loop:
  1. **Reason**: AI analyzes the goal and decides what action to take
  2. **Act**: Executes the action (currently simulated)
  3. **Observe**: AI summarizes the result
  4. **Repeat** until goal is completed or deviation detected
- Validates each action with Guardian before execution
- Fetches available tools from Resource Hub
- Logs memory (Thought, Action, Observation) to Resource Hub
- Detects deviations and reports them to Manager

**Why it's important**:
- **Execution**: Actually performs the work to achieve goals
- **Intelligence**: Uses AI to reason about actions
- **Safety**: Validates every action before execution
- **Learning**: Stores execution history for future reference
- **Adaptability**: Can handle unexpected situations and deviations

**Key Features**:
- `/partner/execute_goal` - Execute a single step goal
- ReAct loop with AI reasoning
- Action validation with Guardian
- Memory logging to Resource Hub
- Deviation detection

**Port**: 8002

---

### 6. `resource_hub_service.py` - The Armory/Library
**Purpose**: Central repository for tools, policies, runbooks, and task memory.

**What it does**:
- Stores and serves compliance policies
- Provides a list of available tools for agents
- Implements RAG (Retrieval-Augmented Generation) for semantic search:
  - Vector embeddings using Gemini's text-embedding-004 model
  - Cosine similarity search across runbook, policies, and tools
- Stores short-term task memory (Thought, Action, Observation entries)
- Provides both legacy keyword search and modern vector-based RAG

**Why it's important**:
- **Knowledge Base**: Centralized repository for organizational knowledge
- **RAG**: Enables semantic understanding of queries (not just keyword matching)
- **Memory**: Stores execution history for learning and debugging
- **Policies**: Dynamic policy storage (can be updated without code changes)
- **Tools**: Catalog of available actions agents can take

**Key Features**:
- `/policy/list` - Get compliance policies
- `/tools/list` - Get available tools
- `/rag/query` - Semantic search using vector embeddings
- `/runbook/search` - Legacy keyword-based search
- `/memory/{task_id}` - Store/retrieve task memory
- `/memory/query/{task_id}` - Query memory for insights

**Port**: 8006

---

## 🛠️ **UTILITY MODULES** (Supporting Infrastructure)

### 7. `gemini_client.py` - AI Client Wrapper
**Purpose**: Provides a clean interface to Google's Gemini AI models.

**What it does**:
- Configures Gemini API with API key from environment variables
- Provides helper functions for:
  - `get_model()` - Initialize a Gemini model with system instructions
  - `generate_json()` - Call the model and parse JSON responses
  - `get_embedding()` - Generate vector embeddings for RAG
- Handles errors gracefully (JSON parsing failures, API errors)
- Uses `gemini-flash-latest` for text generation
- Uses `text-embedding-004` for embeddings (768-dimensional vectors)

**Why it's important**:
- **Abstraction**: Hides complexity of Gemini API from services
- **Consistency**: Ensures all services use the same model configuration
- **Error Handling**: Provides fallbacks for API failures
- **Reusability**: Single place to update model versions or settings
- **Embeddings**: Enables RAG functionality across the system

**Key Functions**:
- `get_model(system_instruction)` - Get configured model
- `generate_json(model, prompt_parts)` - Generate and parse JSON
- `get_embedding(text, task_type)` - Generate embeddings

---

### 8. `security.py` - Authentication Module
**Purpose**: Provides API key authentication for all services.

**What it does**:
- Defines a shared secret API key (`mysecretapikey`)
- Implements FastAPI dependency `get_api_key()` that validates the `X-SHIVA-SECRET` header
- Returns `403 Forbidden` if API key is missing or invalid
- Can be applied to all endpoints via FastAPI's `dependencies` parameter

**Why it's important**:
- **Security**: Prevents unauthorized access to services
- **Consistency**: All services use the same authentication mechanism
- **Simplicity**: Easy to add/remove authentication from endpoints
- **Production-Ready**: Foundation for more advanced auth (JWT, OAuth, etc.)

**Note**: In production, this should use environment variables and proper secret management.

---

### 9. `guardian_rules.py` - Rule Engine
**Purpose**: Provides deterministic, fast rule-based validation before LLM fallback.

**What it does**:
- Implements hard deny patterns (rm -rf, shutdown, format disk, /dev/sda)
- Detects prompt injection patterns
- Validates tool allowlists
- Checks parameter restrictions (path prefixes, allowed hosts)
- Performs policy substring matching
- Calculates semantic similarity scores using token overlap
- Parses proposed actions from various formats

**Why it's important**:
- **Performance**: Fast deterministic checks avoid expensive LLM calls
- **Reliability**: Rule-based checks are predictable and testable
- **Security**: Catches obvious threats immediately
- **Cost**: Reduces API costs by filtering out clear violations
- **Fallback**: LLM only called for ambiguous cases

**Key Functions**:
- `deterministic_eval_action()` - Fast action validation
- `deterministic_eval_plan()` - Fast plan validation
- `detect_injection()` - Prompt injection detection
- `hard_deny_match()` - Destructive pattern detection
- `action_matches_plan_score()` - Plan deviation detection

---

## 🚀 **STARTUP & ORCHESTRATION**

### 10. `start_services.py` - Service Launcher
**Purpose**: Convenience script to start all 6 services in parallel.

**What it does**:
- Launches all 6 services as separate subprocesses
- Staggers startup slightly for readable logs
- Handles Ctrl+C to gracefully shutdown all services
- Uses `atexit` to ensure cleanup on exit

**Why it's important**:
- **Convenience**: One command to start everything
- **Development**: Faster than opening 6 terminal windows
- **Testing**: Ensures all services start in correct order
- **Cleanup**: Properly terminates all child processes

**Services Started** (in order):
1. Directory Service (must start first)
2. Overseer Service
3. Resource Hub Service
4. Guardian Service
5. Partner Service
6. Manager Service

---

## 🧪 **TESTING FILES**

### 11. `test_pause_and_approve.py` - Integration Test
**Purpose**: Tests the pause-and-approve workflow for task deviations.

**What it does**:
- Submits a task to Manager
- Polls task status until it pauses due to deviation
- Approves the paused task
- Verifies the task completes after approval

**Why it's important**:
- **Validation**: Ensures pause/resume functionality works
- **Integration**: Tests interaction between Manager, Partner, and Guardian
- **Workflow**: Validates the human-in-the-loop approval process
- **Documentation**: Shows how to use the approval API





### 19. `test_invoke.py` - Basic Integration Test
**Purpose**: Simple test to verify the system works end-to-end.

**What it does**:
- Checks Directory for all services
- Submits a test task
- Verifies task execution
- Tests kill-switch functionality

**Why it's important**:
- **Smoke Test**: Quick verification everything works
- **Example**: Shows how to use the API
- **CI/CD**: Can be run in automated pipelines




## 🏗️ **SYSTEM ARCHITECTURE SUMMARY**

```
User/Test Script
      |
      v
Manager Service (Orchestrator)
      |
      +---> Guardian Service (Validate Plan)
      |           |
      |           v
      |     Resource Hub (Get Policies via RAG)
      |
      +---> Partner Service (Execute Steps)
                  |
                  +---> Guardian Service (Validate Actions)
                  |
                  +---> Resource Hub (Get Tools, Log Memory)

All Services
      |
      +---> Directory Service (Service Discovery)
      |
      +---> Overseer Service (Logging, Kill-Switch, Dashboard)
```

---

## 🔑 **KEY DESIGN PATTERNS**

1. **Microservices Architecture**: Each service has a single responsibility
2. **Service Discovery**: Services find each other via Directory
3. **Event-Driven**: Services communicate via HTTP REST APIs
4. **Two-Tier Validation**: Fast rules + LLM fallback
5. **ReAct Loop**: Partner uses reasoning-action-observation cycle
6. **RAG**: Semantic search for knowledge retrieval
7. **Human-in-the-Loop**: Pause/resume for deviations
8. **Observability**: Centralized logging and monitoring

---

