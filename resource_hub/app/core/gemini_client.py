# app/core/gemini_client.py
import os
import google.generativeai as genai

from app.core.config import settings

API_KEY = os.getenv("GOOGLE_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)

MODEL = "gemini-pro"  # adjust if needed

def ask_gemini(prompt: str, max_output_tokens: int = 256):
    """
    Calls Gemini generate_content and returns text string.
    Raises if API key not present or call fails.
    """
    if not API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set in environment")
    model = genai.get_model(MODEL)
    # using generate_text (or generate_content depending on SDK) -- using generate_text style:
    resp = model.generate(prompt=prompt, max_output_tokens=max_output_tokens)
    # The SDK returns a response object; .text or .candidates[0].content may contain the generated text
    # Here we try multiple fallbacks
    if hasattr(resp, "text") and resp.text:
        return resp.text
    if hasattr(resp, "candidates") and resp.candidates:
        return resp.candidates[0].content
    # fallback to str(resp)
    return str(resp)
