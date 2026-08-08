import os
import json
import io
import sqlite3
import tarfile
import time
import zipfile
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import connection, models
from django.db.models import Q
from django.core.management import call_command

from .models import BackupLog, Ticket, TicketComment

BACKUP_DIR = os.path.abspath(
    os.environ.get("BACKUP_DIR", os.path.join(settings.BASE_DIR, "backups"))
)
BACKUP_RETENTION_DAYS = max(1, int(os.environ.get("BACKUP_RETENTION_DAYS", "30")))


def get_backup_file_path(filename):
    """Returns absolute filepath in BACKUP_DIR if it exists, else None."""
    if not filename or os.path.basename(filename) != filename:
        return None
    path = os.path.abspath(os.path.join(BACKUP_DIR, filename))
    try:
        is_inside_backup_dir = os.path.commonpath([BACKUP_DIR, path]) == BACKUP_DIR
    except ValueError:
        is_inside_backup_dir = False
    if is_inside_backup_dir and os.path.isfile(path):
        return path
    return None


def cleanup_expired_backups():
    """Delete local AWS VPS backup archives older than the retention policy."""
    if not os.path.isdir(BACKUP_DIR):
        return 0
    cutoff = timezone.now().timestamp() - (BACKUP_RETENTION_DAYS * 86400)
    deleted_count = 0
    for filename in os.listdir(BACKUP_DIR):
        if not filename.endswith(('.zip', '.tar.gz')):
            continue
        path = get_backup_file_path(filename)
        if not path:
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                deleted_count += 1
        except OSError:
            continue
    return deleted_count


class FileLock:
    """
    Cross-platform inter-process lock manager.
    Ensures safe synchronization between background backup operations,
    active database queues, and file uploads.
    """
    def __init__(self, lock_file_name="system_backup.lock", timeout=60, poll_interval=0.5):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self.lock_file_path = os.path.join(BACKUP_DIR, lock_file_name)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.fd = None

    def acquire(self):
        end_time = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.lock_file_path, os.O_CREAT | os.O_RDWR | os.O_EXCL)
                return True
            except OSError:
                try:
                    mtime = os.path.getmtime(self.lock_file_path)
                    if time.time() - mtime > (self.timeout + 10):
                        try:
                            os.remove(self.lock_file_path)
                        except OSError:
                            pass
                except OSError:
                    pass

                if time.time() >= end_time:
                    return False
                time.sleep(self.poll_interval)

    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
            try:
                if os.path.exists(self.lock_file_path):
                    os.remove(self.lock_file_path)
            except OSError:
                pass

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(
                f"Timed out waiting for backup lock: {self.lock_file_path}"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def is_postgresql_backend():
    engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
    return 'postgresql' in engine or 'postgres' in engine


def perform_full_backup():
    """
    Creates a full backup of the database (via PostgreSQL dump or SQLite Online Backup API) and media.
    Waits for active locks/queues (up to 60s) before execution.
    Saves to BACKUP_DIR on the AWS VPS for authorized local download.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now_str = timezone.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"full_backup_{now_str}.tar.gz"
    backup_filepath = os.path.join(BACKUP_DIR, archive_name)
    temp_db_path = os.path.join(BACKUP_DIR, f"temp_db_{now_str}.sqlite3")
    temp_json_path = os.path.join(BACKUP_DIR, f"temp_dump_{now_str}.json")

    with FileLock("system_backup.lock", timeout=60):
        try:
            is_pg = is_postgresql_backend()

            if is_pg:
                # PostgreSQL Backup: Export full dataset to structured JSON dump
                orig_close = connection.close
                connection.close = lambda: None
                try:
                    with open(temp_json_path, 'w', encoding='utf-8') as f:
                        call_command('dumpdata', database='default', indent=2, stdout=f)
                finally:
                    connection.close = orig_close
                connection.ensure_connection()
            else:
                # SQLite Backup: Perform safe online SQLite backup to temp_db_path to prevent WAL corruption
                db_path = os.path.join(settings.BASE_DIR, "db.sqlite3")
                if os.path.exists(db_path):
                    src_conn = sqlite3.connect(db_path)
                    dst_conn = sqlite3.connect(temp_db_path)
                    with dst_conn:
                        src_conn.backup(dst_conn, pages=100, sleep=0.01)
                    dst_conn.close()
                    src_conn.close()

            # Package the database and media
            with tarfile.open(backup_filepath, "w:gz") as tar:
                if is_pg and os.path.exists(temp_json_path):
                    tar.add(temp_json_path, arcname="db_dump.json")
                elif os.path.exists(temp_db_path):
                    tar.add(temp_db_path, arcname="db.sqlite3")
                elif os.path.exists(os.path.join(settings.BASE_DIR, "db.sqlite3")):
                    tar.add(os.path.join(settings.BASE_DIR, "db.sqlite3"), arcname="db.sqlite3")

                media_path = os.path.join(settings.BASE_DIR, "media")
                if os.path.exists(media_path):
                    tar.add(media_path, arcname="media")

            # Clean up temporary backup files
            for p in (temp_db_path, temp_json_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            file_size = os.path.getsize(backup_filepath)
            expired_count = cleanup_expired_backups()

            db_type = "PostgreSQL" if is_pg else "SQLite"
            details = (
                f"Full Backup ({db_type}, {file_size} bytes). Stored locally on the AWS VPS. "
                f"Expired local archives removed: {expired_count}."
            )
            log = BackupLog.objects.create(
                filename=archive_name,
                file_size_bytes=file_size,
                backup_type=BackupLog.TYPE_FULL,
                status=BackupLog.STATUS_SUCCESS,
                details=details
            )
            return {"success": True, "log": log, "details": details, "file_path": backup_filepath}
        except Exception as e:
            for p in (temp_db_path, temp_json_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            if os.path.exists(backup_filepath):
                try:
                    os.remove(backup_filepath)
                except OSError:
                    pass
            log = BackupLog.objects.create(
                filename=archive_name,
                file_size_bytes=0,
                backup_type=BackupLog.TYPE_FULL,
                status=BackupLog.STATUS_FAILED,
                details=f"Backup Failed: {str(e)}"
            )
            return {"success": False, "log": log, "error": str(e)}


def perform_system_data_backup():
    """Back up the database configuration/master data without Ticket rows."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now_str = timezone.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"system_data_no_tickets_{now_str}.tar.gz"
    archive_path = os.path.join(BACKUP_DIR, archive_name)
    temp_db_path = os.path.join(BACKUP_DIR, f"temp_system_data_{now_str}.sqlite3")
    temp_json_path = os.path.join(BACKUP_DIR, f"temp_system_data_{now_str}.json")

    with FileLock("system_backup.lock", timeout=60):
        try:
            is_pg = is_postgresql_backend()
            removed_ticket_count = Ticket.objects.count()

            if is_pg:
                # PostgreSQL Backup: Export system master data excluding ticket-specific models
                excluded_models = [
                    'tickets.ticket',
                    'tickets.ticketcomment',
                    'tickets.ticketattachment',
                    'tickets.commentattachment',
                    'tickets.ticketauditlog',
                    'tickets.inappnotification',
                ]
                orig_close = connection.close
                connection.close = lambda: None
                try:
                    with open(temp_json_path, 'w', encoding='utf-8') as f:
                        call_command('dumpdata', database='default', exclude=excluded_models, indent=2, stdout=f)
                finally:
                    connection.close = orig_close
                connection.ensure_connection()
            else:
                # SQLite Backup: Clone and sanitize SQLite database
                db_path = os.path.join(settings.BASE_DIR, "db.sqlite3")
                if not os.path.isfile(db_path):
                    raise FileNotFoundError('The SQLite database file was not found.')

                source_connection = sqlite3.connect(db_path)
                destination_connection = sqlite3.connect(temp_db_path)
                try:
                    with destination_connection:
                        source_connection.backup(
                            destination_connection,
                            pages=100,
                            sleep=0.01,
                        )
                finally:
                    destination_connection.close()
                    source_connection.close()

                sanitized_connection = sqlite3.connect(temp_db_path)
                try:
                    sanitized_connection.execute('PRAGMA foreign_keys = ON')
                    ticket_table = sanitized_connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tickets_ticket'"
                    ).fetchone()
                    if not ticket_table:
                        raise RuntimeError('The Ticket table was not found in the database snapshot.')

                    removed_ticket_count = sanitized_connection.execute(
                        'SELECT COUNT(*) FROM tickets_ticket'
                    ).fetchone()[0]
                    table_names = {
                        row[0]
                        for row in sanitized_connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    with sanitized_connection:
                        if 'tickets_inboundemailreceipt' in table_names:
                            sanitized_connection.execute(
                                'UPDATE tickets_inboundemailreceipt SET ticket_id = NULL'
                            )
                        if 'tickets_inappnotification' in table_names:
                            sanitized_connection.execute('DELETE FROM tickets_inappnotification')
                        for dependent_table in (
                            'tickets_commentattachment',
                            'tickets_ticketcomment',
                            'tickets_ticketattachment',
                            'tickets_ticketauditlog',
                        ):
                            if dependent_table in table_names:
                                sanitized_connection.execute(f'DELETE FROM {dependent_table}')
                        sanitized_connection.execute('DELETE FROM tickets_ticket')
                        if 'sqlite_sequence' in table_names:
                            sanitized_connection.execute(
                                "DELETE FROM sqlite_sequence WHERE name IN ("
                                "'tickets_ticket', 'tickets_ticketcomment', "
                                "'tickets_ticketattachment', 'tickets_commentattachment', "
                                "'tickets_ticketauditlog', 'tickets_inappnotification')"
                            )

                    remaining_ticket_count = sanitized_connection.execute(
                        'SELECT COUNT(*) FROM tickets_ticket'
                    ).fetchone()[0]
                    foreign_key_errors = sanitized_connection.execute(
                        'PRAGMA foreign_key_check'
                    ).fetchall()
                    if remaining_ticket_count or foreign_key_errors:
                        raise RuntimeError('Ticket data could not be removed safely from the snapshot.')
                    sanitized_connection.execute('VACUUM')
                finally:
                    sanitized_connection.close()

            manifest = {
                'backup_type': 'SYSTEM_DATA_NO_TICKETS',
                'database_engine': 'PostgreSQL' if is_pg else 'SQLite',
                'created_at': timezone.now().isoformat(),
                'removed_ticket_count': removed_ticket_count,
                'included': [
                    'Database master data schema and records',
                    'users and companies',
                    'roles and system configuration',
                    'SMTP/IMAP and Email-to-Ticket configuration',
                    'routing, schedules, categories, and non-ticket records',
                ],
                'excluded': [
                    'Ticket rows and database rows deleted by Ticket foreign-key cascades',
                    'media directory and Ticket attachments',
                    'runtime environment secrets',
                ],
            }
            manifest_bytes = json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ).encode('utf-8')
            with tarfile.open(archive_path, 'w:gz') as archive:
                if is_pg and os.path.exists(temp_json_path):
                    archive.add(temp_json_path, arcname='system_data.json')
                elif os.path.exists(temp_db_path):
                    archive.add(temp_db_path, arcname='db.sqlite3')

                manifest_info = tarfile.TarInfo('backup_manifest.json')
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(timezone.now().timestamp())
                archive.addfile(manifest_info, io.BytesIO(manifest_bytes))

            for p in (temp_db_path, temp_json_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            file_size = os.path.getsize(archive_path)
            expired_count = cleanup_expired_backups()
            db_label = "PostgreSQL" if is_pg else "SQLite"
            details = (
                f'System Data Backup without Tickets ({db_label}) '
                f'({file_size} bytes, excluded {removed_ticket_count} Ticket row(s)). '
                'Includes database configuration/master data; excludes media and runtime secrets. '
                f'Expired local archives removed: {expired_count}.'
            )
            log = BackupLog.objects.create(
                filename=archive_name,
                file_size_bytes=file_size,
                backup_type=BackupLog.TYPE_SYSTEM,
                status=BackupLog.STATUS_SUCCESS,
                details=details,
            )
            return {
                'success': True,
                'log': log,
                'details': details,
                'file_path': archive_path,
                'removed_ticket_count': removed_ticket_count,
            }
        except Exception as exc:
            for path in (temp_db_path, archive_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            log = BackupLog.objects.create(
                filename=archive_name,
                file_size_bytes=0,
                backup_type=BackupLog.TYPE_SYSTEM,
                status=BackupLog.STATUS_FAILED,
                details=f'System Data Backup Failed: {str(exc)}',
            )
            return {'success': False, 'log': log, 'error': str(exc)}


def perform_incremental_backup(hours=2):
    """
    Exports tickets created in the last `hours` hours + their comments & attachments.
    Waits for active locks/queues (up to 60s) before execution.
    Saves to BACKUP_DIR on the AWS VPS for authorized local download.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now = timezone.now()
    since = now - timedelta(hours=hours)
    now_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"incremental_backup_{now_str}.zip"

    with FileLock("system_backup.lock", timeout=60):
        tickets = Ticket.objects.filter(
            Q(created_at__gte=since)
            | Q(updated_at__gte=since)
            | Q(status_changed_at__gte=since)
            | Q(comments__created_at__gte=since)
            | Q(attachments__uploaded_at__gte=since)
            | Q(comments__attachments__uploaded_at__gte=since)
        ).distinct().select_related(
            'company',
            'created_by',
            'assigned_to',
            'ticket_category',
            'module_category',
        )

        if not tickets.exists():
            expired_count = cleanup_expired_backups()
            log = BackupLog.objects.create(
                filename=archive_name,
                file_size_bytes=0,
                backup_type=BackupLog.TYPE_INCREMENTAL,
                status=BackupLog.STATUS_SUCCESS,
                details=(
                    f"No tickets changed in the last {hours} hours. "
                    f"Expired local archives removed: {expired_count}."
                )
            )
            return {
                "success": True,
                "log": log,
                "count": 0,
                "message": f"No tickets changed in the last {hours} hours.",
            }

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
                    "attachments": [],
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
                            archive_path = f"attachments/ticket_{ticket.id}_{os.path.basename(att.file.name)}"
                            t_data["attachments"].append({
                                "filename": att.filename or os.path.basename(att.file.name),
                                "path": archive_path,
                            })
                            attachments_to_pack.append((att.file.path, archive_path))

                # Preserve legacy FileField attachments created before the
                # related TicketAttachment model was introduced.
                related_paths = {path for path, _ in attachments_to_pack}
                if (
                    ticket.attachment
                    and os.path.exists(ticket.attachment.path)
                    and ticket.attachment.path not in related_paths
                ):
                    archive_path = (
                        f"attachments/ticket_{ticket.id}_"
                        f"{os.path.basename(ticket.attachment.name)}"
                    )
                    t_data["attachments"].append({
                        "filename": os.path.basename(ticket.attachment.name),
                        "path": archive_path,
                    })
                    attachments_to_pack.append(
                        (ticket.attachment.path, archive_path)
                    )

                tickets_data.append(t_data)

            # Create Zip file
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr("tickets.json", json.dumps(tickets_data, indent=2, ensure_ascii=False))
                for file_on_disk, arcname in attachments_to_pack:
                    if os.path.exists(file_on_disk):
                        zipf.write(file_on_disk, arcname)

            file_size = os.path.getsize(zip_path)
            expired_count = cleanup_expired_backups()

            ticket_ids = ", ".join([f"#{t.id}" for t in tickets])
            details = (
                f"{hours}-Hour Incremental Backup of {tickets.count()} changed ticket(s) "
                f"({ticket_ids}). Stored locally on the AWS VPS. "
                f"Expired local archives removed: {expired_count}."
            )
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
