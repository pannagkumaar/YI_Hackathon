import os
import google.generativeai as genai
from app.core.config import settings
from dotenv import load_dotenv


# Load .env and .env.local (if present)
load_dotenv()
if os.path.exists(".env.local"):
    load_dotenv(".env.local")

API_KEY = os.getenv("GOOGLE_API_KEY") or getattr(settings, "GOOGLE_API_KEY", None)
if not API_KEY:
    raise RuntimeError("GOOGLE_API_KEY not found in environment or settings.")
genai.configure(api_key=API_KEY)

MODEL_NAME = "models/gemini-2.5-pro"  # or "models/gemini-2.5-flash"

def ask_gemini(prompt: str, max_output_tokens: int = 512) -> str:
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={
                "max_output_tokens": max_output_tokens,
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 40,
            },
        )

        if getattr(response, "text", None):
            return response.text.strip()
        for c in getattr(response, "candidates", []):
            if hasattr(c, "content") and c.content.parts:
                parts = [p.text for p in c.content.parts if hasattr(p, "text")]
                if parts:
                    return " ".join(parts).strip()

        print(f"[Gemini] Empty result -> finish_reason: {getattr(response.candidates[0], 'finish_reason', None) if response.candidates else 'unknown'}")
        return "I don't have enough information."
    except Exception as e:
        print(f"[Gemini] Error: {e}")
        return "Gemini generation failed."
