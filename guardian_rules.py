"""
Deterministic + lightweight-semantic Guardian rule engine.

Provides deterministic evaluation helpers that the guardian service uses before
falling back to the LLM. The functions return dictionaries with the fields:
    {
      "decision": "Allow" | "Deny" | "Ambiguous",
      "reason": str,
      "evidence": str,
      "policy_score": float,
      "requires_human_review": bool (optional)
    }
"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Tuple
import unicodedata


# ---------------------------------------------------------------------------
# Configuration (tuneable)
# ---------------------------------------------------------------------------

ALLOWED_TOOLS = {"run_script", "fetch_data", "restart_service"}

# Per-tool parameter restrictions (example)
PER_TOOL_RULES = {
    "run_script": {
        "path_prefix": "/srv/",  # required prefix for any path param
    },
    "fetch_data": {
        "allowed_hosts": ["api.mycompany.com", "localhost"],
    },
}

# Hard deterministic deny regexes (high severity)
HARD_DENY_REGEX = [
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\bformat\s+disk\b", re.I),
    re.compile(r"\b:/dev/sda\b", re.I),
]

# Prompt-injection indicative patterns (deny or require review)
INJECTION_PATTERNS = [
    r"ignore (previous|earlier) instructions",
    r"forget (previous|earlier) instructions",
    r"role\s*:\s*system",
    r"you are now",
    r"do anything now",
    r"`{3}\s*system",
    r"<script",
]
INJECTION_RX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

# Synonym map for light canonicalization (small & deterministic)
SYNONYMS = {
    "wipe": "delete",
    "purge": "delete",
    "bring down": "shutdown",
    "bring-up": "start",
    "reboot": "restart",
    "remove": "delete",
    "erase": "delete",
    "drop": "delete",
}

# Semantic thresholds (deterministic constants)
SEMANTIC_DENY_THRESHOLD = 0.90  # >= -> automatic deny (very similar to disallow phrase)
SEMANTIC_REVIEW_THRESHOLD = 0.70  # review band

# ---------------------------------------------------------------------------
# Optional: jsonschema usage (kept optional)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - optional dependency
    from jsonschema import ValidationError as JSValidationError
    from jsonschema import validate as js_validate

    JSONSCHEMA_AVAILABLE = True
except Exception:  # pragma: no cover - if jsonschema not installed
    JSONSCHEMA_AVAILABLE = False

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "action_input": {"type": "object"},
    },
    "required": ["action", "action_input"],
    "additionalProperties": True,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_id": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "integer"},
                    "goal": {"type": "string"},
                },
                "required": ["step_id", "goal"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": True,
}


def _try_jsonschema(obj: dict, schema: dict) -> Tuple[bool, str]:
    """Validate using jsonschema if available. Fail-closed on validation error."""

    if not JSONSCHEMA_AVAILABLE:
        return True, ""
    try:
        js_validate(obj, schema)
        return True, ""
    except JSValidationError as exc:  # pragma: no cover - only when jsonschema present
        return False, f"JSON schema validation failed: {exc.message}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LEETS = str.maketrans({
    '0': 'o',
    '1': 'i',
    '2': 'r',  # optional, sometimes used
    '3': 'e',
    '4': 'a',
    '5': 's',
    '6': 'g',
    '7': 't',
    '@': 'a',
    '$': 's',
    '+': 't'
})
# Zero-width characters we aggressively strip before deobfuscation
_ZERO_WIDTH = ['\u200b', '\u200c', '\u200d', '\ufeff']
_IMPERATIVE_VERBS = [
    'execute','run','delete','remove','shutdown','restart','format','wipe','purge','drop','erase','kill'
]

def _remove_zero_width(s: str) -> str:
    for ch in _ZERO_WIDTH:
        s = s.replace(ch, '')
    return s

def _strip_control_chars(s: str) -> str:
    return ''.join(ch for ch in s if unicodedata.category(ch)[0] != 'C')

def _deobfuscate_leet(s: str) -> str:
    """
    Lowercase, map common leet/digit substitutions and collapse non-word runs.
    Returns a cleaned string suitable for token-based matching.
    """
    if not s:
        return ""
    # normalize lowercase and apply mapping
    s1 = s.lower().translate(_LEETS)
    # replace non-word characters with spaces and collapse repeats
    s1 = re.sub(r'[\W_]+', ' ', s1)
    s1 = re.sub(r'\s+', ' ', s1).strip()
    return s1

def _instruction_density(s: str) -> float:
    toks = [t for t in re.findall(r"\w+", s.lower())]
    if not toks:
        return 0.0
    hits = sum(1 for t in toks if t in _IMPERATIVE_VERBS)
    return hits / len(toks)

def canonicalize_text(text: str) -> str:
    """Lowercase, replace synonyms, collapse whitespace deterministically."""

    if not text:
        return ""
    t = text.lower()
    for src, dst in SYNONYMS.items():
        t = t.replace(src, dst)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_interrogative(text: str) -> bool:
    """Return True if the text looks like a question (interrogative phrasing)."""

    if not text:
        return False
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    starters = (
        "should ",
        "can ",
        "may ",
        "would ",
        "could ",
        "is ",
        "are ",
        "do ",
        "does ",
        "did ",
        "will ",
        "shall ",
        "might ",
        "must ",
    )
    return any(t.startswith(s) for s in starters)


def detect_injection(text: str) -> Tuple[bool, List[str], float]:
    """
    Return (is_injection, hits, score)
    - Robust to zero-width masking, leet/digit obfuscation, spaced/collapsed obfuscation.
    - Produces a list of hits and a float score in [0,1].
    """
    if not text:
        return False, [], 0.0

    original = text

    # 1) strip zero-width and control characters first (critical for masked tokens)
    t = _remove_zero_width(original)
    t = _strip_control_chars(t)

    # 2) produce multiple normalized variants
    deob_leet = _deobfuscate_leet(t)                # leet mapped, punctuation removed
    # additional digit->letter pass (extra safety)
    digit_map = str.maketrans({'1': 'i', '0': 'o', '3': 'e', '4': 'a', '5': 's', '7': 't'})
    deob_digits = deob_leet.translate(digit_map)

    # collapsed (no spaces/punctuation) form to catch zero-width / punctuation obfuscation
    collapsed = re.sub(r'[\W_]+', '', deob_digits or "")

    # cleaned original (only whitespace normalized) for punctuation-based checks
    original_clean = re.sub(r'\s+', ' ', original).strip()

    hits: List[str] = []

    # 3) direct injection regex matching (use deob_digits and collapsed)
    m = INJECTION_RX.search(deob_digits) or INJECTION_RX.search(t) or INJECTION_RX.search(original)
    if m:
        hits.append(f"injection_pattern:{m.group(0).strip()}")

    # 4) Hard deny regex checks across normalized variants
    for rx in HARD_DENY_REGEX:
        try:
            if rx.search(deob_digits) or rx.search(deob_leet) or rx.search(t) or rx.search(original):
                hits.append(f"hard_deny_regex:{rx.pattern}")
        except Exception:
            continue

    # 4b) relaxed rm -rf detection (catch obfuscations like rM -rF /)
    try:
        if (re.search(r"r\s*m\W*\s*-?\s*r\W*\s*-?\s*f", deob_digits, re.I)
            or re.search(r"r\W*m\W*-?r\W*-?f", deob_leet, re.I)
            or re.search(r"rm\W*-?rf", original, re.I)
            or re.search(r"rmrf", collapsed, re.I)):
            if not any(h.startswith("hard_deny_regex") for h in hits):
                hits.append("hard_deny_regex:rm-rf-relaxed")
    except Exception:
        pass

    # 5) code fences / html / long code fence detection (original preserves markup fidelity)
    if '```' in original:
        hits.append('code_fence_or_html')
    if '<script' in original.lower():
        hits.append('code_fence_or_html')

    # long code fence detection (lower threshold to catch long payloads)
    codefence_match = re.search(r'```(.{40,})', original, re.S)
    if codefence_match:
        hits.append('long_code_fence')

    # 6) robust role:system detection (works on deobfuscated text and collapsed)
    if re.search(r"\brole\s*[:=]?\s*system\b", deob_digits, re.I) or re.search(r"youarenowrole", collapsed, re.I) or re.search(r"youarenowrole", deob_digits, re.I):
        hits.append('role:system')

    # 7) explicit ignore/forget detection (catch obfuscations: 1gn0re, ign0re, zero-width splits)
    # Patterns to match:
    #  - normal: "ignore previous instructions"
    #  - collapsed: "ignorepreviousinstructions" or "ignoreprevious"
    #  - obfuscated digits: "1gn0re previous"
    # We check both tokenized and collapsed variants.
    ignore_pattern_token = re.search(r"\b(ignore|ign0re|ign0r[e3]|1gn0re)\b\s*(previous|earlier)?\s*(instructions)?", deob_digits, re.I)
    ignore_pattern_collapsed = re.search(r"(ignorepreviousinstructions|ignoreprevious|forgetpreviousinstructions|forgetprevious)", collapsed, re.I)
    if ignore_pattern_token or ignore_pattern_collapsed:
        hits.append("ignore_previous_instructions")

    # 8) instruction density using deob_digits
    instr_density = _instruction_density(deob_digits)
    if instr_density > 0.08:
        hits.append('imperative_density')

    # 9) punctuation noise (use original to capture '!!!' etc.)
    punct_ratio = sum(1 for ch in original if not ch.isalnum() and not ch.isspace()) / max(1, len(original))
    if punct_ratio > 0.10:
        hits.append('high_punctuation')

    # Build a conservative score
    score = 0.0

    # Immediate deny if hard deny matched
    if any(h.startswith('hard_deny_regex') for h in hits):
        return True, hits, 1.0

    if 'long_code_fence' in hits or 'code_fence_or_html' in hits:
        score += 0.40

    if 'role:system' in hits:
        score += 0.35

    if 'imperative_density' in hits:
        score += min(0.35, instr_density * 4.0)

    if 'high_punctuation' in hits:
        score += 0.10

    if any(h.startswith("injection_pattern") for h in hits) or INJECTION_RX.search(deob_digits) or INJECTION_RX.search(collapsed):
        score += 0.35

    if 'ignore_previous_instructions' in hits:
        score += 0.35

    score = max(0.0, min(1.0, score))

    # Some combinations are treated as immediate injection-like
    immediate_injection = False
    if 'long_code_fence' in hits:
        immediate_injection = True
    if 'ignore_previous_instructions' in hits:
        immediate_injection = True
    if 'role:system' in hits:
        immediate_injection = True
    if 'imperative_density' in hits and 'high_punctuation' in hits:
        immediate_injection = True

    is_injection = immediate_injection or (score >= SEMANTIC_REVIEW_THRESHOLD)

    return bool(is_injection), hits, float(round(score, 6))




def hard_deny_match(text: str) -> Tuple[bool, List[str]]:
    """High-confidence destructive patterns."""

    if not text:
        return False, []
    hits: List[str] = []
    for rx in HARD_DENY_REGEX:
        if rx.search(text):
            hits.append(rx.pattern)
    return (len(hits) > 0), hits


def normalize_policies(policies: List[str]) -> Dict[str, List[str]]:
    """Convert simple 'Disallow: token' lines into buckets."""

    buckets = {"disallow": []}
    for policy in policies or []:
        parts = policy.split(":", 1)
        if len(parts) == 2:
            key = parts[0].strip().lower()
            val = parts[1].strip()
            if key == "disallow" and val:
                buckets["disallow"].append(val.lower())
    return buckets


def policy_disallow_substring(text: str, policy_buckets: Dict[str, List[str]]) -> Tuple[bool, List[str]]:
    """Simple deterministic substring match against policy list."""

    if not text:
        return False, []
    hits: List[str] = []
    lowered = text.lower()
    for needle in policy_buckets.get("disallow", []):
        if needle in lowered:
            hits.append(needle)
    return (len(hits) > 0), hits


def token_overlap_score(a: str, b: str) -> float:
    """Deterministic similarity score between two strings using token overlap."""

    if not a or not b:
        return 0.0

    def _tokens(s: str) -> List[str]:
        s2 = re.sub(r"[^\w\s]", " ", canonicalize_text(s))
        return [tok for tok in s2.split() if tok]

    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    intersection = ta.intersection(tb)
    union = ta.union(tb)
    return len(intersection) / len(union)


def semantic_policy_score(text: str, policy_buckets: Dict[str, List[str]]) -> float:
    """Return the max token-overlap score between text and any disallow policy phrase."""

    max_score = 0.0
    for policy_str in policy_buckets.get("disallow", []):
        score = token_overlap_score(text, policy_str)
        if score > max_score:
            max_score = score
    return max_score


# ---------------------------------------------------------------------------
# Parsing proposed actions
# ---------------------------------------------------------------------------

def parse_proposed_action(proposed_action: str) -> Tuple[bool, Dict[str, Any], str]:
    """Parse proposed_action string into structured {action, action_input}."""

    if not isinstance(proposed_action, str) or not proposed_action.strip():
        return False, {}, "proposed_action must be a non-empty string"

    snippet = proposed_action.strip()

    # Attempt literal dict parsing first
    try:
        if snippet.startswith("{"):
            obj = ast.literal_eval(snippet)
            if not isinstance(obj, dict):
                return False, {}, "Parsed proposed_action is not an object"
            if "action" in obj and "action_input" in obj:
                return True, {"action": obj["action"], "action_input": obj["action_input"]}, ""
            if "tool" in obj and "action_input" in obj:
                return True, {"action": obj["tool"], "action_input": obj["action_input"]}, ""
            return False, {}, "Object must contain 'action' and 'action_input'"
    except Exception as exc:
        return False, {}, f"Failed to parse object: {exc}"

    # Fallback: "tool: { ... }"
    parts = snippet.split(":", 1)
    if len(parts) != 2:
        return False, {}, "Expected format 'tool: {...}' or a JSON-like object"
    tool_name = parts[0].strip()
    remainder = parts[1].strip()
    try:
        payload = ast.literal_eval(remainder)
        if not isinstance(payload, dict):
            return False, {}, "action_input must be an object"
    except Exception as exc:
        return False, {}, f"Failed to parse action_input: {exc}"

    return True, {"action": tool_name, "action_input": payload}, ""


# ---------------------------------------------------------------------------
# Deterministic evaluators
# ---------------------------------------------------------------------------

def deterministic_eval_action(
    proposed_action: str,
    context: Dict[str, Any],
    policies: List[str],
) -> Dict[str, Any]:
    """Deterministically evaluate a proposed action before LLM fallback."""

    # 1. Malformed -> Deny
    ok, parsed_action, err = parse_proposed_action(proposed_action)
    if not ok:
        return {
            "decision": "Deny",
            "reason": f"Malformed action: {err}",
            "evidence": proposed_action,
            "policy_score": 0.0,
        }

    # 2. Hard deny patterns -> Deny
    hd, hd_hits = hard_deny_match(proposed_action)
    if hd:
        return {
            "decision": "Deny",
            "reason": f"Hard deny pattern: {hd_hits}",
            "evidence": hd_hits,
            "policy_score": 1.0,
        }

    # 3. Injection patterns -> use numeric score thresholds (less aggressive)
    # detect_injection -> (is_injection: bool, hits: List[str], score: float)
    inj, inj_hits, inj_score = detect_injection(proposed_action)
    # Deny only at deny-threshold (very high confidence)
    if inj_score >= SEMANTIC_DENY_THRESHOLD:
        return {
            "decision": "Deny",
            "reason": f"Prompt-injection detected (high_conf): {inj_hits}",
            "evidence": inj_hits,
            "policy_score": inj_score,
        }
    # Ambiguous (human review) only when in the review band
    if inj_score >= SEMANTIC_REVIEW_THRESHOLD:
        return {
            "decision": "Ambiguous",
            "reason": f"Prompt-injection suspected (review): {inj_hits}",
            "evidence": inj_hits,
            "policy_score": inj_score,
            "requires_human_review": True
        }
    # If inj_score < SEMANTIC_REVIEW_THRESHOLD -> treat as non-actionable signal and continue checks

    # 4. Tool allowlist -> if unknown tool -> Ambiguous (ask LLM)
    action_name = parsed_action["action"]
    if action_name not in ALLOWED_TOOLS:
        return {
            "decision": "Ambiguous",
            "reason": f"Unsupported tool '{action_name}', require LLM/human review",
            "evidence": action_name,
            "policy_score": 0.0,
        }

    # 5. Policy substring match -> Deny
    for policy in policies or []:
        if policy.lower().startswith("disallow:"):
            token = policy.split(":", 1)[1].strip().lower()
            if token and token in proposed_action.lower():
                return {
                    "decision": "Deny",
                    "reason": f"Policy matched: {token}",
                    "evidence": token,
                    "policy_score": 1.0,
                }

    # 6. Parameter checks -> if suspicious -> Ambiguous (LLM review), else Allow
    if action_name == "run_script":
        path = str(parsed_action["action_input"].get("path", ""))
        if not path.startswith(PER_TOOL_RULES["run_script"]["path_prefix"]):
            return {
                "decision": "Ambiguous",
                "reason": "run_script path outside safe prefix",
                "evidence": path,
                "policy_score": 0.4,
            }

    if action_name == "fetch_data":
        url = str(parsed_action["action_input"].get("url", ""))
        allowed = PER_TOOL_RULES["fetch_data"]["allowed_hosts"]
        if not any(host in url for host in allowed):
            return {
                "decision": "Ambiguous",
                "reason": "fetch_data target not in allowed hosts",
                "evidence": url,
                "policy_score": 0.4,
            }

    # no issues -> Allow
    return {
        "decision": "Allow",
        "reason": "Passes deterministic checks",
        "evidence": "",
        "policy_score": 0.0,
    }



def deterministic_eval_plan(plan: Dict[str, Any], policies: List[str], llm_review_fn=None) -> Dict[str, Any]:
    """
    Deterministically evaluate a high-level execution plan.

    Enhancements:
    - Accepts optional llm_review_fn(callback) to make an LLM-assisted decision when a step
      crosses the 'review' threshold (SEMANTIC_REVIEW_THRESHOLD) but is below the deny threshold.
      The llm_review_fn should be a callable with signature:
          llm_review_fn(task_id: str, plan_or_step: dict, policies: list) -> {"decision": "Allow"|"Deny"|"Ambiguous", "reason": str, ...}
      If llm_review_fn is None or the call fails, the function falls back to Ambiguous (require human review).

    - Keeps fail-closed semantics (hard deny -> Deny).
    """

    # Basic structural validation
    if not isinstance(plan, dict) or "steps" not in plan:
        return {
            "decision": "Deny",
            "reason": "Malformed plan",
            "evidence": str(plan),
            "policy_score": 1.0,
        }

    # Optional jsonschema validation (fail-closed on schema errors)
    ok, err = _try_jsonschema(plan, PLAN_SCHEMA)
    if not ok:
        return {
            "decision": "Deny",
            "reason": err,
            "evidence": str(plan),
            "policy_score": 1.0,
        }

    steps = plan.get("steps", [])
    # Plan too complex -> Deny (fail-closed)
    if len(steps) > 10:
        return {
            "decision": "Deny",
            "reason": "Plan too complex (>10 steps)",
            "evidence": str(len(steps)),
            "policy_score": 1.0,
        }

    # Normalize policies into buckets for fast checks
    policy_buckets = normalize_policies(policies or [])

    # Iterate steps and apply deterministic checks
    for step in steps:
        goal = step.get("goal", "")
        sid = step.get("step_id", "?")

        # 1) Hard deny patterns (high-confidence destructive commands)
        hd, hd_hits = hard_deny_match(goal)
        if hd:
            # For planning-level destructive language, prefer human review (Ambiguous),
            # but treat explicit destructive matches as high risk and mark for review.
            return {
                "decision": "Ambiguous",
                "reason": f"Restricted/hard-deny term present in plan step {sid}",
                "evidence": str(hd_hits),
                "policy_score": 0.95,
                "requires_human_review": True
            }

        # 2) Prompt-injection detection
        inj, inj_hits, inj_score = detect_injection(goal)

        # If extremely high confidence of injection, deny immediately
        if inj_score >= SEMANTIC_DENY_THRESHOLD:
            return {
                "decision": "Deny",
                "reason": f"High-confidence prompt-injection detected in plan step {sid}",
                "evidence": inj_hits,
                "policy_score": float(inj_score),
            }

        # If it crosses the review threshold, attempt LLM-assisted triage if available
        if SEMANTIC_REVIEW_THRESHOLD <= inj_score < SEMANTIC_DENY_THRESHOLD:
            # If caller provided an llm_review_fn, try it (best-effort).
            if llm_review_fn:
                try:
                    # Provide the LLM with the full plan step and policies.
                    # llm_review_fn is expected to return a dict with 'decision' and 'reason'.
                    llm_resp = llm_review_fn(task_id=step.get("plan_task_id", "N/A"), plan={"step": step}, policies=policies)
                    if isinstance(llm_resp, dict):
                        llm_dec = llm_resp.get("decision")
                        llm_reason = llm_resp.get("reason", "LLM-assisted review")
                        llm_score = float(llm_resp.get("policy_score", inj_score))
                        # Accept LLM Allow/Deny if valid
                        if llm_dec == "Deny":
                            return {
                                "decision": "Deny",
                                "reason": f"LLM-assisted deny for step {sid}: {llm_reason}",
                                "evidence": inj_hits,
                                "policy_score": llm_score
                            }
                        elif llm_dec == "Allow":
                            # Continue to next step (treat as pass for this step)
                            continue
                        else:
                            # LLM returned Ambiguous -> require human review
                            return {
                                "decision": "Ambiguous",
                                "reason": f"LLM-assisted review inconclusive for step {sid}: {llm_reason}",
                                "evidence": inj_hits,
                                "policy_score": llm_score,
                                "requires_human_review": True
                            }
                    else:
                        # Non-dict response -> fall back to Ambiguous
                        return {
                            "decision": "Ambiguous",
                            "reason": f"Prompt-injection suspected in plan step {sid}; requires human review (LLM returned invalid format)",
                            "evidence": inj_hits,
                            "policy_score": float(inj_score),
                            "requires_human_review": True
                        }
                except Exception:
                    # Best-effort only: if LLM call fails, require human review
                    return {
                        "decision": "Ambiguous",
                        "reason": f"Prompt-injection suspected in plan step {sid}; LLM triage failed; requires human review",
                        "evidence": inj_hits,
                        "policy_score": float(inj_score),
                        "requires_human_review": True
                    }
            else:
                # No LLM available -> require human review
                return {
                    "decision": "Ambiguous",
                    "reason": f"Prompt-injection suspected in plan step {sid}; requires human review",
                    "evidence": inj_hits,
                    "policy_score": float(inj_score),
                    "requires_human_review": True
                }

        # 3) Exact substring policy matches (disallow entries)
        policy_hit, policy_terms = policy_disallow_substring(goal, policy_buckets)
        if policy_hit:
            return {
                "decision": "Ambiguous",
                "reason": f"Policy term {policy_terms} found in plan step {sid}",
                "evidence": goal,
                "policy_score": 0.9,
                "requires_human_review": True
            }

        # 4) Lightweight semantic similarity for policy terms
        sem_score = semantic_policy_score(goal, policy_buckets)
        if sem_score >= SEMANTIC_DENY_THRESHOLD:
            return {
                "decision": "Ambiguous",
                "reason": f"Plan step {sid} semantically similar to restricted policy",
                "evidence": goal,
                "policy_score": float(sem_score),
                "requires_human_review": True
            }

    # If we scanned all steps and found nothing to deny/review -> Allow
    return {
        "decision": "Allow",
        "reason": "Plan passes deterministic checks",
        "evidence": "",
        "policy_score": 0.0,
    }



# ---------------------------------------------------------------------------
# Extra public helpers required by other modules
# ---------------------------------------------------------------------------

def _plan_match_score(action_text: str, plan: Dict[str, Any]) -> Tuple[float, int]:
    """
    Internal helper: returns (best_score, best_step_id)
    using token_overlap_score between action_text and each step.goal.
    """
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


def action_matches_plan_score(action_text: str, plan: Dict[str, Any]) -> float:
    """
    Public helper for other services:
    Returns the best token-overlap score (0.0 - 1.0) between action_text and any step in plan.

    This is a thin wrapper around the internal _plan_match_score for convenience.
    """
    best_score, best_step = _plan_match_score(action_text, plan)
    return float(best_score)
