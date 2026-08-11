import sqlite3

import pytest
from fastapi.testclient import TestClient

import database
import gemini_engine
import main
import security_sandbox


USER_HEADERS = {
    "X-TicketSolve-Authenticated-User": "101",
    "X-TicketSolve-Authenticated-Role": "CLIENT_USER",
}
ADMIN_HEADERS = {
    "X-TicketSolve-Authenticated-User": "1",
    "X-TicketSolve-Authenticated-Role": "SYSTEM_ADMIN",
}
TRUSTED_ORIGIN = "https://tikketsolve-systemoneit.uk"


@pytest.fixture()
def chatbot_client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "chatbot.db")
    monkeypatch.setattr(database, "SECRET_KEY_PATH", tmp_path / "chatbot-fernet.key")
    main._chat_request_times.clear()
    with TestClient(main.app) as client:
        yield client
    main._chat_request_times.clear()


def test_runtime_database_has_no_default_admin_account(chatbot_client):
    with sqlite3.connect(database.DB_PATH) as connection:
        legacy_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='admin_users'"
        ).fetchone()
    assert legacy_table is None


def test_chatbot_api_requires_django_proxy_identity(chatbot_client, monkeypatch):
    called = False

    def fake_generate(_message):
        nonlocal called
        called = True
        return {"status": "success", "response": "ok"}

    monkeypatch.setattr(gemini_engine, "generate_chat_response", fake_generate)
    assert chatbot_client.get("/api/status").status_code == 401
    assert chatbot_client.post("/api/chat", json={"message": "hello"}).status_code == 401
    assert called is False


def test_authenticated_user_can_read_status_and_chat(chatbot_client, monkeypatch):
    monkeypatch.setattr(
        gemini_engine,
        "generate_chat_response",
        lambda message: {"status": "success", "response": f"answer:{message}"},
    )
    status = chatbot_client.get("/api/status", headers=USER_HEADERS)
    chat = chatbot_client.post(
        "/api/chat", headers=USER_HEADERS, json={"message": " help "}
    )
    assert status.status_code == 200
    assert chat.status_code == 200
    assert chat.json()["response"] == "answer:help"


def test_chat_payload_is_bounded(chatbot_client):
    response = chatbot_client.post(
        "/api/chat",
        headers=USER_HEADERS,
        json={"message": "x" * 2001},
    )
    assert response.status_code == 422


def test_chat_rate_limit_is_enforced_per_authenticated_user(
    chatbot_client, monkeypatch
):
    monkeypatch.setattr(main, "CHAT_REQUESTS_PER_MINUTE", 2)
    monkeypatch.setattr(
        gemini_engine,
        "generate_chat_response",
        lambda _message: {"status": "success", "response": "ok"},
    )
    assert chatbot_client.post(
        "/api/chat", headers=USER_HEADERS, json={"message": "one"}
    ).status_code == 200
    assert chatbot_client.post(
        "/api/chat", headers=USER_HEADERS, json={"message": "two"}
    ).status_code == 200
    blocked = chatbot_client.post(
        "/api/chat", headers=USER_HEADERS, json={"message": "three"}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_admin_page_requires_system_role_and_never_returns_api_key(chatbot_client):
    database.update_config(is_active=True, api_key="AIzaSy-secret-value")
    forbidden = chatbot_client.get("/admin/", headers=USER_HEADERS)
    allowed = chatbot_client.get("/admin/", headers=ADMIN_HEADERS)
    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert "AIzaSy-secret-value" not in allowed.text
    assert "API key configured" in allowed.text


def test_admin_mutation_requires_trusted_origin_and_preserves_blank_key(chatbot_client):
    database.update_config(is_active=True, api_key="existing-key")
    payload = {
        "is_active": False,
        "api_key": "",
        "model_name": "gemini-3.6-flash",
        "system_prompt": "Answer support questions safely.",
    }
    blocked = chatbot_client.post(
        "/api/admin/config", headers=ADMIN_HEADERS, json=payload
    )
    allowed = chatbot_client.post(
        "/api/admin/config",
        headers={**ADMIN_HEADERS, "Origin": TRUSTED_ORIGIN},
        json=payload,
    )
    assert blocked.status_code == 403
    assert allowed.status_code == 200
    config = database.get_config()
    assert config["api_key"] == "existing-key"
    assert config["model_name"] == "gemini-3.6-flash"
    assert config["is_active"] is False
    with sqlite3.connect(database.DB_PATH) as connection:
        audit_details = connection.execute(
            "SELECT actor_id, action, details FROM admin_audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit_details[0] == ADMIN_HEADERS["X-TicketSolve-Authenticated-User"]
    assert audit_details[1] == "CONFIG_UPDATED"
    assert "existing-key" not in audit_details[2]


def test_admin_rejects_decommissioned_model(chatbot_client):
    response = chatbot_client.post(
        "/api/admin/config",
        headers={**ADMIN_HEADERS, "Origin": TRUSTED_ORIGIN},
        json={
            "is_active": True,
            "model_name": "gemini-2.0-flash",
            "system_prompt": "Safe support assistant.",
        },
    )
    assert response.status_code == 400


def test_startup_migrates_retired_model_without_changing_api_key(chatbot_client):
    database.update_config(
        is_active=True,
        api_key="existing-encrypted-key",
        model_name="gemini-2.0-flash",
    )

    database.init_db()

    config = database.get_config()
    assert config["model_name"] == database.DEFAULT_MODEL
    assert config["api_key"] == "existing-encrypted-key"
    with sqlite3.connect(database.DB_PATH) as connection:
        audit = connection.execute(
            "SELECT action, details FROM admin_audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit[0] == "MODEL_AUTO_MIGRATED"
    assert database.DEFAULT_MODEL in audit[1]


def test_document_sandbox_excludes_repository_and_secrets():
    repository_root = security_sandbox.SERVICE_DIR.parent
    assert security_sandbox.is_path_safe(
        str(security_sandbox.SERVICE_DIR / "knowledge" / "system_guide.md")
    )
    assert not security_sandbox.is_path_safe(str(repository_root / "README.md"))
    assert not security_sandbox.is_path_safe(str(repository_root / ".env"))
    assert not security_sandbox.is_path_safe("/etc/passwd")
