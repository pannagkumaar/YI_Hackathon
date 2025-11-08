# 📄 list_models.py
import google.generativeai as genai
import os
import dotenv

dotenv.load_dotenv()

# 1. Configure the API key from an environment variable
#    (Remember to set this in your terminal: export GOOGLE_API_KEY="your_api_key_here")

print("--- Listing Available Gemini Models ---")

try:
    # 1. Configure the API key from an environment variable
    GOOGLE_API_KEY =  os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")

    genai.configure(api_key=GOOGLE_API_KEY)

    # 2. Call the list_models function and print the results
    print("\nFound the following models:")
    
    for m in genai.list_models():
        # We only care about models that support the 'generateContent' method
        if 'generateContent' in m.supported_generation_methods:
            print(f"  * {m.name}")

    print("\n--- End of List ---")
    print("\nACTION: Copy one of the model names above (e.g., 'gemini-1.0-pro')")
    print("and paste it into the 'model_name' variable in gemini_client.py")

except Exception as e:
    print(f"\n--- ERROR ---")
    print(f"Failed to list models: {e}")
    print("Please ensure your GOOGLE_API_KEY is correct and has access.")