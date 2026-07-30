import os
import json
import tarfile
import zipfile
import shutil
import urllib.request
import urllib.parse
import subprocess
from datetime import timedelta
from django.utils import timezone
from django.conf import settings

from .models import BackupLog, Ticket, TicketComment, TicketAttachment, CommentAttachment

GDRIVE_FOLDER_ID = "1q_86246EXE63IItYtI2tklqwr8EuuNrM"
BACKUP_DIR = os.path.join(settings.BASE_DIR, "backups")


def get_backup_file_path(filename):
    """Returns absolute filepath in BACKUP_DIR if it exists, else None."""
    path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(path):
        return path
    return None


def upload_to_gdrive(file_path, folder_id=GDRIVE_FOLDER_ID):
    """
    Uploads a file to Google Drive using Service Account key or OAuth2 Refresh Token.
    Returns (success: bool, message: str)
    """
    file_name = os.path.basename(file_path)
    env_vars = {}
    env_path = os.path.join(settings.BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as env_f:
            for line in env_f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")

    access_token = None

    # Method 1: Google Cloud Service Account JSON Key File
    sa_key_paths = [
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", env_vars.get("GOOGLE_APPLICATION_CREDENTIALS", "")),
        os.path.join(settings.BASE_DIR, "service_account.json"),
        os.path.join(settings.BASE_DIR, "gdrive_key.json"),
        os.path.join(settings.BASE_DIR, "credentials.json"),
    ]

    sa_key_file = next((p for p in sa_key_paths if p and os.path.exists(p)), None)

    if sa_key_file:
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests
            scopes = ['https://www.googleapis.com/auth/drive']
            creds = service_account.Credentials.from_service_account_file(sa_key_file, scopes=scopes)
            creds.refresh(google.auth.transport.requests.Request())
            access_token = creds.token
        except Exception as e:
            print(f"Service Account Auth Warning: {e}")

    # Method 2: OAuth2 Refresh Token
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
                print(f"OAuth Refresh Token Warning: {e}")

    # Method 3: gcloud CLI fallback
    if not access_token and shutil.which("gcloud"):
        try:
            access_token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
        except Exception:
            pass

    if not access_token:
        return False, "Google Drive credentials not configured. Local backup saved."

    try:
        metadata = json.dumps({"name": file_name, "parents": [folder_id]}).encode("utf-8")
        init_req = urllib.request.Request(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            data=metadata,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "application/gzip" if file_name.endswith(".gz") else "application/zip",
            },
            method="POST"
        )

        with urllib.request.urlopen(init_req) as init_resp:
            upload_url = init_resp.headers.get("Location")

        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            file_data = f.read()

        upload_req = urllib.request.Request(
            upload_url,
            data=file_data,
            headers={
                "Content-Type": "application/gzip" if file_name.endswith(".gz") else "application/zip",
                "Content-Length": str(file_size),
            },
            method="PUT"
        )

        with urllib.request.urlopen(upload_req) as upload_resp:
            result = json.loads(upload_resp.read().decode("utf-8"))
            file_id = result.get("id")
            return True, f"Uploaded to Google Drive (ID: {file_id})"
    except Exception as e:
        return False, f"Google Drive Upload Error: {e}"


def perform_full_backup():
    """
    Creates a full backup of db.sqlite3, media, and .env.
    Saves to BACKUP_DIR for local download and uploads to Google Drive if configured.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now_str = timezone.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"full_backup_{now_str}.tar.gz"
    backup_filepath = os.path.join(BACKUP_DIR, archive_name)

    try:
        with tarfile.open(backup_filepath, "w:gz") as tar:
            db_path = os.path.join(settings.BASE_DIR, "db.sqlite3")
            if os.path.exists(db_path):
                tar.add(db_path, arcname="db.sqlite3")

            media_path = os.path.join(settings.BASE_DIR, "media")
            if os.path.exists(media_path):
                tar.add(media_path, arcname="media")

            env_path = os.path.join(settings.BASE_DIR, ".env")
            if os.path.exists(env_path):
                tar.add(env_path, arcname=".env")

        file_size = os.path.getsize(backup_filepath)
        uploaded, cloud_msg = upload_to_gdrive(backup_filepath)

        details = f"Full Backup ({file_size} bytes). {cloud_msg}"
        log = BackupLog.objects.create(
            filename=archive_name,
            file_size_bytes=file_size,
            backup_type=BackupLog.TYPE_FULL,
            status=BackupLog.STATUS_SUCCESS,
            details=details
        )
        return {"success": True, "log": log, "details": details, "file_path": backup_filepath}
    except Exception as e:
        if os.path.exists(backup_filepath):
            os.remove(backup_filepath)
        log = BackupLog.objects.create(
            filename=archive_name,
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_FULL,
            status=BackupLog.STATUS_FAILED,
            details=f"Backup Failed: {str(e)}"
        )
        return {"success": False, "log": log, "error": str(e)}


def perform_incremental_backup(hours=2):
    """
    Exports tickets created in the last `hours` hours + their comments & attachments.
    Saves to BACKUP_DIR for local download and uploads to Google Drive if configured.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now = timezone.now()
    since = now - timedelta(hours=hours)
    now_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"incremental_backup_{now_str}.zip"

    tickets = Ticket.objects.filter(created_at__gte=since).select_related('company', 'created_by', 'assigned_to', 'ticket_category', 'module_category')

    if not tickets.exists():
        log = BackupLog.objects.create(
            filename=archive_name,
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
            details=f"No new tickets created in the last {hours} hours."
        )
        return {"success": True, "log": log, "count": 0, "message": f"No new tickets created in the last {hours} hours."}

    zip_path = os.path.join(BACKUP_DIR, archive_name)

    try:
        tickets_data = []
        attachments_to_pack = []

        for ticket in tickets:
            t_data = {
                "id": ticket.id,
                "ticket_code": ticket.get_ticket_code(),
                "title": ticket.title,
                "description": ticket.description,
                "status": ticket.status,
                "priority": ticket.priority,
                "company": ticket.company.name if ticket.company else None,
                "created_by": ticket.created_by.username if ticket.created_by else None,
                "assigned_to": ticket.assigned_to.username if ticket.assigned_to else None,
                "category": ticket.ticket_category.name if ticket.ticket_category else None,
                "module_category": ticket.module_category.name if ticket.module_category else None,
                "custom_fields": ticket.custom_fields_data,
                "resolution_notes": ticket.resolution_notes,
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
                "comments": []
            }

            # Gather comments
            comments = TicketComment.objects.filter(ticket=ticket).select_related('author')
            for c in comments:
                c_data = {
                    "id": c.id,
                    "author": c.author.username if c.author else "System",
                    "content": c.content,
                    "created_at": c.created_at.isoformat(),
                    "attachments": []
                }
                for att in c.attachments.all():
                    if att.file and os.path.exists(att.file.path):
                        c_data["attachments"].append({
                            "filename": att.filename or os.path.basename(att.file.name),
                            "path": f"attachments/comment_{c.id}_{os.path.basename(att.file.name)}"
                        })
                        attachments_to_pack.append((att.file.path, f"attachments/comment_{c.id}_{os.path.basename(att.file.name)}"))
                t_data["comments"].append(c_data)

            # Ticket direct attachments
            if hasattr(ticket, 'attachments'):
                for att in ticket.attachments.all():
                    if att.file and os.path.exists(att.file.path):
                        attachments_to_pack.append((att.file.path, f"attachments/ticket_{ticket.id}_{os.path.basename(att.file.name)}"))

            tickets_data.append(t_data)

        # Create Zip file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("tickets.json", json.dumps(tickets_data, indent=2, ensure_ascii=False))
            for file_on_disk, arcname in attachments_to_pack:
                if os.path.exists(file_on_disk):
                    zipf.write(file_on_disk, arcname)

        file_size = os.path.getsize(zip_path)
        uploaded, cloud_msg = upload_to_gdrive(zip_path)

        ticket_ids = ", ".join([f"#{t.id}" for t in tickets])
        details = f"2-Hour Incremental Backup of {tickets.count()} ticket(s) ({ticket_ids}). {cloud_msg}"
        log = BackupLog.objects.create(
            filename=archive_name,
            file_size_bytes=file_size,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
            details=details
        )
        return {"success": True, "log": log, "count": tickets.count(), "details": details, "file_path": zip_path}
    except Exception as e:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        log = BackupLog.objects.create(
            filename=archive_name,
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_FAILED,
            details=f"Incremental Backup Failed: {str(e)}"
        )
        return {"success": False, "log": log, "error": str(e)}
