---
name: ticketsolve-dev
description: >-
  TicketSolve project development skill. Provides architecture knowledge,
  deployment workflows, coding conventions, and database schema for the
  Django + FastAPI multi-tenant IT support ticket management system
  deployed on AWS Lightsail Ubuntu VPS at tikketsolve-systemoneit.uk.
---

# TicketSolve Development Skill

## Overview

TicketSolve is a multi-tenant IT support ticket management system built with:
- **Django 5.2** (main app) — ticket CRUD, user/company management, email notifications, reports
- **FastAPI** (chatbot microservice) — Gemini AI chatbot with admin panel

Production URL: `https://tikketsolve-systemoneit.uk`

## Quick Start

### Project Structure (Key Files)

```
ticketSolve/
├── ticket_system/          # Django project config
│   ├── settings.py         # Django settings (env-based config)
│   ├── urls.py             # Root URL router
│   └── wsgi.py             # Gunicorn entry point
├── tickets/                # Main Django app
│   ├── models.py           # 30+ models (Company, User, Ticket, etc.)
│   ├── views.py            # ~200KB, all CBV views
│   ├── urls.py             # 108 URL routes
│   ├── signals.py          # Email/notification triggers
│   ├── context_processors.py # English i18n translations (t.*)
│   ├── security.py         # EncryptedCharField, throttling
│   ├── permissions.py      # Role-based access control
│   ├── templates/tickets/  # 26 Django templates
│   └── static/             # CSS/JS assets
├── chatbot_service/        # FastAPI microservice (port 8001)
│   ├── main.py             # FastAPI app + routes
│   ├── gemini_engine.py    # Gemini API integration
│   ├── database.py         # SQLite config/knowledge store
│   ├── security_sandbox.py # Input sanitization
│   ├── templates/          # Jinja2 templates (admin_panel.html)
│   └── static/             # widget.js (floating chat widget)
├── deployment/             # Server config files
│   ├── deploy.sh           # Full deployment script
│   ├── nginx.conf          # Nginx reverse proxy config
│   ├── gunicorn.service    # Django systemd service
│   └── *.service/*.timer   # Background worker services
├── db.sqlite3              # Django database
├── requirements.txt        # Python dependencies
└── LightsailDefaultKey-ap-southeast-1.pem  # SSH key
```

### Deploy Pattern (Quick Reference)

```bash
# Upload changed files
scp -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    <local-file> ubuntu@3.1.52.201:/var/www/ticketSolve/<remote-path>

# Restart services
ssh -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    ubuntu@3.1.52.201 \
    "sudo systemctl restart gunicorn && sudo systemctl restart ticket-chatbot"
```

> **Important**: SCP can only send multiple files to the SAME remote directory.
> For files going to DIFFERENT directories, use separate SCP commands.

### Template Coding Rule (CRITICAL)

**NEVER** put Django `{% %}` / `{{ }}` or Jinja2 template tags inside `<script>` blocks.  
Instead, pass values through `data-*` attributes on HTML elements and read them in pure JS.

For full details, read: `references/coding-patterns.md`

## References

When working on this project, consult these reference documents as needed:

| Document | When to Read |
|----------|-------------|
| `references/architecture.md` | Understanding system components, services, and how they connect |
| `references/deployment.md` | Deploying changes to the VPS, service management |
| `references/coding-patterns.md` | Writing templates, handling forms, i18n, permissions |
| `references/database-schema.md` | Understanding models, relationships, field choices |
| `references/risk-analysis.md` | Security risk factors, controls, and mitigation roadmap |

## Common Mistakes

1. **Putting Django template tags in `<script>`** — causes IDE errors and confuses JS parsers. Always use `data-*` attributes.
2. **Using a single SCP for files in different remote directories** — SCP fails silently. Use separate commands per target directory.
3. **Forgetting to restart both services** — Django changes need `gunicorn` restart; chatbot changes need `ticket-chatbot` restart.
4. **Hardcoding URLs in JavaScript** — Always use `data-*` attributes populated by `{% url 'name' %}` in the HTML, then read via `element.dataset.*` in JS.
5. **Mixing Thai and English** — The system UI is English-only. All user-facing strings go through `context_processors.language_processor` as `t.*` variables.
