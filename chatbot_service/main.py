import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

import database
import gemini_engine


logger = logging.getLogger("ticketsolve.chatbot")
BASE_DIR = Path(__file__).resolve().parent
ADMIN_ROLES = {"SYSTEM_ADMIN", "SYSTEM_SUB_ADMIN", "SUPERUSER"}
ALLOWED_MODELS = {
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
}


def _environment_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


ALLOWED_ORIGINS = _environment_list(
    "CHATBOT_ALLOWED_ORIGINS",
    "https://tikketsolve-systemoneit.uk,https://www.tikketsolve-systemoneit.uk",
)
ALLOWED_HOSTS = _environment_list(
    "CHATBOT_ALLOWED_HOSTS",
    "tikketsolve-systemoneit.uk,www.tikketsolve-systemoneit.uk,127.0.0.1,localhost,testserver",
)
CHAT_REQUESTS_PER_MINUTE = max(
    1, min(120, int(os.environ.get("CHATBOT_USER_RATE_PER_MINUTE", "20")))
)
_chat_request_times: dict[str, deque[float]] = defaultdict(deque)
_chat_rate_lock = Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    yield


app = FastAPI(
    title="TicketSolve Isolated Chatbot Microservice",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; connect-src 'self'",
    )
    if request.url.path.startswith(("/admin", "/api/admin")):
        response.headers["Cache-Control"] = "no-store, private"
    return response


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictRequest):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default_session", min_length=1, max_length=128)


class ConfigRequest(StrictRequest):
    is_active: bool
    api_key: str | None = Field(default=None, max_length=256)
    model_name: str | None = Field(default=None, max_length=80)
    system_prompt: str | None = Field(default=None, max_length=8000)


class KnowledgeRequest(StrictRequest):
    id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=30000)
    is_active: bool = True


class DeleteKnowledgeRequest(StrictRequest):
    id: int = Field(gt=0)


def require_proxy_user(request: Request) -> dict[str, str]:
    """Trust only identity headers overwritten by the local Nginx auth_request."""
    user_id = request.headers.get("x-ticketsolve-authenticated-user", "").strip()
    role = request.headers.get("x-ticketsolve-authenticated-role", "").strip()
    if not user_id or not role:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"user_id": user_id, "role": role}


def require_admin(identity: dict[str, str] = Depends(require_proxy_user)) -> dict[str, str]:
    if identity["role"] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="System administrator permission required")
    return identity


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        referer = request.headers.get("referer", "")
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Trusted same-origin request required")


def require_admin_mutation(
    request: Request,
    identity: dict[str, str] = Depends(require_admin),
) -> dict[str, str]:
    require_same_origin(request)
    return identity


def enforce_chat_rate_limit(identity: dict[str, str]) -> None:
    now = time.monotonic()
    cutoff = now - 60
    with _chat_rate_lock:
        timestamps = _chat_request_times[identity["user_id"]]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= CHAT_REQUESTS_PER_MINUTE:
            retry_after = max(1, int(60 - (now - timestamps[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Chat request limit reached. Please wait before trying again.",
                headers={"Retry-After": str(retry_after)},
            )
        timestamps.append(now)


@app.get("/")
def read_root():
    return {"service": "TicketSolve Gemini Chatbot Microservice", "status": "running"}


@app.get("/api/status")
def get_chatbot_status(_identity: dict[str, str] = Depends(require_proxy_user)):
    config = database.get_admin_config()
    return {"is_active": config["is_active"]}


@app.post("/api/chat")
def handle_chat(payload: ChatRequest, identity: dict[str, str] = Depends(require_proxy_user)):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty query")
    enforce_chat_rate_limit(identity)
    return gemini_engine.generate_chat_response(message)


@app.api_route("/admin", methods=["GET", "HEAD"])
@app.api_route("/admin/", methods=["GET", "HEAD"])
def admin_page(request: Request, _identity: dict[str, str] = Depends(require_admin)):
    config = database.get_admin_config()
    knowledge_entries = database.get_custom_knowledge_entries()
    return templates.TemplateResponse(
        request=request,
        name="admin_panel.html",
        context={"config": config, "knowledge_entries": knowledge_entries},
    )


@app.post("/api/admin/config")
def update_admin_config(
    payload: ConfigRequest,
    identity: dict[str, str] = Depends(require_admin_mutation),
):
    model_name = payload.model_name.strip() if payload.model_name else None
    if model_name is not None and model_name not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported Gemini model")

    api_key = payload.api_key.strip() if payload.api_key else None
    system_prompt = payload.system_prompt.strip() if payload.system_prompt is not None else None
    if system_prompt is not None and not system_prompt:
        raise HTTPException(status_code=400, detail="System prompt cannot be empty")

    database.update_config(
        is_active=payload.is_active,
        api_key=api_key,
        model_name=model_name,
        system_prompt=system_prompt,
    )
    database.record_admin_audit(
        identity["user_id"],
        "CONFIG_UPDATED",
        details=(
            f"active={payload.is_active}; model={model_name or 'unchanged'}; "
            f"api_key_replaced={bool(api_key)}; prompt_replaced={system_prompt is not None}"
        ),
    )
    return {"status": "success", "message": "Configuration updated successfully"}


@app.post("/api/admin/knowledge/save")
def save_knowledge_entry(
    payload: KnowledgeRequest,
    identity: dict[str, str] = Depends(require_admin_mutation),
):
    title = payload.title.strip()
    content = payload.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="Title and content cannot be empty")
    if payload.id:
        if not database.update_custom_knowledge_entry(
            payload.id, title, content, payload.is_active
        ):
            raise HTTPException(status_code=404, detail="Knowledge guide not found")
        entry_id = payload.id
        message = "Knowledge guide updated successfully"
    else:
        entry_id = database.add_custom_knowledge_entry(title, content)
        message = "New knowledge guide added successfully"
    database.record_admin_audit(
        identity["user_id"],
        "KNOWLEDGE_UPDATED" if payload.id else "KNOWLEDGE_CREATED",
        target_id=str(entry_id),
        details=f"active={payload.is_active}; content_length={len(content)}",
    )
    return {"status": "success", "message": message}


@app.post("/api/admin/knowledge/delete")
def delete_knowledge_entry(
    payload: DeleteKnowledgeRequest,
    identity: dict[str, str] = Depends(require_admin_mutation),
):
    if not database.delete_custom_knowledge_entry(payload.id):
        raise HTTPException(status_code=404, detail="Knowledge guide not found")
    database.record_admin_audit(
        identity["user_id"], "KNOWLEDGE_DELETED", target_id=str(payload.id)
    )
    return {"status": "success", "message": "Knowledge guide deleted successfully"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001)
