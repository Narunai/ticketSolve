# 🤖 TicketSolve Gemini Chatbot Microservice

An isolated, decoupled AI Chatbot Microservice powered by **Google Gemini API** for the **TicketSolve** system, running on Linux.

---

## 🏗️ Architecture Overview

The Chatbot Microservice operates on port `8001` independently from the main Django application. It communicates via REST APIs and reverse proxies through Nginx.

```text
[ User / Browser ] ─────── ( Embed widget.js ) ──────► [ TicketSolve Web App (Port 8000) ]
        │
        └─────── ( REST API / WebSockets ) ──────► [ Chatbot Microservice (Port 8001) ]
                                                        │
                                                        ├──► Admin Panel (/chatbot-admin/)
                                                        ├──► Isolated SQLite (chatbot.db)
                                                        ├──► Read-Only Security Sandbox Guard
                                                        └──► Google Gemini API Gateway (google-genai)
```

---

## 📁 File Structure (`chatbot_service/`)

```text
chatbot_service/
├── main.py                   # FastAPI application entrypoint & API routes (Port 8001)
├── database.py               # SQLite database manager (chatbot.db) & AES-256 Key Encryption
├── security_sandbox.py       # Read-Only file access sandbox & security whitelist guard
├── gemini_engine.py          # Google Gemini API connector with automatic model fallback
├── requirements.txt          # Dependencies (FastAPI, uvicorn, google-genai, cryptography)
├── ticket-chatbot.service    # Linux systemd service daemon configuration
├── templates/
│   └── admin_panel.html      # System Admin Control Panel template
└── static/
    ├── widget.js             # Embeddable Floating Chat Widget script
    └── widget.css            # Chat Widget stylesheet (Modern Dark UI)
```

---

## 🔌 API Endpoints

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/api/status` | GET | Public | Returns `{ "is_active": true/false }` for widget visibility check |
| `/api/chat` | POST | Public | Receives `{ "message": "query" }` and returns Gemini AI response |
| `/chatbot-admin/` | GET / HEAD | Admin | System Admin control panel to configure API Key, Models & Master Toggle |
| `/api/admin/config` | POST | Admin | Updates system configuration (Encrypted API Key, Model, On/Off status) |
| `/api/admin/knowledge/save` | POST | Admin | Adds or updates a system knowledge guide / manual entry |
| `/api/admin/knowledge/delete` | POST | Admin | Deletes a custom knowledge guide by ID |
| `/chatbot-static/` | GET | Public | Serves `widget.js` and `widget.css` static assets |

---

## 🔒 Security & Privacy (Read-Only Sandboxing)

1. **System Master Toggle**: System Admin can turn the chatbot `ON` or `OFF` at any time. When disabled, the chat widget is hidden dynamically across all user sessions.
2. **AES-256 Encrypted Key Storage**: Gemini API Key is stored using Fernet encryption (`cryptography` library) in `chatbot.db`.
3. **OS-Level Read-Only Restriction**: The AI is restricted to reading whitelisted public documentation files (`README.md`, `docs/`, `media/public_docs/`). It cannot access sensitive system files like `.env`, `db.sqlite3`, or execute shell commands.

---

## 🛠️ Linux Service Management (Daemon)

```bash
# Check service status
sudo systemctl status ticket-chatbot

# Restart chatbot service
sudo systemctl restart ticket-chatbot

# View live system logs
sudo journalctl -u ticket-chatbot.service -f --no-pager
```

---

## 🌐 Sidebar Integration

System Administrators (`SYSTEM_ADMIN`, `SYSTEM_SUB_ADMIN`, `is_superuser`) have an **AI Chatbot Admin** button added directly to their TicketSolve main sidebar under the `Administration` section for 1-click access to `https://tikketsolve-systemoneit.uk/chatbot-admin/`.
