# tests/test_gemini_client.py
import json
import pytest
from gemini_client import _extract_json_text, _validate_decision_schema, generate_json

class DummyModel:
    def __init__(self, text): self._text = text
    def generate_content(self, prompt_parts):
        # emulate the gemini response object with .text
        class R: pass
        r = R()
        r.text = self._text
        return r

def test_extract_json_text_mixed():
    raw = "Some commentary\n{\"decision\":\"Allow\",\"reason\":\"ok\"}\nExtra text"
    assert _extract_json_text(raw) is not None
    assert json.loads(_extract_json_text(raw))["decision"] == "Allow"

def test_generate_json_parses_json(monkeypatch):
    model = DummyModel('{"decision":"Allow","reason":"safe"}')
    # monkeypatch get_model not necessary; call generate_json with model directly
    schema = {"required": ["decision", "reason"]}
    # generate_json expects a model with generate_content; pass model
    res = generate_json(model, ["input"], expected_schema=schema, max_retries=0)
    assert isinstance(res, dict)
    assert res.get("decision") == "Allow"

def test_generate_json_handles_bad_json(monkeypatch):
    model = DummyModel('I will answer:\n{"decision":"Allow", "reason": "ok"}\nNote: done')
    schema = {"required":["decision","reason"]}
    res = generate_json(model, ["x"], expected_schema=schema, max_retries=0)
    # success because heuristics extract JSON
    assert res.get("decision") == "Allow"
