#!/bin/bash
# TicketSolve deployment helper for the Ubuntu AWS VPS.

set -euo pipefail

PROJECT_DIR="/var/www/ticketSolve"
ENV_DIR="/etc/ticketsolve"
ENV_FILE="${ENV_DIR}/ticketsolve.env"
BACKUP_DIR="/var/backups/ticketsolve"

# Prevent background workers from loading new model code before migrations finish.
sudo systemctl stop ticketsolve-email-to-ticket.timer 2>/dev/null || true
sudo systemctl stop ticketsolve-scheduler.timer 2>/dev/null || true
sudo systemctl stop ticketsolve-email-to-ticket.service 2>/dev/null || true
sudo systemctl stop ticketsolve-scheduler.service 2>/dev/null || true

sudo apt update
sudo apt install -y python3-pip python3-venv nginx curl git python3-certbot-nginx

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
if ! sudo grep -qE '^FIELD_ENCRYPTION_KEYS=.+$' "$ENV_FILE"; then
    GENERATED_FIELD_KEY="$(venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    echo "FIELD_ENCRYPTION_KEYS=${GENERATED_FIELD_KEY}" | sudo tee -a "$ENV_FILE" >/dev/null
    echo "Generated an independent field-encryption key. Back it up in the approved secret store."
fi
if ! sudo grep -qE '^ALLOWED_HOSTS=.+$' "$ENV_FILE"; then
    echo "ALLOWED_HOSTS=tikketsolve-systemoneit.uk,www.tikketsolve-systemoneit.uk" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^CSRF_TRUSTED_ORIGINS=' "$ENV_FILE"; then
    echo "CSRF_TRUSTED_ORIGINS=https://tikketsolve-systemoneit.uk,https://www.tikketsolve-systemoneit.uk" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^BACKUP_DIR=' "$ENV_FILE"; then
    echo "BACKUP_DIR=${BACKUP_DIR}" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^BACKUP_RETENTION_DAYS=' "$ENV_FILE"; then
    echo "BACKUP_RETENTION_DAYS=30" | sudo tee -a "$ENV_FILE" >/dev/null
fi
if ! sudo grep -q '^SECURE_HSTS_PRELOAD=' "$ENV_FILE"; then
    echo "SECURE_HSTS_PRELOAD=True" | sudo tee -a "$ENV_FILE" >/dev/null
fi
sudo chmod 640 "$ENV_FILE"
sudo chown root:www-data "$ENV_FILE"
sudo install -d -m 750 -o ubuntu -g www-data "$BACKUP_DIR"

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

sudo cp deployment/gunicorn.service /etc/systemd/system/gunicorn.service
sudo cp deployment/ticketsolve-scheduler.service /etc/systemd/system/ticketsolve-scheduler.service
sudo cp deployment/ticketsolve-scheduler.timer /etc/systemd/system/ticketsolve-scheduler.timer
sudo cp deployment/ticketsolve-email-to-ticket.service /etc/systemd/system/ticketsolve-email-to-ticket.service
sudo cp deployment/ticketsolve-email-to-ticket.timer /etc/systemd/system/ticketsolve-email-to-ticket.timer
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl enable gunicorn
sudo systemctl enable --now ticketsolve-scheduler.timer
sudo systemctl enable --now ticketsolve-email-to-ticket.timer

sudo cp deployment/nginx.conf /etc/nginx/sites-available/ticketsolve
if [ ! -L "/etc/nginx/sites-enabled/ticketsolve" ]; then
    sudo ln -s /etc/nginx/sites-available/ticketsolve /etc/nginx/sites-enabled/ticketsolve
fi

sudo nginx -t
sudo systemctl restart nginx

echo "Deployment completed."
echo "Review ${ENV_FILE} and configure SMTP credentials if required."
