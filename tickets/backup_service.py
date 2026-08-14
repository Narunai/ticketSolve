import os
import json
import io
import hashlib
import stat
import subprocess
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
from .backup_restore_service import (
    BACKUP_FORMAT_VERSION,
    file_sha256,
    make_backup_manifest,
    MEDIA_INDEX_PATH,
    validate_backup_archive,
)

BACKUP_DIR = os.path.abspath(
    os.environ.get("BACKUP_DIR", os.path.join(settings.BASE_DIR, "backups"))
)
BACKUP_RETENTION_DAYS = max(1, int(os.environ.get("BACKUP_RETENTION_DAYS", "30")))
CHATBOT_DB_PATH = os.path.abspath(
    os.environ.get("CHATBOT_DB_PATH", "/var/lib/ticketsolve-chatbot/chatbot.db")
)


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
            if BackupLog.objects.filter(filename=filename, is_protected=True).exists():
                continue
        except Exception:
            # Cleanup must never remove an archive when protection state cannot
            # be verified (for example while a database restore is in flight).
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


def _snapshot_chatbot_database(destination_path):
    """Create a transaction-consistent copy of the optional chatbot SQLite DB."""
    if not os.path.isfile(CHATBOT_DB_PATH):
        return False
    source = sqlite3.connect(f"file:{CHATBOT_DB_PATH}?mode=ro", uri=True, timeout=10)
    destination = sqlite3.connect(destination_path)
    try:
        with destination:
            source.backup(destination, pages=100, sleep=0.01)
    finally:
        destination.close()
        source.close()
    return True


def _build_media_file_index(media_root):
    """Hash every regular media file and reject links/special files."""
    files = {}
    for current_root, directories, filenames in os.walk(media_root, followlinks=False):
        for directory_name in directories:
            directory_path = os.path.join(current_root, directory_name)
            if os.path.islink(directory_path):
                raise ValueError('Media backup refuses symbolic-link directories.')
        for filename in filenames:
            source_path = os.path.join(current_root, filename)
            file_stat = os.lstat(source_path)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError('Media backup only accepts regular files.')
            relative_path = os.path.relpath(source_path, media_root).replace(os.sep, '/')
            archive_name = f'media/{relative_path}'
            files[archive_name] = file_sha256(source_path)
    return {
        'format_version': '1',
        'files': dict(sorted(files.items())),
    }


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
    temp_pg_path = os.path.join(BACKUP_DIR, f"temp_pg_{now_str}.dump")
    temp_chatbot_path = os.path.join(BACKUP_DIR, f"temp_chatbot_{now_str}.sqlite3")

    with FileLock("system_backup.lock", timeout=60):
        try:
            is_pg = is_postgresql_backend()

            if is_pg:
                # Native PostgreSQL custom format is transaction-consistent and
                # supports an atomic single-transaction pg_restore workflow.
                database = settings.DATABASES['default']
                environment = os.environ.copy()
                if database.get('PASSWORD'):
                    environment['PGPASSWORD'] = str(database['PASSWORD'])
                command = [
                    'pg_dump',
                    '--format=custom',
                    '--no-owner',
                    '--no-acl',
                    '--file',
                    temp_pg_path,
                ]
                if database.get('HOST'):
                    command.extend(['--host', str(database['HOST'])])
                if database.get('PORT'):
                    command.extend(['--port', str(database['PORT'])])
                if database.get('USER'):
                    command.extend(['--username', str(database['USER'])])
                command.append(str(database['NAME']))
                subprocess.run(
                    command,
                    check=True,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
            else:
                # SQLite Backup: Perform safe online SQLite backup to temp_db_path to prevent WAL corruption
                database_name = str(settings.DATABASES['default']['NAME'])
                is_memory_database = (
                    database_name == ':memory:'
                    or 'mode=memory' in database_name
                )
                if is_memory_database:
                    # TestCase keeps an outer transaction open; SQLite's backup
                    # loop waits on that transaction. serialize() creates the
                    # same consistent snapshot without waiting for a commit.
                    connection.ensure_connection()
                    serialized = connection.connection.serialize()
                    with open(temp_db_path, 'wb') as destination:
                        destination.write(serialized)
                else:
                    db_path = os.path.abspath(database_name)
                    if not os.path.isfile(db_path):
                        raise FileNotFoundError('The SQLite database file was not found.')
                    src_conn = sqlite3.connect(db_path)
                    dst_conn = sqlite3.connect(temp_db_path)
                    try:
                        with dst_conn:
                            src_conn.backup(dst_conn, pages=100, sleep=0.01)
                    finally:
                        dst_conn.close()
                        src_conn.close()

            chatbot_included = _snapshot_chatbot_database(temp_chatbot_path)

            if is_pg:
                database_arcname = 'database/postgresql.dump'
                database_path = temp_pg_path
                database_format = 'postgresql_custom'
            else:
                database_arcname = 'database/db.sqlite3'
                database_path = temp_db_path
                database_format = 'sqlite3'
            if not os.path.isfile(database_path):
                raise FileNotFoundError('The database backup payload was not created.')

            payloads = {database_arcname: file_sha256(database_path)}
            if chatbot_included:
                payloads['chatbot/chatbot.db'] = file_sha256(temp_chatbot_path)
            media_path = os.path.abspath(str(settings.MEDIA_ROOT))
            media_included = os.path.isdir(media_path)
            media_index_bytes = b''
            if media_included:
                media_index = _build_media_file_index(media_path)
                media_index_bytes = json.dumps(
                    media_index,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                ).encode('utf-8')
                payloads[MEDIA_INDEX_PATH] = hashlib.sha256(media_index_bytes).hexdigest()
            manifest = make_backup_manifest(
                backup_type=BackupLog.TYPE_FULL,
                database_format=database_format,
                payloads=payloads,
                includes_media=media_included,
                includes_chatbot=chatbot_included,
            )
            manifest_bytes = json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ).encode('utf-8')

            # Package the database and media
            with tarfile.open(backup_filepath, "w:gz") as tar:
                tar.add(database_path, arcname=database_arcname)
                if chatbot_included:
                    tar.add(temp_chatbot_path, arcname="chatbot/chatbot.db")
                if media_included:
                    tar.add(media_path, arcname="media")
                    media_index_info = tarfile.TarInfo(MEDIA_INDEX_PATH)
                    media_index_info.size = len(media_index_bytes)
                    media_index_info.mtime = int(timezone.now().timestamp())
                    tar.addfile(media_index_info, io.BytesIO(media_index_bytes))

                manifest_info = tarfile.TarInfo('backup_manifest.json')
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(timezone.now().timestamp())
                tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

            validation = validate_backup_archive(backup_filepath)
            if not validation.get('restore_supported'):
                raise ValueError(
                    'Generated Full Backup did not pass post-write validation: '
                    f"{validation.get('details', 'unknown validation error')}"
                )

            # Clean up temporary backup files
            for p in (temp_db_path, temp_pg_path, temp_chatbot_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            file_size = os.path.getsize(backup_filepath)
            archive_sha256 = file_sha256(backup_filepath)
            expired_count = cleanup_expired_backups()

            db_type = "PostgreSQL" if is_pg else "SQLite"
            details = (
                f"Full Backup ({db_type}, {file_size} bytes). Stored locally on the AWS VPS. "
                f"Chatbot data included: {'yes' if chatbot_included else 'not installed'}. "
                f"Expired local archives removed: {expired_count}."
            )
            log = BackupLog.objects.create(
                filename=archive_name,
                original_filename=archive_name,
                file_size_bytes=file_size,
                backup_type=BackupLog.TYPE_FULL,
                status=BackupLog.STATUS_SUCCESS,
                source=BackupLog.SOURCE_GENERATED,
                sha256=archive_sha256,
                format_version=BACKUP_FORMAT_VERSION,
                validation_status=BackupLog.VALIDATION_VALID,
                validation_details='Generated and checksummed by TicketSolve.',
                restore_supported=True,
                details=details
            )
            return {"success": True, "log": log, "details": details, "file_path": backup_filepath}
        except Exception as e:
            for p in (temp_db_path, temp_pg_path, temp_chatbot_path):
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
                original_filename=archive_name,
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
    temp_chatbot_path = os.path.join(BACKUP_DIR, f"temp_system_chatbot_{now_str}.sqlite3")

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

            chatbot_included = _snapshot_chatbot_database(temp_chatbot_path)
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
                    'chatbot configuration, curated knowledge, and chatbot admin audit log'
                    if chatbot_included else 'chatbot data not installed',
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
                if chatbot_included:
                    archive.add(temp_chatbot_path, arcname='chatbot/chatbot.db')

                manifest_info = tarfile.TarInfo('backup_manifest.json')
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(timezone.now().timestamp())
                archive.addfile(manifest_info, io.BytesIO(manifest_bytes))

            for p in (temp_db_path, temp_json_path, temp_chatbot_path):
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
                f"Includes database configuration/master data and chatbot data: {'yes' if chatbot_included else 'not installed'}; "
                'excludes media and runtime secrets. '
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
            for path in (temp_db_path, temp_json_path, temp_chatbot_path, archive_path):
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
