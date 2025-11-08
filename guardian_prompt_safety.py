"""
Dynamic, context-aware prompt-injection analyzer for PROJECT SHIVA Guardian.

Entrypoint: analyze_payload(payload, policies=None)
 - For action payloads (contains "proposed_action") returns:
    {
      "decision": "Allow"|"Ambiguous"|"Deny",
      "approved": bool,
      "score": float,
      "one_liner": str,
      "reasons": [...],
      "details": {...}
    }
 - For plan payloads (contains "plan") similar shape.

Design:
 - Deterministic short-circuits for hard denies & injection regexes.
 - Semantic scoring (token overlap) using guardian_rules helpers.
 - Context-aware boosts (off-hours, high-priority).
 - Memory/RAG best-effort checks via Resource Hub (if available).
"""

import time
import math
import requests
from typing import Dict, Any, List, Optional, Tuple

from guardian_rules import (
    parse_proposed_action,
    hard_deny_match,
    detect_injection,
    normalize_policies,
    semantic_policy_score,
    token_overlap_score,
)

# Config (tuneable)
RESOURCE_HUB_BASE = "http://localhost:8006"
HISTORY_LOOKBACK = 8
OFF_HOURS = (0, 6)                 # [start_hour, end_hour)
PRIORITY_HIGH_BOOST = 0.15
SEMANTIC_REVIEW_THRESHOLD = 0.70
SEMANTIC_DENY_THRESHOLD = 0.90
PLAN_MATCH_THRESHOLD = 0.50

def _now_hour() -> int:
    return time.localtime().tm_hour

def _is_off_hours() -> bool:
    start, end = OFF_HOURS
    h = _now_hour()
    if start <= end:
        return start <= h < end
    return h >= start or h < end

def _http_get_json(url: str, timeout: float = 2.0) -> Optional[Any]:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None

def fetch_short_term_memory(task_id: str) -> List[Dict[str, Any]]:
    """Best-effort; do not raise if Resource Hub unavailable."""
    try:
        body = _http_get_json(f"{RESOURCE_HUB_BASE}/memory/{task_id}")
        if isinstance(body, list):
            return body[-HISTORY_LOOKBACK:]
    except Exception:
        pass
    return []

def _score_from_components(components: List[float]) -> float:
    # Combine independent risk components conservatively
    s = 1 - math.prod([1 - max(0.0, min(1.0, c)) for c in components]) if components else 0.0
    return max(0.0, min(1.0, s))

def _one_liner(decision: str, reasons: List[str]) -> str:
    if not reasons:
        return f"{decision} — no explicit reason"
    # Prefer short, first reason
    return f"{decision} — {reasons[0]}"[:200]

def analyze_action_payload(payload: Dict[str, Any], policies: Optional[List[str]] = None) -> Dict[str, Any]:
    task_id = payload.get("task_id", "N/A")
    proposed_action = str(payload.get("proposed_action", "") or "")
    context = payload.get("context", {}) or {}
    approved_plan = payload.get("approved_plan")
    policies = policies or []

    reasons: List[str] = []
    components: List[float] = []

    # 1) parse
    ok_parse, parsed, parse_err = parse_proposed_action(proposed_action)
    if not ok_parse:
        reasons.append(f"malformed_action:{parse_err}")
        components.append(0.95)
        return _finalize("Deny", reasons, components, {"parse_err": parse_err})

    # 2) hard deny
    hd, hd_hits = hard_deny_match(proposed_action)
    if hd:
        reasons.append(f"hard_deny:{hd_hits}")
        components.append(0.99)
        return _finalize("Deny", reasons, components, {"hd_hits": hd_hits})

    # 3) injection heuristics — use full 3-value signature (is_injection, hits, score)
    inj_flag, inj_hits, inj_score = detect_injection(proposed_action)
    # Deny only at high-confidence deny threshold
    if inj_score >= SEMANTIC_DENY_THRESHOLD:
        reasons.append(f"prompt_injection:{inj_hits}")
        components.append(0.99)
        return _finalize("Deny", reasons, components, {"inj_hits": inj_hits, "inj_score": inj_score})
    # Ambiguous (human review) only when in the review band
    if inj_score >= SEMANTIC_REVIEW_THRESHOLD:
        reasons.append(f"prompt_injection:{inj_hits}")
        components.append(inj_score)
        return _finalize("Ambiguous", reasons, components, {"inj_hits": inj_hits, "inj_score": inj_score})

    # 4) policy substring/semantic
    pb = normalize_policies(policies)
    lowered = proposed_action.lower()
    for p in pb.get("disallow", []):
        if p and p in lowered:
            reasons.append(f"policy_substring:{p}")
            components.append(0.99)
            return _finalize("Deny", reasons, components, {"policy_term": p})

    sem = semantic_policy_score(proposed_action, pb)
    components.append(sem)
    if sem >= SEMANTIC_DENY_THRESHOLD:
        reasons.append(f"semantic_policy:{sem:.2f}")
        return _finalize("Deny", reasons, components, {"semantic_score": sem})
    if SEMANTIC_REVIEW_THRESHOLD <= sem < SEMANTIC_DENY_THRESHOLD:
        reasons.append(f"semantic_policy:{sem:.2f}")
        components.append(0.1)  # bias toward review (small)
        # treat as review-band -> ambiguous
        return _finalize("Ambiguous", reasons, components, {"semantic_score": sem})

    # 5) context boosts
    if context.get("priority", "").lower() == "high":
        components.append(PRIORITY_HIGH_BOOST)
        reasons.append("priority_high")
    if _is_off_hours():
        components.append(0.05)
        reasons.append("off_hours")

    # 6) approved plan cross-check
    if approved_plan:
        action_text = f"{parsed.get('action')} {str(parsed.get('action_input', {}))}"
        best_score, best_step = _plan_match_score(action_text, approved_plan)
        components.append(max(0.0, 1.0 - best_score) * 0.35)
        reasons.append(f"plan_match:{best_score:.2f}")
        if best_score < PLAN_MATCH_THRESHOLD:
            reasons.append(f"plan_mismatch_best:{best_score:.2f}")
            return _finalize("Ambiguous", reasons, components, {"plan_score": best_score})

    # 7) short-term memory heuristic
    mem = fetch_short_term_memory(task_id)
    mem_text = str(mem).lower()
    if any(k in mem_text for k in ("error", "deviation", "failed")):
        components.append(0.2)
        reasons.append("memory_previous_failures")

    # 8) tool allowlist
    from guardian_rules import ALLOWED_TOOLS, PER_TOOL_RULES
    act = parsed.get("action")
    if act not in ALLOWED_TOOLS:
        reasons.append(f"unsupported_tool:{act}")
        components.append(0.6)
        return _finalize("Ambiguous", reasons, components, {"tool": act})
    if act == "run_script":
        path = str(parsed.get("action_input", {}).get("path", ""))
        prefix = PER_TOOL_RULES.get("run_script", {}).get("path_prefix", "")
        if prefix and not path.startswith(prefix):
            reasons.append("run_script_path_outside_prefix")
            components.append(0.4)
            return _finalize("Ambiguous", reasons, components, {"path": path})
    if act == "fetch_data":
        url = str(parsed.get("action_input", {}).get("url", ""))
        allowed_hosts = PER_TOOL_RULES.get("fetch_data", {}).get("allowed_hosts", [])
        if not any(h in url for h in allowed_hosts):
            reasons.append("fetch_data_target_not_allowed")
            components.append(0.45)
            return _finalize("Ambiguous", reasons, components, {"url": url})

    # final - allow
    return _finalize("Allow", reasons, components, {"memory_count": len(mem)})


def analyze_plan_payload(payload: Dict[str, Any], policies: Optional[List[str]] = None) -> Dict[str, Any]:
    task_id = payload.get("task_id", "N/A")
    plan = payload.get("plan", {}) or {}
    policies = policies or []
    reasons: List[str] = []
    components: List[float] = []

    if not isinstance(plan, dict) or "steps" not in plan:
        reasons.append("malformed_plan")
        components.append(0.95)
        return _finalize("Deny", reasons, components, {"plan": str(plan)})

    steps = plan.get("steps", [])
    if len(steps) > 10:
        reasons.append("plan_too_complex")
        components.append(0.99)
        return _finalize("Deny", reasons, components, {"steps": len(steps)})

    pb = normalize_policies(policies)
    max_sem = 0.0
    for s in steps:
        goal = s.get("goal", "")
        hd, hd_hits = hard_deny_match(goal)
        if hd:
            reasons.append(f"hard_deny_in_step:{s.get('step_id')}")
            components.append(0.9)
            return _finalize("Ambiguous", reasons, components, {"hd_hits": hd_hits})

        # use 3-value detect_injection
        inj_flag, inj_hits, inj_score = detect_injection(goal)
        if inj_score >= SEMANTIC_DENY_THRESHOLD:
            reasons.append(f"injection_high_in_step:{s.get('step_id')}")
            components.append(0.95)
            return _finalize("Deny", reasons, components, {"inj_hits": inj_hits, "inj_score": inj_score})
        if inj_score >= SEMANTIC_REVIEW_THRESHOLD:
            reasons.append(f"injection_suspected_in_step:{s.get('step_id')}")
            components.append(inj_score)
            return _finalize("Ambiguous", reasons, components, {"inj_hits": inj_hits, "inj_score": inj_score})

        sem_score = semantic_policy_score(goal, pb)
        if sem_score > max_sem:
            max_sem = sem_score

    components.append(max_sem)
    if max_sem >= SEMANTIC_DENY_THRESHOLD:
        reasons.append(f"plan_semantic:{max_sem:.2f}")
        return _finalize("Ambiguous", reasons, components, {"semantic_max": max_sem})

    if _is_off_hours():
        components.append(0.05)
        reasons.append("plan_off_hours")

    return _finalize("Allow", reasons, components, {"steps": len(steps)})


# helpers
def _plan_match_score(action_text: str, plan: Dict[str, Any]) -> Tuple[float, int]:
    if not isinstance(plan, dict):
        return 0.0, -1
    steps = plan.get("steps", []) or []
    best = 0.0
    best_id = -1
    for s in steps:
        g = s.get("goal", "")
        score = token_overlap_score(action_text, g)
        if score > best:
            best = score
            best_id = s.get("step_id", -1)
    return best, best_id

def _finalize(decision: str, reasons: List[str], components: List[float], details: Dict[str, Any]):
    score = _score_from_components(components)
    if decision == "Deny":
        approved = False
    elif decision == "Ambiguous":
        approved = False
    else:
        if score > 0.8:
            decision = "Ambiguous"
            approved = False
            reasons.insert(0, f"high_risk_score:{score:.2f}")
        else:
            approved = True
    return {
        "decision": decision,
        "approved": bool(approved),
        "score": round(score, 3),
        "one_liner": _one_liner(decision, reasons),
        "reasons": reasons,
        "details": details
    }

def analyze_payload(payload: Dict[str, Any], policies: Optional[List[str]] = None) -> Dict[str, Any]:
    if "proposed_action" in payload:
        return analyze_action_payload(payload, policies)
    if "plan" in payload:
        return analyze_plan_payload(payload, policies)
    return {
        "decision": "Deny",
        "approved": False,
        "score": 1.0,
        "one_liner": "Deny — missing 'plan' or 'proposed_action'",
        "reasons": ["missing_payload_field"],
        "details": {}
    }
