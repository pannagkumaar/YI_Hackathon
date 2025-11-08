# gemini_client.py - Client for Google Gemini API with safe JSON extraction
import google.generativeai as genai
import os
import json
from typing import List, Optional, Dict, Any
import dotenv
import re
import time
try:
    from jsonschema import validate as js_validate, ValidationError as JSValidationError
    JSONSCHEMA_AVAILABLE = True
except Exception:
    JSONSCHEMA_AVAILABLE = False


dotenv.load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    # Defer raising in some test contexts; but keep it loud
    raise ValueError("GOOGLE_API_KEY environment variable not set.")

genai.configure(api_key=GOOGLE_API_KEY)

generation_config = {
    "temperature": 0.0,  # use low temp for safety-by-default in decision tasks
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 1024,
    "response_mime_type": "application/json",
}


def get_model(system_instruction: str = None):
    return genai.GenerativeModel(
        model_name="models/gemini-flash-latest",
        generation_config=generation_config,
        system_instruction=system_instruction
    )


# --- New safe JSON extraction + schema checker ---
def _extract_json_text(raw: str) -> Optional[str]:
    """
    Extract the first top-level JSON object or array from raw text.
    This handles cases where model leaks commentary before/after JSON.

    Tries multiple heuristics:
     - balanced braces match for the earliest top-level object/array
     - regex to find the first {...} or [...] block
     - fallback: find a line that *looks* like JSON
    """
    if not raw:
        return None
    s = raw.strip()

    # 1) try to find a top-level JSON object or array with balanced braces scanning
    # This is conservative but effective for many outputs.
    stack = []
    start_idx = None
    for i, ch in enumerate(s):
        if ch == '{' or ch == '[':
            if start_idx is None:
                start_idx = i
            stack.append(ch)
        elif ch == '}' or ch == ']':
            if not stack:
                # unmatched closing - ignore
                continue
            opening = stack.pop()
            # when stack emptied, we likely found a top-level JSON block
            if not stack and start_idx is not None:
                candidate = s[start_idx:i+1]
                # quick sanity check: must start with { or [
                if candidate[0] in ('{', '[') and candidate[-1] in ('}', ']'):
                    return candidate

    # 2) fallback regex (less precise but catches simple cases)
    obj_match = re.search(r"(\{(?:.|\n)*\})", s)
    arr_match = re.search(r"(\[(?:.|\n)*\])", s)
    candidate = None
    if obj_match and arr_match:
        candidate = obj_match if obj_match.start() < arr_match.start() else arr_match
    else:
        candidate = obj_match or arr_match
    if candidate:
        return candidate.group(1)

    # 3) last-resort: find any line that looks like JSON
    for line in s.splitlines():
        line = line.strip()
        if (line.startswith("{") and line.endswith("}")) or (line.startswith("[") and line.endswith("]")):
            return line

    return None

# --- Backwards-compatible helper expected by tests -------------------------
def _validate_decision_schema(obj: dict, expected_keys: list) -> bool:
    """
    Minimal compatibility wrapper used by unit tests:
    - In older iterations tests imported _validate_decision_schema(obj, expected_keys)
      which simply checked that expected keys exist (simple structural check).
    - Keep that behaviour, but prefer the richer _validate_schema when a JSON Schema
      dict is provided via 'expected_keys' (tests pass a list of required keys).
    """
    # If caller passed a full jsonschema dict accidentally, delegate to _validate_schema
    try:
        # detect a schema-like dict by common keys
        if isinstance(expected_keys, dict) and expected_keys.get("$schema"):
            ok, _ = _validate_schema(obj, expected_keys)
            return ok
    except Exception:
        pass

    # Minimal structural check (legacy behaviour)
    if not isinstance(obj, dict):
        return False
    for k in expected_keys:
        if k not in obj:
            return False
    return True
# -------------------------------------------------------------------------


def _validate_schema(obj: Any, schema: Optional[Dict[str, Any]]):
    """
    Validate using jsonschema if available. If not available, perform simple
    required-key checks when schema is provided. Returns (ok: bool, msg: str).
    """
    if not schema:
        return True, ""
    if JSONSCHEMA_AVAILABLE:
        try:
            js_validate(instance=obj, schema=schema)
            return True, ""
        except JSValidationError as e:
            return False, f"jsonschema validation failed: {e.message}"
    # minimal check: ensure required keys exist
    try:
        required = schema.get("required", [])
        if isinstance(obj, dict):
            for k in required:
                if k not in obj:
                    return False, f"Missing required key: {k}"
    except Exception:
        return False, "Schema provided but validation unavailable and fallback check failed"
    return True, ""


def _simple_text_from_response(response) -> str:
    """
    Normalize different response objects from the Gemini client into plain text.
    """
    # genai response objects often provide '.text' or string coercion
    txt = ""
    try:
        txt = getattr(response, "text", None) or str(response)
    except Exception:
        txt = str(response)
    return txt


def generate_json(model, prompt_parts: List[str], expected_schema: dict = None, max_retries: int = 1) -> dict:
    """
    Calls the model and attempts to parse & validate its JSON response.
    Returns either the parsed dict or {"error": "...", "raw": "..."}.

    This function is pragmatic: it first attempts to json.loads the returned text.
    On failure it uses heuristics to extract an inner JSON blob and parse it.
    It does basic schema validation if expected_schema is provided (fail-closed).
    """
    last_raw = ""
    for attempt in range(max_retries + 1):
        try:
            # model.generate_content may raise; wrap to capture response
            response = model.generate_content(prompt_parts)
            raw_text = _simple_text_from_response(response)
            last_raw = raw_text

            # Try direct parse first
            parsed = json.loads(raw_text)

            # validate schema if requested
            ok, msg = _validate_schema(parsed, expected_schema)
            if not ok:
                return {"error": "Schema validation failed", "details": msg, "raw": raw_text}
            return parsed

        except json.JSONDecodeError:
            # try extraction heuristics
            try:
                extracted = _extract_json_text(last_raw or "")
                if extracted:
                    parsed = json.loads(extracted)
                    ok, msg = _validate_schema(parsed, expected_schema)
                    if not ok:
                        return {"error": "Schema validation failed after extraction", "details": msg, "raw": last_raw}
                    return parsed
            except Exception:
                pass

            # retry if attempts remain
            if attempt < max_retries:
                time.sleep(0.2)
                continue

            return {"error": "Failed to parse JSON response", "raw": last_raw}

        except Exception as e:
            # If the model call itself failed, retry up to max_retries
            last_txt = _simple_text_from_response(locals().get('response', ''))
            if attempt < max_retries:
                time.sleep(0.2)
                continue
            return {"error": f"Model generation failed: {e}", "raw": last_txt}

    return {"error": "Unknown failure", "raw": last_raw}


def generate_json_safe(model, prompt_parts: List[str], expected_schema: dict = None, max_retries: int = 2) -> dict:
    """
    Safer wrapper around generate_json with:
     - extra attempts
     - enforced schema validation (if expected_schema provided)
     - better error messages for callers that must fail-closed
    Returned value: parsed dict or {"error": "...", "raw": "...", "schema_err": "..."}.
    """
    # small defensive wrapper: ensure prompt_parts is list of strings
    parts = [str(p) for p in (prompt_parts or [])]

    # call generate_json (which already has heuristics)
    result = generate_json(model, parts, expected_schema=expected_schema, max_retries=max_retries)

    # If parse failed, try one last attempt with a slightly different prompt (ask model to output only JSON)
    if isinstance(result, dict) and result.get("error"):
        # attempt a constrained re-run with a minimal instruction to force JSON
        try:
            extra_prompt = parts + ["\nPLEASE RESPOND WITH ONLY A SINGLE JSON OBJECT OR ARRAY — NO EXTRA TEXT."]
            response = model.generate_content(extra_prompt)
            raw_text = _simple_text_from_response(response)
            extracted = _extract_json_text(raw_text) or raw_text
            parsed = json.loads(extracted)
            ok, msg = _validate_schema(parsed, expected_schema)
            if not ok:
                return {"error": "Schema validation failed (final attempt)", "details": msg, "raw": raw_text}
            return parsed
        except Exception as e:
            # return original error augmented
            return {"error": result.get("error", f"Final attempt failed: {e}"), "raw": result.get("raw", ""), "final_exception": str(e)}

    return result


# keep embedding helper (no change)
def get_embedding(text: str, task_type: str = "retrieval_document") -> List[float]:
    try:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type=task_type
        )
        # result might be a mapping; normalize access
        return result.get("embedding") if isinstance(result, dict) else result['embedding']
    except Exception as e:
        print(f"[Gemini] FAILED to generate embedding: {e}")
        # return None to indicate failure (caller should fallback)
        return None
