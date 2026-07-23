#!/bin/bash
# TicketSolve Continuous Automated Backup Script
# Schedule: Every 2 Hours
# Policy: Continuous recording without deletion limits
# Uploads directly to Personal Google Drive via Google Drive API v3

set -e

PROJECT_DIR="/var/www/ticketSolve"
BACKUP_ROOT="/var/backups/ticketsolve"
BACKUPS_DIR="${BACKUP_ROOT}/archives"
GDRIVE_FOLDER_ID="1q_86246EXE63IItYtI2tklqwr8EuuNrM"

NOW=$(date +"%Y-%m-%d_%H-%M-%S")

mkdir -p "$BACKUPS_DIR"

echo "[$(date)] 🚀 Starting TicketSolve 2-Hour Continuous Backup..."

# 1. Create 2-Hour Backup Archive
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
echo "✅ 2-Hour Backup Archive created: ${BACKUPS_DIR}/${ARCHIVE_NAME}"

# 2. Upload to Personal Google Drive via gcloud OAuth token & Drive API v3 (if gcloud available)
upload_file_to_gdrive() {
    local FILE_PATH="$1"
    local FILE_NAME=$(basename "$FILE_PATH")
    echo "☁️ Uploading $FILE_NAME to Personal Google Drive..."
    "${PROJECT_DIR}/venv/bin/python3" - "$FILE_PATH" "$GDRIVE_FOLDER_ID" << 'EOF'
import sys, urllib.request, json, os, subprocess, shutil

file_path = sys.argv[1]
file_name = os.path.basename(file_path)
folder_id = sys.argv[2]

try:
    if not shutil.which("gcloud"):
        print("ℹ️ gcloud CLI not detected on system. Local backup archive saved successfully.")
        sys.exit(0)

    # 1. Get Access Token from gcloud authenticated user
    access_token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()

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
    print("⚠️ Google Drive Upload Note:", str(e))
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
fi

echo "[$(date)] 🎉 2-Hour backup workflow finished successfully."
