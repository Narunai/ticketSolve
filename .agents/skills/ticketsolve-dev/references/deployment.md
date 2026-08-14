# TicketSolve Deployment Reference

## Server Connection

```
Host:     3.1.52.201 (AWS Lightsail, ap-southeast-1)
User:     ubuntu
SSH Key:  LightsailDefaultKey-ap-southeast-1.pem (project root)
Domain:   tikketsolve-systemoneit.uk
```

## Quick Deploy (Most Common)

For deploying individual changed files:

### Step 1: Upload files via SCP

```bash
# Django template files
scp -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    tickets/templates/tickets/<filename>.html \
    ubuntu@3.1.52.201:/var/www/ticketSolve/tickets/templates/tickets/<filename>.html

# Django Python files (views, models, signals, etc.)
scp -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    tickets/<filename>.py \
    ubuntu@3.1.52.201:/var/www/ticketSolve/tickets/<filename>.py

# Chatbot service files
scp -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    chatbot_service/<filename> \
    ubuntu@3.1.52.201:/var/www/ticketSolve/chatbot_service/<filename>

# Django settings / project config
scp -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    ticket_system/settings.py \
    ubuntu@3.1.52.201:/var/www/ticketSolve/ticket_system/settings.py
```

> **CRITICAL**: SCP cannot send files to different remote directories in a single command.  
> Always use separate `scp` commands for files in different target directories.

### Step 2: Restart services

```bash
# Restart Django (always needed after Python/template changes)
ssh -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    ubuntu@3.1.52.201 "sudo systemctl restart gunicorn"

# Restart chatbot (only needed after chatbot_service/ changes)
ssh -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    ubuntu@3.1.52.201 "sudo systemctl restart ticket-chatbot"

# Restart both (combined)
ssh -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    ubuntu@3.1.52.201 \
    "sudo systemctl restart gunicorn && sudo systemctl restart ticket-chatbot && echo 'All services restarted OK'"
```

## Service Restart Guide

| Changed File | Services to Restart |
|---|---|
| `tickets/*.py` | `gunicorn` |
| `tickets/templates/**` | `gunicorn` |
| `ticket_system/*.py` | `gunicorn` |
| `chatbot_service/*.py` | `ticket-chatbot` |
| `chatbot_service/templates/*` | `ticket-chatbot` |
| `chatbot_service/static/*` | `ticket-chatbot` |
| `deployment/nginx.conf` | `nginx` (via `sudo nginx -t && sudo systemctl reload nginx`) |
| Restore worker/unit or migration changes | Run full `deployment/deploy.sh`; never SCP/restart only |

## Full Deployment (Model/Migration Changes)

Use full deployment for any chatbot authorization, Nginx, service unit, database
path or encryption-key change. The deploy script migrates legacy chatbot data to
`/var/lib/ticketsolve-chatbot`, preserves the legacy Fernet key under `/etc`,
installs the dedicated service account and validates Nginx `auth_request` support.
Do not replace either encryption key during deployment.

When `models.py` changes require new migrations:

```bash
# 1. Upload all changed files
scp -r -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no \
    tickets/ ubuntu@3.1.52.201:/var/www/ticketSolve/tickets/

# 2. SSH into server and run migrations
ssh -i LightsailDefaultKey-ap-southeast-1.pem -o StrictHostKeyChecking=no ubuntu@3.1.52.201

# On server:
cd /var/www/ticketSolve
source venv/bin/activate
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart gunicorn
```

## Static Files

After changing CSS/JS in `tickets/static/`:

```bash
ssh -i LightsailDefaultKey-ap-southeast-1.pem ubuntu@3.1.52.201 \
    "cd /var/www/ticketSolve && source venv/bin/activate && python manage.py collectstatic --noinput"
```

## Checking Service Status

```bash
ssh -i LightsailDefaultKey-ap-southeast-1.pem ubuntu@3.1.52.201 \
    "sudo systemctl status gunicorn ticket-chatbot --no-pager"
```

## Viewing Logs

```bash
# Django (gunicorn) logs
ssh -i LightsailDefaultKey-ap-southeast-1.pem ubuntu@3.1.52.201 \
    "sudo journalctl -u gunicorn --no-pager -n 50"

# Chatbot service logs
ssh -i LightsailDefaultKey-ap-southeast-1.pem ubuntu@3.1.52.201 \
    "sudo journalctl -u ticket-chatbot --no-pager -n 50"

# Nginx access/error logs
ssh -i LightsailDefaultKey-ap-southeast-1.pem ubuntu@3.1.52.201 \
    "sudo tail -30 /var/log/nginx/error.log"
```

## Environment Variables (Production)

Located at `/etc/ticketsolve/ticketsolve.env` on the server:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Must be `False` in production |
| `ALLOWED_HOSTS` | `tikketsolve-systemoneit.uk,www.tikketsolve-systemoneit.uk` |
| `CSRF_TRUSTED_ORIGINS` | `https://tikketsolve-systemoneit.uk,...` |
| `FIELD_ENCRYPTION_KEYS` | Fernet key(s) for SMTP password encryption |
| `BACKUP_MANIFEST_SIGNING_KEY` | Persistent HMAC key for Full Backup v2 manifests |
| `BACKUP_DIR` | `/var/backups/ticketsolve` |
| `BACKUP_QUARANTINE_DIR` | Quarantine for chunked imports |
| `BACKUP_IMPORT_MAX_BYTES` | Maximum imported archive size |
| `RESTORE_TRIGGER_FILE` | Root worker trigger path |
| `RESTORE_SENTINEL_FILE` | Hard-maintenance sentinel path |
| `RESTORE_LOG_DIR` | External JSONL restore logs |

## Restore Deployment Safety

The deploy script installs and enables `ticketsolve-restore.path`, the root-owned oneshot service, worker wrapper and Nginx hard-maintenance fallback. Production verification may validate units and create a Full Backup, but must not trigger a restore. Restore drills belong in an isolated copy with the same database engine and approved encryption key.

If the worker retains `/run/ticketsolve/restore-in-progress`, do not remove it until an operator has reviewed the service journal and per-job JSONL log and has confirmed either the target restore or rollback is healthy.

## CWD for All Commands

All `scp` and `ssh` commands should be run from the project root:
```
d:\Project_personal\ticketSolve
```
