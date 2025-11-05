# 📄 gemini_client.py
import google.generativeai as genai
import os
import json
from typing import List
import dotenv

dotenv.load_dotenv()

# 1. Configure the API key from an environment variable
#    (Remember to set this in your terminal: export GOOGLE_API_KEY="your_api_key_here")
GOOGLE_API_KEY =  os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set.")

genai.configure(api_key=GOOGLE_API_KEY)

# 2. Setup standard generation config
generation_config = {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 4096,
    "response_mime_type": "application/json", # Request JSON output
}

# 3. Helper to create a model with system instructions
def get_model(system_instruction: str = None):
    """Initializes and returns a Gemini 1.5 Pro model."""
    return genai.GenerativeModel(
        model_name="models/gemini-flash-latest",
        generation_config=generation_config,
        system_instruction=system_instruction
    )

# 4. Helper function to call the model and parse the JSON response
def generate_json(model, prompt_parts: List[str]) -> dict:
    """Calls the model and attempts to parse its JSON response."""
    try:
        response = model.generate_content(prompt_parts)
        
        # The model is configured for JSON, so we can parse directly
        return json.loads(response.text)
        
    except json.JSONDecodeError as e:
        print(f"[Gemini] FAILED to decode JSON: {e}")
        print(f"[Gemini] Raw response: {response.text}")
        return {"error": "Failed to parse JSON response", "raw": response.text}
    except Exception as e:
        # Handle other potential errors (e.g., API errors, content safety blocks)
        print(f"[Gemini] FAILED to generate content: {e}")
        return {"error": f"Model generation failed: {e}"}