import database
from google import genai

config = database.get_config()
api_key = config.get('api_key', '')
client = genai.Client(api_key=api_key)

test_models = ["gemini-2.0-flash", "gemini-flash-latest", "gemini-2.0-flash-lite", "models/gemini-2.0-flash"]

for m in test_models:
    print(f"\n--- Testing model: '{m}' ---")
    try:
        res = client.models.generate_content(model=m, contents="Hi")
        print(f"SUCCESS with '{m}':", res.text)
    except Exception as e:
        print(f"ERROR with '{m}':", e)
