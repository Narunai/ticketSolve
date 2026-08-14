# TicketSolve Architecture Reference

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     AWS Lightsail Ubuntu VPS                     │
│                        IP: 3.1.52.201                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Nginx (Port 443/80)                      │ │
│  │          tikketsolve-systemoneit.uk (SSL via Certbot)       │ │
│  └──────┬────────────────────────────┬─────────────────────────┘ │
│         │                            │                           │
│         │ /* → Unix Socket           │ /chatbot-admin, /api/*    │
│         │                            │ → Django auth_request     │
│         │                            │ → localhost:8001          │
│         ▼                            ▼                           │
│  ┌──────────────────┐    ┌──────────────────────┐               │
│  │   Gunicorn (4w)  │    │   Uvicorn (FastAPI)  │               │
│  │ ticket_system    │    │   chatbot_service    │               │
│  │   .wsgi          │    │   main:app           │               │
│  │ Port: Unix sock  │    │   Port: 8001         │               │
│  └───────┬──────────┘    └──────────┬───────────┘               │
│          │                          │                            │
│          ▼                          ▼                            │
│  ┌──────────────┐        ┌──────────────────┐                   │
│  │ PostgreSQL   │        │   chatbot.db     │                   │
│  │ (production) │        │ /var/lib/...     │                   │
│  └──────────────┘        └──────────────────┘                   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Background Workers (systemd)                   │ │
│  │  • ticketsolve-scheduler.timer   (ticket automation)        │ │
│  │  • ticketsolve-email-to-ticket   (inbound email → ticket)   │ │
│  │  • ticketsolve-restore.path       (root-owned restore gate)  │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Django Main App (`tickets/`)

| File | Size | Purpose |
|------|------|---------|
| `models.py` | 61KB, 1746 lines | 30+ models — Company hierarchy, Users, Tickets, Email, SMTP, Backups |
| `views.py` | 201KB | All class-based views — CRUD, reports, backups, settings |
| `urls.py` | 8KB, 108 routes | URL routing for all features |
| `signals.py` | 19KB | Post-save email notifications, in-app notifications |
| `context_processors.py` | 9KB | English translation dictionary (`t.*` variables) |
| `security.py` | 10KB | `EncryptedCharField` (Fernet), brute-force throttling |
| `permissions.py` | 3KB | `PermissionRequiredMixin` derivatives for role checks |
| `admin.py` | 10KB | Django admin customizations |
| `backup_service.py` | 21KB | PostgreSQL/SQLite + chatbot DB backup and scheduling |
| `backup_restore_service.py` | Validation, quarantine import, signed manifest and restore primitives |
| `email_to_ticket.py` | 26KB | IMAP polling → auto-create tickets from inbound emails |
| `email_formatting.py` | 1.4KB | HTML email template builder |

### 2. FastAPI Chatbot (`chatbot_service/`)

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, routes: `/api/chat`, `/admin`, `/api/admin/*` |
| `gemini_engine.py` | Google Gemini API integration (configurable model) |
| `database.py` | Isolated SQLite config, custom knowledge and admin audit log |
| `security_sandbox.py` | Curated-document allowlist and path containment |
| `templates/admin_panel.html` | Jinja2 admin UI for chatbot config + knowledge base |
| `static/widget.js` | Floating chat widget injected into Django `base.html` |

### 3. Nginx Routing

| URL Pattern | Backend |
|-------------|---------|
| `/*` (default) | Gunicorn (Django) via Unix socket |
| `/login/` | Gunicorn with rate limiting (10 req/min) |
| `/static/` | Direct file serve from `/var/www/ticketSolve/staticfiles/` |
| `/media/` | Returns 404 (downloads go through Django auth views) |
| `/chatbot-admin` | Django System Admin auth subrequest → FastAPI `:8001/admin` |
| `/chatbot-static/` | FastAPI `:8001/static/` |
| `/api/status`, `/api/chat` | Django authenticated-session subrequest → FastAPI; rate limited |
| `/api/admin/` | Django System Admin/Sub Admin subrequest → FastAPI; same-origin POST |

### 4. Systemd Services

| Service | Description |
|---------|-------------|
| `gunicorn.service` | Django via Gunicorn (4 workers, sandboxed) |
| `ticket-chatbot.service` | FastAPI chatbot on port 8001 |
| `ticketsolve-scheduler.timer` | Periodic ticket automation (OPEN → IN_PROGRESS) |
| `ticketsolve-email-to-ticket.timer` | IMAP polling for inbound emails |
| `ticketsolve-restore.path` | Watches the exclusive restore trigger |
| `ticketsolve-restore.service` | Root-owned oneshot worker; stops writers, restores, verifies and rolls back on failure |

### 5. Security Architecture

- **Environment secrets**: Stored in `/etc/ticketsolve/ticketsolve.env` (not in repo)
- **Encryption**: SMTP passwords encrypted with Fernet (`FIELD_ENCRYPTION_KEYS`)
- **Login protection**: IP-based brute-force throttle (`AuthenticationThrottle` model)
- **CSRF**: Enabled globally; AJAX forms include `{% csrf_token %}`
- **Gunicorn hardening**: `PrivateTmp`, `NoNewPrivileges`, `ProtectSystem=full`
- **Media downloads**: Served through Django views (auth-gated), not nginx
- **Chatbot authorization**: Nginx `auth_request` reuses Django session/RBAC and overwrites trusted identity headers
- **Chatbot secrets**: DB is `/var/lib/ticketsolve-chatbot`; Fernet key is `/etc/ticketsolve-chatbot/fernet.key`; the decrypted API key is never returned to the browser. `ticketsolve-backup` can read only the DB, not the key.
- **Chatbot service sandbox**: dedicated system user, read-only project, capability drop, memory/task limits
- **Maintenance gate**: hashed access code, 5-attempt/10-minute throttle, expiring versioned session; normal authentication and RBAC still required
- **Backup restore**: only signed compatible Full Backup v2; quarantine import, protected pre-restore rollback, hard sentinel and post-restore admin review

### 6. Template System

Django templates extend `base.html` which provides:
- Sidebar navigation (role-aware menu items)
- Top navbar with user info + notifications
- Theme system (dark mode, accent colors)
- Gemini chatbot widget (only for authenticated users: `{% if user.is_authenticated %}`)

The chatbot widget (`/chatbot-static/widget.js`) is loaded conditionally in `base.html`.

### 7. Key Directories on VPS

```
/var/www/ticketSolve/         # Project root
/var/www/ticketSolve/venv/    # Python virtual environment
/var/www/ticketSolve/staticfiles/  # collectstatic output
/var/www/ticketSolve/media/   # User uploads (attachments)
/etc/ticketsolve/ticketsolve.env   # Production environment secrets
/etc/ticketsolve-chatbot/fernet.key # Chatbot API-key encryption key
/var/lib/ticketsolve-chatbot/chatbot.db # Chatbot runtime data
/var/backups/ticketsolve/     # Database backups
/var/backups/ticketsolve/.quarantine/ # In-progress imported archives
/var/lib/ticketsolve-restore/ # Exclusive restore trigger
/var/log/ticketsolve/restore/ # External JSONL restore audit
/run/ticketsolve/restore-in-progress # Hard-maintenance sentinel
```
