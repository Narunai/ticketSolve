try:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:
    genai = None  # type: ignore
    types = None  # type: ignore

import database
import security_sandbox

def generate_chat_response(user_query: str, history: list = None) -> dict:
    """
    Queries Google Gemini API with system prompt, safe document context, and automatic model fallback.
    """
    config = database.get_config()

    # 1. Check if Chatbot Service is active
    if not config["is_active"]:
        return {
            "status": "disabled",
            "response": "Chatbot service is temporarily disabled by System Administrator."
        }

    # 2. Check if API Key is configured
    api_key = config["api_key"]
    if not api_key:
        return {
            "status": "error",
            "response": "Gemini API Key has not been configured by System Administrator."
        }

    selected_model = config["model_name"] or "gemini-flash-latest"
    system_prompt = config["system_prompt"]

    # 3. Gather Safe Document Context (Read-only Public Docs)
    doc_context = security_sandbox.get_allowed_documents_content()

    full_system_instruction = f"""
{system_prompt}

[AI System Security & Permission Guidelines]:
- You are an AI Assistant with read-only permission to system documentation.
- Do not pretend to have access to confidential files, backend servers, or private user database records.
- Answer user queries politely, concisely, accurately, and strictly in English based on the public knowledge base below:

[Public Knowledge Base Context]:
{doc_context}
"""

    # Model candidates list for automatic fallback
    candidate_models = [selected_model]
    for fallback in ["gemini-flash-latest", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    client = genai.Client(api_key=api_key)
    last_error = ""

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_query,
                config=types.GenerateContentConfig(
                    system_instruction=full_system_instruction,
                    temperature=0.3,
                    max_output_tokens=1000
                )
            )

            reply_text = response.text if response and response.text else "Sorry, unable to generate response at this time."
            return {
                "status": "success",
                "response": reply_text
            }
        except Exception as e:
            last_error = str(e)
            # If rate limited (429) or model not found (404), try next fallback model
            if "429" in last_error or "404" in last_error or "RESOURCE_EXHAUSTED" in last_error or "NOT_FOUND" in last_error:
                continue
            else:
                break

    # If all models failed or encountered quota/key issues
    if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
        error_explanation = (
            "⚠️ Gemini API Key rate limit or quota exceeded.\n\n"
            "Resolution:\n"
            "1. Access Admin (/chatbot-admin/) and select 'Gemini Flash (Latest)'.\n"
            "2. Or generate a new free API Key from Google AI Studio (https://aistudio.google.com/)."
        )
    elif "404" in last_error or "NOT_FOUND" in last_error:
        error_explanation = (
            "⚠️ Model not found or API Key lacks permission for the specified model.\n\n"
            "Resolution: Access Admin (/chatbot-admin/) and select 'Gemini Flash (Latest)'."
        )
    else:
        error_explanation = f"Error connecting to Gemini API: {last_error}"

    return {
        "status": "error",
        "response": error_explanation
    }
