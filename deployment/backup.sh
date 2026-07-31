#!/bin/bash
# Manual/cron entry point for a local incremental backup on the AWS VPS.

set -euo pipefail
umask 027

PROJECT_DIR="/var/www/ticketSolve"
ENV_FILE="/etc/ticketsolve/ticketsolve.env"

cd "$PROJECT_DIR"
set -a
source "$ENV_FILE"
set +a

exec venv/bin/python manage.py run_2hr_backup "$@"
