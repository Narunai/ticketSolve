#!/bin/bash

set -euo pipefail

PROJECT_DIR="/var/www/ticketSolve"
TRIGGER_FILE="${RESTORE_TRIGGER_FILE:-/var/lib/ticketsolve-restore/restore.trigger}"
SENTINEL_FILE="${RESTORE_SENTINEL_FILE:-/run/ticketsolve/restore-in-progress}"
BACKUP_DIR_VALUE="${BACKUP_DIR:-/var/backups/ticketsolve}"
CHATBOT_DB_VALUE="${CHATBOT_DB_PATH:-/var/lib/ticketsolve-chatbot/chatbot.db}"

if [ ! -f "$TRIGGER_FILE" ]; then
    exit 0
fi

IFS= read -r JOB_ID < "$TRIGGER_FILE"
if [[ ! "$JOB_ID" =~ ^[0-9a-fA-F-]{36}$ ]]; then
    echo "Refusing invalid restore job identifier."
    exit 1
fi

install -d -m 755 -o root -g root "$(dirname "$SENTINEL_FILE")"
touch "$SENTINEL_FILE"
rm -f -- "$TRIGGER_FILE"

systemctl stop ticketsolve-email-to-ticket.timer 2>/dev/null || true
systemctl stop ticketsolve-scheduler.timer 2>/dev/null || true
systemctl stop ticketsolve-email-to-ticket.service 2>/dev/null || true
systemctl stop ticketsolve-scheduler.service 2>/dev/null || true
systemctl stop gunicorn.service 2>/dev/null || true
systemctl stop ticket-chatbot.service 2>/dev/null || true

set +e
cd "$PROJECT_DIR"
"$PROJECT_DIR/venv/bin/python" manage.py process_restore_job "$JOB_ID"
RESTORE_STATUS=$?
set -e

chown -R ubuntu:www-data "$BACKUP_DIR_VALUE" 2>/dev/null || true
chown -R ubuntu:www-data "$PROJECT_DIR/media" 2>/dev/null || true
if [ -f "$CHATBOT_DB_VALUE" ]; then
    chown ticketsolve-chatbot:ticketsolve-backup "$CHATBOT_DB_VALUE" 2>/dev/null || true
    chmod 640 "$CHATBOT_DB_VALUE" 2>/dev/null || true
fi

if [ "$RESTORE_STATUS" -ne 0 ]; then
    echo "Restore failed. Hard-maintenance sentinel retained for operator review."
    exit "$RESTORE_STATUS"
fi

systemctl start gunicorn.service
systemctl start ticket-chatbot.service
systemctl start ticketsolve-scheduler.timer
systemctl start ticketsolve-email-to-ticket.timer

if ! systemctl is-active --quiet gunicorn.service; then
    echo "Gunicorn did not recover. Hard-maintenance sentinel retained."
    exit 1
fi

rm -f -- "$SENTINEL_FILE"
echo "Restore completed. Application Maintenance Mode remains enabled for review."
