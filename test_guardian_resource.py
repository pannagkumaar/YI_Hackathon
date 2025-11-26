import os
import google.generativeai as genai
from dotenv import load_dotenv


load_dotenv()
if os.path.exists(".env.local"):
    load_dotenv(".env.local")
    
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

model = genai.GenerativeModel("gemini-2.5-flash")

resp = model.generate_content(
    "hello",
    generation_config={
        "max_output_tokens": 50
    }
)

print(resp.text)
