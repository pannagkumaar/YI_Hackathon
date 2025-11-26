import os
import google.generativeai as genai
from dotenv import load_dotenv
from google.generativeai.types import GenerationConfig

# Load env
load_dotenv()
if os.path.exists(".env.local"):
    load_dotenv(".env.local")

API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise RuntimeError("GOOGLE_API_KEY missing")

# Configure Gemini
genai.configure(api_key=API_KEY)

# WORKING MODEL
MODEL_NAME = "gemini-2.5-flash"


def ask_gemini(prompt: str, max_output_tokens: int = 1024) -> str:
    """
    Stable Gemini wrapper for AI Studio keys.
    """
    print("USING MODEL:", MODEL_NAME)
    print("🔥 [Gemini Debug] PROMPT SENT:\n")
    print(prompt)
    print("---------------")

    try:
        model = genai.GenerativeModel(MODEL_NAME)

        response = model.generate_content(
            contents=prompt,
            generation_config=GenerationConfig(
                max_output_tokens=max_output_tokens,
                temperature=0.3,
                top_p=0.95,
            )
        )

        print("🔥 [Gemini Debug] RAW RESPONSE:", response)
        print("---------------")

        if hasattr(response, "text") and response.text:
            return response.text.strip()

        # Safeguard fallback (rare with new SDK)
        for cand in getattr(response, "candidates", []) or []:
            parts = getattr(cand.content, "parts", None)
            if not parts:
                continue
            texts = [p.text for p in parts if hasattr(p, "text")]
            if texts:
                return "\n".join(texts).strip()

        print("⚠️ No usable text returned.")
        return ""

    except Exception as e:
        print("❌ [Gemini Debug] Exception:", e)
        return ""
