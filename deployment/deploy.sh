#!/bin/bash
# TicketSolve deployment helper for the Ubuntu AWS VPS.

set -euo pipefail

PROJECT_DIR="/var/www/ticketSolve"
ENV_DIR="/etc/ticketsolve"
ENV_FILE="${ENV_DIR}/ticketsolve.env"
CHATBOT_ENV_DIR="/etc/ticketsolve-chatbot"
CHATBOT_KEY_FILE="${CHATBOT_ENV_DIR}/fernet.key"
BACKUP_DIR="/var/backups/ticketsolve"
BACKUP_QUARANTINE_DIR="${BACKUP_DIR}/.quarantine"
RESTORE_DIR="/var/lib/ticketsolve-restore"
RESTORE_LOG_DIR="/var/log/ticketsolve/restore"
RESTORE_TRIGGER_FILE="${RESTORE_DIR}/restore.trigger"
RESTORE_SENTINEL_FILE="/run/ticketsolve/restore-in-progress"

# Prevent background workers from loading new model code before migrations finish.
sudo systemctl stop ticketsolve-email-to-ticket.timer 2>/dev/null || true
sudo systemctl stop ticketsolve-scheduler.timer 2>/dev/null || true
sudo systemctl stop ticketsolve-email-to-ticket.service 2>/dev/null || true
sudo systemctl stop ticketsolve-scheduler.service 2>/dev/null || true

sudo apt update
sudo apt install -y python3-pip python3-venv nginx curl git python3-certbot-nginx postgresql-client

cd "$PROJECT_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Keep production secrets outside the Git checkout.
sudo install -d -m 750 -o root -g www-data "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    if [ -f ".env" ]; then
        sudo install -m 640 -o root -g www-data .env "$ENV_FILE"
    else
        sudo touch "$ENV_FILE"
        sudo chown root:www-data "$ENV_FILE"
        sudo chmod 640 "$ENV_FILE"
    fi
fi

# Keep a root-only recovery copy before changing any production secret. This
# protects encrypted database fields from an accidental key replacement.
ENV_BACKUP_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -m 600 -o root -g root \
    "$ENV_FILE" "${ENV_FILE}.predeploy.${ENV_BACKUP_TIMESTAMP}"

EXISTING_FIELD_KEYS="$(sudo sed -n 's/^FIELD_ENCRYPTION_KEYS=//p' "$ENV_FILE" | head -n 1)"
if [ -z "$EXISTING_FIELD_KEYS" ]; then
    echo "Refusing deployment: FIELD_ENCRYPTION_KEYS is missing from the production environment."
    echo "Restore the approved key from the secret store or ${ENV_FILE}.predeploy.${ENV_BACKUP_TIMESTAMP}."
    echo "The deploy helper never generates a replacement because that could make encrypted SMTP/IMAP data unrecoverable."
    exit 1
fi

EXISTING_SECRET="$(sudo sed -n 's/^SECRET_KEY=//p' "$ENV_FILE" | head -n 1)"
if [ "${#EXISTING_SECRET}" -lt 50 ] || [[ "$EXISTING_SECRET" == django-insecure-* ]]; then
    GENERATED_SECRET="$(venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))')"
    if sudo grep -q '^SECRET_KEY=' "$ENV_FILE"; then
        sudo sed -i "s|^SECRET_KEY=.*$|SECRET_KEY=${GENERATED_SECRET}|" "$ENV_FILE"
    else
        echo "SECRET_KEY=${GENERATED_SECRET}" | sudo tee -a "$ENV_FILE" >/dev/null
    fi
    echo "Generated a strong production SECRET_KEY."
fi
if ! sudo grep -qE '^BACKUP_MANIFEST_SIGNING_KEY=.{32,}$' "$ENV_FILE"; then
    BACKUP_SIGNING_KEY="$(venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))')"
    if sudo grep -q '^BACKUP_MANIFEST_SIGNING_KEY=' "$ENV_FILE"; then
        sudo sed -i "s|^BACKUP_MANIFEST_SIGNING_KEY=.*$|BACKUP_MANIFEST_SIGNING_KEY=${BACKUP_SIGNING_KEY}|" "$ENV_FILE"
    else
        echo "BACKUP_MANIFEST_SIGNING_KEY=${BACKUP_SIGNING_KEY}" | sudo tee -a "$ENV_FILE" >/dev/null
    fi
    echo "Generated a persistent Full Backup manifest signing key."
fi
if ! sudo grep -qE '^ALLOWED_HOSTS=.+$' "$ENV_FILE"; then
    echo "ALLOWED_HOSTS=tikketsolve-systemoneit.uk,www.tikketsolve-systemoneit.uk" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^CSRF_TRUSTED_ORIGINS=' "$ENV_FILE"; then
    echo "CSRF_TRUSTED_ORIGINS=https://tikketsolve-systemoneit.uk,https://www.tikketsolve-systemoneit.uk" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^PUBLIC_BASE_URL=' "$ENV_FILE"; then
    echo "PUBLIC_BASE_URL=https://tikketsolve-systemoneit.uk" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^BACKUP_DIR=' "$ENV_FILE"; then
    echo "BACKUP_DIR=${BACKUP_DIR}" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^BACKUP_RETENTION_DAYS=' "$ENV_FILE"; then
    echo "BACKUP_RETENTION_DAYS=30" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^BACKUP_QUARANTINE_DIR=' "$ENV_FILE"; then
    echo "BACKUP_QUARANTINE_DIR=${BACKUP_QUARANTINE_DIR}" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^BACKUP_IMPORT_MAX_BYTES=' "$ENV_FILE"; then
    echo "BACKUP_IMPORT_MAX_BYTES=536870912" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^RESTORE_TRIGGER_FILE=' "$ENV_FILE"; then
    echo "RESTORE_TRIGGER_FILE=${RESTORE_TRIGGER_FILE}" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^RESTORE_SENTINEL_FILE=' "$ENV_FILE"; then
    echo "RESTORE_SENTINEL_FILE=${RESTORE_SENTINEL_FILE}" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^RESTORE_LOG_DIR=' "$ENV_FILE"; then
    echo "RESTORE_LOG_DIR=${RESTORE_LOG_DIR}" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^CHATBOT_DB_PATH=' "$ENV_FILE"; then
    echo "CHATBOT_DB_PATH=/var/lib/ticketsolve-chatbot/chatbot.db" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^SECURE_HSTS_PRELOAD=' "$ENV_FILE"; then
    echo "SECURE_HSTS_PRELOAD=True" | sudo tee -a "$ENV_FILE" >/dev/null
fi
sudo chmod 640 "$ENV_FILE"
sudo chown root:www-data "$ENV_FILE"
sudo install -d -m 750 -o ubuntu -g www-data "$BACKUP_DIR"
sudo install -d -m 750 -o ubuntu -g www-data "$BACKUP_QUARANTINE_DIR"
sudo install -d -m 750 -o ubuntu -g www-data "$RESTORE_DIR"
sudo install -d -m 750 -o root -g adm "$RESTORE_LOG_DIR"
sudo install -d -m 755 -o root -g root "$(dirname "$RESTORE_SENTINEL_FILE")"

run_manage() {
    local unit_suffix="$1"
    shift
    sudo systemd-run --wait --pipe --collect \
        --unit="ticketsolve-deploy-${unit_suffix}" \
        -p Type=oneshot \
        -p User=ubuntu \
        -p Group=www-data \
        -p WorkingDirectory="${PROJECT_DIR}" \
        -p EnvironmentFile="${ENV_FILE}" \
        "${PROJECT_DIR}/venv/bin/python" manage.py "$@"
}

run_manage migrate migrate --noinput
run_manage static collectstatic --noinput

pip install -r chatbot_service/requirements.txt

# Keep chatbot runtime data and encryption material outside the Git checkout.
# Preserve the original encrypted configuration when upgrading an older install.
sudo systemctl stop ticket-chatbot.service 2>/dev/null || true
if ! id -u ticketsolve-chatbot >/dev/null 2>&1; then
    sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin ticketsolve-chatbot
fi
if ! getent group ticketsolve-backup >/dev/null 2>&1; then
    sudo groupadd --system ticketsolve-backup
fi
sudo usermod -a -G ticketsolve-backup ubuntu
# Older releases used chatbot group membership for backup access, which also
# exposed the Fernet key to the Django/Gunicorn user. Remove that broad grant.
if id -nG ubuntu | tr ' ' '\n' | grep -qx 'ticketsolve-chatbot'; then
    sudo gpasswd --delete ubuntu ticketsolve-chatbot
fi
# setgid preserves the backup-only group when SQLite creates sidecar files.
sudo install -d -m 2750 -o ticketsolve-chatbot -g ticketsolve-backup /var/lib/ticketsolve-chatbot
sudo install -d -m 750 -o root -g ticketsolve-chatbot "$CHATBOT_ENV_DIR"
if [ ! -f /var/lib/ticketsolve-chatbot/chatbot.db ] && [ -f chatbot_service/chatbot.db ]; then
    sudo install -m 600 -o ticketsolve-chatbot -g ticketsolve-chatbot \
        chatbot_service/chatbot.db /var/lib/ticketsolve-chatbot/chatbot.db
fi
if [ ! -f "$CHATBOT_KEY_FILE" ]; then
    if [ -f /etc/ticketsolve/chatbot-fernet.key ]; then
        # Upgrade older secure deployments without rotating the encryption key.
        sudo install -m 640 -o root -g ticketsolve-chatbot \
            /etc/ticketsolve/chatbot-fernet.key "$CHATBOT_KEY_FILE"
    elif [ -f chatbot_service/.secret_key ]; then
        sudo install -m 640 -o root -g ticketsolve-chatbot \
            chatbot_service/.secret_key "$CHATBOT_KEY_FILE"
    else
        CHATBOT_KEY_TMP="$(mktemp)"
        venv/bin/python -c \
            'import pathlib, sys; from cryptography.fernet import Fernet; pathlib.Path(sys.argv[1]).write_bytes(Fernet.generate_key())' \
            "$CHATBOT_KEY_TMP"
        sudo install -m 640 -o root -g ticketsolve-chatbot \
            "$CHATBOT_KEY_TMP" "$CHATBOT_KEY_FILE"
        rm -f "$CHATBOT_KEY_TMP"
    fi
fi
sudo chown root:ticketsolve-chatbot "$CHATBOT_KEY_FILE"
sudo chmod 640 "$CHATBOT_KEY_FILE"
sudo chown ticketsolve-chatbot:ticketsolve-backup /var/lib/ticketsolve-chatbot/chatbot.db 2>/dev/null || true
sudo chmod 640 /var/lib/ticketsolve-chatbot/chatbot.db 2>/dev/null || true

sudo cp deployment/gunicorn.service /etc/systemd/system/gunicorn.service
sudo cp deployment/ticketsolve-scheduler.service /etc/systemd/system/ticketsolve-scheduler.service
sudo cp deployment/ticketsolve-scheduler.timer /etc/systemd/system/ticketsolve-scheduler.timer
sudo cp deployment/ticketsolve-email-to-ticket.service /etc/systemd/system/ticketsolve-email-to-ticket.service
sudo cp deployment/ticketsolve-email-to-ticket.timer /etc/systemd/system/ticketsolve-email-to-ticket.timer
sudo cp deployment/ticketsolve-restore.service /etc/systemd/system/ticketsolve-restore.service
sudo cp deployment/ticketsolve-restore.path /etc/systemd/system/ticketsolve-restore.path
sudo install -m 750 -o root -g root deployment/ticketsolve-restore-worker.sh /usr/local/sbin/ticketsolve-restore-worker
sudo install -m 644 -o root -g root deployment/maintenance-hard.html "$PROJECT_DIR/staticfiles/maintenance-hard.html"
sudo cp chatbot_service/ticket-chatbot.service /etc/systemd/system/ticket-chatbot.service
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl enable gunicorn
sudo systemctl enable --now ticketsolve-scheduler.timer
sudo systemctl enable --now ticketsolve-email-to-ticket.timer
sudo systemctl enable --now ticketsolve-restore.path
sudo systemctl enable --now ticket-chatbot
sudo systemctl restart ticket-chatbot

sudo cp deployment/nginx.conf /etc/nginx/sites-available/ticketsolve
if [ ! -L "/etc/nginx/sites-enabled/ticketsolve" ]; then
    sudo ln -s /etc/nginx/sites-available/ticketsolve /etc/nginx/sites-enabled/ticketsolve
fi

if ! sudo nginx -V 2>&1 | grep -q -- '--with-http_auth_request_module'; then
    echo "Refusing deployment: Nginx auth_request module is required for chatbot authorization."
    exit 1
fi
sudo nginx -t
sudo systemctl restart nginx

echo "Deployment completed."
echo "Review ${ENV_FILE} and configure SMTP credentials if required."
