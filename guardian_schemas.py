# guardian_schemas.py
ACTION_DECISION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Guardian Action Validation Response",
    "type": "object",
    "required": ["decision", "reason"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["Allow", "Deny", "Ambiguous"],
            "description": "The Guardian's final decision for this action."
        },
        "reason": {
            "type": "string",
            "description": "One-line justification for the decision."
        },
        "evidence": {
            "type": ["string", "array"],
            "description": "Optional extra evidence or findings supporting the decision."
        },
        "policy_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "A numeric confidence score."
        },
        "requires_human_review": {
            "type": "boolean",
            "description": "If true, the action should be paused for operator review."
        }
    },
    "additionalProperties": True
}

PLAN_VALIDATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Guardian Plan Validation Response",
    "type": "object",
    "required": ["decision", "reason", "warnings"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["Allow", "Deny", "Ambiguous"],
            "description": "Final verdict on whether this plan can proceed."
        },
        "reason": {
            "type": "string",
            "description": "High-level explanation for the decision."
        },
        "warnings": {
            "type": "array",
            "description": "Optional warning messages (e.g. risk flags or soft violations).",
            "items": {
                "type": "string"
            }
        },
        "policy_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        },
        "requires_human_review": {
            "type": "boolean"
        },
        "evidence": {
            "type": ["string", "array"]
        }
    },
    "additionalProperties": True
}

RAG_RESPONSE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Resource Hub RAG Query Response",
    "type": "object",
    "required": ["documents"],
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["content", "score"],
                "properties": {
                    "content": {"type": "string"},
                    "score": {"type": "number"}
                }
            }
        },
        "source": {"type": "string"},
        "query": {"type": "string"}
    },
    "additionalProperties": True
}
