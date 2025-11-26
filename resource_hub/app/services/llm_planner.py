# app/services/llm_planner.py

import json
import re
import uuid
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, ValidationError

from app.core.gemini_client import ask_gemini
from core.logging_client import send_log
from app.core.config import settings

# ============================================================
# PLAN SCHEMA (STRICT & SHIVA-COMPATIBLE)
# ============================================================
class PlanStep(BaseModel):
    step_id: int = Field(..., description="Sequential step id (1..N)")
    title: str = Field(..., description="Short title for the step")
    description: str = Field(..., description="Actionable description for the step")
    estimated_minutes: Optional[int] = Field(None, description="Estimated minutes to complete")
    approvals_required: bool = Field(False, description="Whether human approval is required")
    approver_role: Optional[str] = Field(None, description="Role responsible for approval")
    required_services: List[str] = Field(default_factory=list, description="Partner/Resource services needed")
    dependencies: List[int] = Field(default_factory=list, description="Steps that must finish before this one")
    action_endpoint: Optional[str] = Field(None, description="Partner endpoint to execute the step")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")

class Plan(BaseModel):
    goal: str
    steps: List[PlanStep]


# ============================================================
# LLM PROMPT TEMPLATE
# ============================================================
PROMPT_TEMPLATE = """
Below is an example JSON structure representing steps in a conceptual outline.
Fill in a similar structure for the given goal. Keep the meaning conceptual and
non-operational. Do not include any real-world instructions.

Example format:
[
  {
    "step_id": 1,
    "title": "Example step",
    "description": "A conceptual explanation.",
    "estimated_minutes": null,
    "approvals_required": false,
    "approver_role": null,
    "required_services": [],
    "dependencies": [],
    "action_endpoint": null,
    "metadata": {"conceptual": true}
  }
]

Now produce only the JSON array (no explanation) for this goal:
"{goal}"

Context:
{context}
"""


# ============================================================
# JSON Extraction Helper
# ============================================================
def extract_json(raw: str):
    """Safely extract a JSON array from LLM output."""
    if not raw:
        return None

    txt = raw.strip()

    # Direct JSON
    try:
        parsed = json.loads(txt)
        if isinstance(parsed, list):
            return parsed
    except:
        pass

    # Extract JSON array substring
    m = re.search(r"\[[\s\S]*\]", txt)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return parsed
        except:
            pass

    return None


# ============================================================
# GENERIC DETERMINISTIC FALLBACK PLAN
# (Domain-neutral, SHIVA-compatible, goal-aware)
# ============================================================
def fallback_plan(goal: str) -> List[Dict]:
    """
    Generic plan used ONLY when LLM fails.
    Always 4 deterministic steps.
    Works for ANY goal.
    """
    return [
        {
            "step_id": 1,
            "title": "Clarify the goal",
            "description": f"Review the provided goal '{goal}' and confirm the expected outcome.",
            "estimated_minutes": 5,
            "approvals_required": False,
            "approver_role": None,
            "required_services": [],
            "dependencies": [],
            "action_endpoint": None,
            "metadata": {"fallback": True},
        },
        {
            "step_id": 2,
            "title": "Identify required resources",
            "description": "Determine which systems, tools, or services may be needed to accomplish the goal.",
            "estimated_minutes": 10,
            "approvals_required": False,
            "approver_role": None,
            "required_services": [],
            "dependencies": [1],
            "action_endpoint": None,
            "metadata": {"fallback": True},
        },
        {
            "step_id": 3,
            "title": "Draft an initial plan",
            "description": "Create a high-level sequence of actions that could achieve the desired result.",
            "estimated_minutes": 10,
            "approvals_required": False,
            "approver_role": None,
            "required_services": [],
            "dependencies": [1, 2],
            "action_endpoint": None,
            "metadata": {"fallback": True},
        },
        {
            "step_id": 4,
            "title": "Prepare communication summary",
            "description": "Draft a summary describing the plan and expected impact, ready to notify the appropriate team or stakeholders.",
            "estimated_minutes": 5,
            "approvals_required": False,
            "approver_role": None,
            "required_services": [],
            "dependencies": [3],
            "action_endpoint": None,
            "metadata": {"fallback": True},
        }
    ]


# ============================================================
# MAIN PLAN GENERATOR
# ============================================================
async def generate_plan_steps(goal: str, context: dict = None) -> List[Dict]:
    """
    Generates a SHIVA-compatible plan using LLM.
    Automatically falls back to deterministic generic plan if LLM fails.
    """
    context = context or {}

    prompt = PROMPT_TEMPLATE.format(
        goal=goal,
        context=json.dumps(context, indent=2)
    )

    raw = ask_gemini(prompt, max_output_tokens=400)
    print("🧪 RAW GEMINI OUTPUT:", repr(raw))
    arr = extract_json(raw)
    if not arr:
        send_log(settings.SERVICE_NAME, None, "WARN", "LLM returned invalid JSON → using generic fallback")
        return fallback_plan(goal)

    normalized = []

    try:
        for i, item in enumerate(arr):
            if isinstance(item, str):
                # Convert string → basic step
                ps = {
                    "step_id": i + 1,
                    "title": item[:60],
                    "description": item,
                    "estimated_minutes": None,
                    "approvals_required": False,
                    "approver_role": None,
                    "required_services": [],
                    "dependencies": [],
                    "action_endpoint": None,
                    "metadata": {},
                }

            elif isinstance(item, dict):
                # Apply defaults cleanly
                ps = {
                    "step_id": item.get("step_id", i + 1),
                    "title": item.get("title") or (item.get("description", "")[:60] or f"Step {i+1}"),
                    "description": item.get("description", ""),
                    "estimated_minutes": item.get("estimated_minutes"),
                    "approvals_required": bool(item.get("approvals_required", False)),
                    "approver_role": item.get("approver_role"),
                    "required_services": item.get("required_services", []),
                    "dependencies": item.get("dependencies", []),
                    "action_endpoint": item.get("action_endpoint"),
                    "metadata": item.get("metadata", {}),
                }

            else:
                raise ValueError("Unrecognized step format.")

            normalized.append(ps)

        # Validate via Pydantic
        validated = []
        for ps in normalized:
            ps["step_id"] = int(ps["step_id"])
            validated.append(PlanStep(**ps))

        # Sort steps by ID
        validated.sort(key=lambda s: s.step_id)

        # Validate dependencies
        ids = {s.step_id for s in validated}
        for s in validated:
            for d in s.dependencies:
                if d not in ids:
                    raise ValueError(f"Invalid dependency {d} for step {s.step_id}")

        return [s.dict() for s in validated]

    except Exception as e:
        send_log(settings.SERVICE_NAME, None, "WARN", f"Plan validation failed → using fallback. Error: {e}")
        return fallback_plan(goal)
