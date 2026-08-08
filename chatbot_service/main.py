import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path

import database
import gemini_engine

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TicketSolve Isolated Chatbot Microservice")

# Allow CORS for main application integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# On Startup: Initialize SQLite DB
@app.on_event("startup")
def on_startup():
    database.init_db()

# --- Pydantic Data Models ---
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"

class ConfigRequest(BaseModel):
    is_active: bool
    api_key: str = None
    model_name: str = None
    system_prompt: str = None

class KnowledgeRequest(BaseModel):
    id: int = None
    title: str
    content: str
    is_active: bool = True

class DeleteKnowledgeRequest(BaseModel):
    id: int

# --- User & Public Endpoints ---

@app.get("/")
def read_root():
    return {"service": "TicketSolve Gemini Chatbot Microservice", "status": "running"}

@app.get("/api/status")
def get_chatbot_status():
    config = database.get_config()
    return {"is_active": config["is_active"]}

@app.post("/api/chat")
def handle_chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Empty query")

    # Generate Response from Gemini Engine
    result = gemini_engine.generate_chat_response(payload.message)
    return result

# --- Admin Endpoints ---

@app.api_route("/admin", methods=["GET", "HEAD"])
@app.api_route("/admin/", methods=["GET", "HEAD"])
def admin_page(request: Request):
    config = database.get_config()
    knowledge_entries = database.get_custom_knowledge_entries()
    config_display = {
        "is_active": config["is_active"],
        "api_key": config["api_key"],
        "model_name": config["model_name"],
        "system_prompt": config["system_prompt"]
    }
    return templates.TemplateResponse(request=request, name="admin_panel.html", context={
        "config": config_display,
        "knowledge_entries": knowledge_entries
    })

@app.post("/api/admin/config")
def update_admin_config(payload: ConfigRequest):
    database.update_config(
        is_active=payload.is_active,
        api_key=payload.api_key if payload.api_key and not payload.api_key.startswith("AIzaSy...") else payload.api_key,
        model_name=payload.model_name,
        system_prompt=payload.system_prompt
    )
    return {"status": "success", "message": "Configuration updated successfully"}

@app.post("/api/admin/knowledge/save")
def save_knowledge_entry(payload: KnowledgeRequest):
    if not payload.title.strip() or not payload.content.strip():
        raise HTTPException(status_code=400, detail="Title and content cannot be empty")
    if payload.id:
        database.update_custom_knowledge_entry(payload.id, payload.title, payload.content, payload.is_active)
        msg = "Knowledge guide updated successfully"
    else:
        database.add_custom_knowledge_entry(payload.title, payload.content)
        msg = "New knowledge guide added successfully"
    return {"status": "success", "message": msg}

@app.post("/api/admin/knowledge/delete")
def delete_knowledge_entry(payload: DeleteKnowledgeRequest):
    database.delete_custom_knowledge_entry(payload.id)
    return {"status": "success", "message": "Knowledge guide deleted successfully"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
