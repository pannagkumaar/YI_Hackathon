import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
if os.path.exists(".env.local"):
    load_dotenv(".env.local")


genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

print("Listing Models...\n")

for m in genai.list_models():
    print(
        m.name,
        "| modalities:", getattr(m, "input_token_limit", "N/A"),
        "| output modalities:", getattr(m, "output_token_limit", "N/A"),
        "| supported methods:", m.supported_generation_methods
    )
