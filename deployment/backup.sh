#!/bin/bash
# TicketSolve Continuous Automated Backup Script
# Schedule: Every 2 Hours
# Policy: Cloud backup to Personal Google Drive via Service Account or OAuth2, local temporary files automatically purged

set -e

PROJECT_DIR="/var/www/ticketSolve"
BACKUP_ROOT="/var/backups/ticketsolve"
BACKUPS_DIR="${BACKUP_ROOT}/archives"
GDRIVE_FOLDER_ID="1q_86246EXE63IItYtI2tklqwr8EuuNrM"

NOW=$(date +"%Y-%m-%d_%H-%M-%S")

mkdir -p "$BACKUPS_DIR"

echo "[$(date)] 🚀 Starting TicketSolve 2-Hour Continuous Backup..."

# 1. Create 2-Hour Temporary Backup Archive
ARCHIVE_NAME="backup_${NOW}.tar.gz"
TEMP_ARCHIVE="/tmp/${ARCHIVE_NAME}"

cd "$PROJECT_DIR"

# Include db.sqlite3, media folder, and .env if present
FILES_TO_BACKUP=""
if [ -f "db.sqlite3" ]; then FILES_TO_BACKUP="$FILES_TO_BACKUP db.sqlite3"; fi
if [ -d "media" ]; then FILES_TO_BACKUP="$FILES_TO_BACKUP media"; fi
if [ -f ".env" ]; then FILES_TO_BACKUP="$FILES_TO_BACKUP .env"; fi

if [ -z "$FILES_TO_BACKUP" ]; then
    echo "⚠️ No files found to backup in $PROJECT_DIR"
    exit 1
fi

tar -czf "$TEMP_ARCHIVE" $FILES_TO_BACKUP
mv "$TEMP_ARCHIVE" "${BACKUPS_DIR}/${ARCHIVE_NAME}"
echo "✅ Temporary Backup Archive created: ${BACKUPS_DIR}/${ARCHIVE_NAME}"

# 2. Upload to Personal Google Drive via Service Account or OAuth2 Refresh Token
upload_file_to_gdrive() {
    local FILE_PATH="$1"
    local FILE_NAME=$(basename "$FILE_PATH")
    echo "☁️ Uploading $FILE_NAME to Personal Google Drive..."
    "${PROJECT_DIR}/venv/bin/python3" - "$FILE_PATH" "$GDRIVE_FOLDER_ID" << 'EOF'
import sys, urllib.request, urllib.parse, json, os, subprocess, shutil

file_path = sys.argv[1]
file_name = os.path.basename(file_path)
folder_id = sys.argv[2]

# Read settings from .env
env_vars = {}
if os.path.exists(".env"):
    with open(".env", "r") as env_f:
        for line in env_f:
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip('"').strip("'")

access_token = None

# Method A: Google Cloud Service Account JSON Key File
sa_key_paths = [
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", env_vars.get("GOOGLE_APPLICATION_CREDENTIALS", "")),
    "/var/www/ticketSolve/service_account.json",
    "/var/www/ticketSolve/gdrive_key.json",
    "/var/www/ticketSolve/credentials.json"
]

sa_key_file = next((p for p in sa_key_paths if p and os.path.exists(p)), None)

if sa_key_file:
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
        SCOPES = ['https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_file(sa_key_file, scopes=SCOPES)
        creds.refresh(google.auth.transport.requests.Request())
        access_token = creds.token
        print("🔑 Authenticated using Service Account:", creds.service_account_email)
    except Exception as e:
        print("⚠️ Service Account Auth Error:", str(e))

# Method B: OAuth2 Refresh Token
if not access_token:
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN", env_vars.get("GDRIVE_REFRESH_TOKEN", ""))
    client_id = os.environ.get("GDRIVE_CLIENT_ID", env_vars.get("GDRIVE_CLIENT_ID", ""))
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET", env_vars.get("GDRIVE_CLIENT_SECRET", ""))

    if refresh_token and client_id and client_secret:
        try:
            token_url = "https://oauth2.googleapis.com/token"
            token_data = urllib.parse.urlencode({
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }).encode("utf-8")

            req = urllib.request.Request(token_url, data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req) as resp:
                token_res = json.loads(resp.read().decode("utf-8"))
                access_token = token_res.get("access_token")
        except Exception as e:
            print("⚠️ OAuth Refresh Token Error:", str(e))

# Method C: gcloud CLI fallback
if not access_token and shutil.which("gcloud"):
    try:
        access_token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
    except Exception:
        pass

if not access_token:
    print("ℹ️ Google Drive cloud sync skipped (No valid Service Account key or OAuth token configured).")
    sys.exit(0)

try:
    # 2. Initiate Resumable Upload
    metadata = json.dumps({"name": file_name, "parents": [folder_id]}).encode("utf-8")
    init_req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
        data=metadata,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/gzip",
        },
        method="POST"
    )

    with urllib.request.urlopen(init_req) as init_resp:
        upload_url = init_resp.headers.get("Location")

    # 3. Upload File Binary Stream
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        file_data = f.read()

    upload_req = urllib.request.Request(
        upload_url,
        data=file_data,
        headers={
            "Content-Type": "application/gzip",
            "Content-Length": str(file_size),
        },
        method="PUT"
    )

    with urllib.request.urlopen(upload_req) as upload_resp:
        result = json.loads(upload_resp.read().decode("utf-8"))
        print("🎉 Successfully uploaded to Personal Google Drive! File ID:", result.get("id"))
except Exception as e:
    print("⚠️ Google Drive Upload Error:", str(e))
EOF
}

if [ -f "${BACKUPS_DIR}/${ARCHIVE_NAME}" ]; then
    upload_file_to_gdrive "${BACKUPS_DIR}/${ARCHIVE_NAME}"
    FILE_SIZE=$(stat -c%s "${BACKUPS_DIR}/${ARCHIVE_NAME}" 2>/dev/null || stat -f%z "${BACKUPS_DIR}/${ARCHIVE_NAME}" 2>/dev/null || echo "0")
    "${PROJECT_DIR}/venv/bin/python3" manage.py shell -c "
from tickets.models import BackupLog
BackupLog.objects.create(
    filename='${ARCHIVE_NAME}',
    file_size_bytes=${FILE_SIZE},
    status='SUCCESS',
    details='Backup Archive created successfully (${FILE_SIZE} bytes)'
)
"
    # Auto-purge local archive from VM disk to avoid taking up local storage space
    rm -f "${BACKUPS_DIR}/${ARCHIVE_NAME}"
    echo "🧹 Purged temporary backup archive from local VM disk to conserve storage."
fi

echo "[$(date)] 🎉 Backup workflow finished successfully."
