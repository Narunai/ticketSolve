#!/bin/bash
# TicketSolve Auto-Deployment Helper Script for Ubuntu VPS
# Run this inside /var/www/ticketSolve folder on your remote server

set -e

echo "🚀 Starting TicketSolve auto-deployment setup..."

# 1. Update packages
sudo apt update
sudo apt install -y python3-pip python3-venv nginx postgresql postgresql-contrib curl git python3-certbot-nginx

# 2. Virtual Environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

echo "🔌 Activating virtual env & installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt gunicorn

# 3. Apply database migrations and collect static files
python manage.py migrate --noinput
echo "📂 Collecting static files..."
python manage.py collectstatic --noinput

# 4. Copy Service configurations
echo "⚙️ Setting up Gunicorn systemd service..."
sudo cp deployment/gunicorn.service /etc/systemd/system/gunicorn.service
sudo cp deployment/ticketsolve-scheduler.service /etc/systemd/system/ticketsolve-scheduler.service
sudo cp deployment/ticketsolve-scheduler.timer /etc/systemd/system/ticketsolve-scheduler.timer
sudo systemctl daemon-reload
sudo systemctl start gunicorn
sudo systemctl enable gunicorn
sudo systemctl enable --now ticketsolve-scheduler.timer

# 5. Copy Nginx configurations
echo "🕸️ Setting up Nginx virtual host..."
sudo cp deployment/nginx.conf /etc/nginx/sites-available/ticketsolve
if [ ! -f "/etc/nginx/sites-enabled/ticketsolve" ]; then
    sudo ln -s /etc/nginx/sites-available/ticketsolve /etc/nginx/sites-enabled/
fi

sudo nginx -t
sudo systemctl restart nginx

echo "✅ Deployment structure initialized successfully!"
echo "👉 Please do the following manual steps next:"
echo "1. Configure your .env file with production credentials"
echo "2. Run: python manage.py migrate"
echo "3. Run: sudo certbot --nginx"
