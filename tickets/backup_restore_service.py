"""Validation, import, and restore helpers for TicketSolve backup archives.

Uploaded archives are always written to a quarantine directory first.  Nothing
from an uploaded archive is extracted into the application or database until it
has passed the structural, size, checksum, version, and compatibility checks in
this module.
"""

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import PurePosixPath

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

from .models import BackupLog, BackupUploadSession


BACKUP_FORMAT_VERSION = "2"
BACKUP_DIR = os.path.abspath(
    os.environ.get("BACKUP_DIR", os.path.join(settings.BASE_DIR, "backups"))
)
BACKUP_QUARANTINE_DIR = os.path.abspath(
    os.environ.get(
        "BACKUP_QUARANTINE_DIR",
        os.path.join(BACKUP_DIR, ".quarantine"),
    )
)
BACKUP_IMPORT_MAX_BYTES = max(
    16 * 1024 * 1024,
    int(os.environ.get("BACKUP_IMPORT_MAX_BYTES", str(512 * 1024 * 1024))),
)
BACKUP_CHUNK_MAX_BYTES = max(
    1024 * 1024,
    min(
        16 * 1024 * 1024,
        int(os.environ.get("BACKUP_CHUNK_MAX_BYTES", str(8 * 1024 * 1024))),
    ),
)
BACKUP_MAX_MEMBERS = max(100, int(os.environ.get("BACKUP_MAX_MEMBERS", "50000")))
BACKUP_MAX_EXPANDED_BYTES = max(
    BACKUP_IMPORT_MAX_BYTES,
    int(os.environ.get("BACKUP_MAX_EXPANDED_BYTES", str(4 * 1024 * 1024 * 1024))),
)
BACKUP_MAX_COMPRESSION_RATIO = max(
    10,
    int(os.environ.get("BACKUP_MAX_COMPRESSION_RATIO", "200")),
)
MEDIA_INDEX_PATH = "metadata/media_files.json"
MEDIA_INDEX_MAX_BYTES = max(
    1024 * 1024,
    min(
        16 * 1024 * 1024,
        int(os.environ.get("BACKUP_MEDIA_INDEX_MAX_BYTES", str(8 * 1024 * 1024))),
    ),
)
RESTORE_TRIGGER_FILE = os.path.abspath(
    os.environ.get(
        "RESTORE_TRIGGER_FILE",
        os.path.join(settings.BASE_DIR, ".restore", "restore.trigger"),
    )
)


def ensure_backup_directories():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(BACKUP_QUARANTINE_DIR, exist_ok=True)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stream_sha256(source):
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def encryption_key_fingerprint():
    keys = list(getattr(settings, "FIELD_ENCRYPTION_KEYS", []))
    if not keys:
        return "development-derived"
    return hashlib.sha256(keys[0].encode("utf-8")).hexdigest()[:16]


def current_database_engine():
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    return "PostgreSQL" if "postgres" in engine else "SQLite"


def _manifest_signature(manifest):
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_signature"}
    payload = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(
        settings.BACKUP_MANIFEST_SIGNING_KEY.encode("utf-8"),
        b"ticketsolve-backup-manifest-v2\x00" + payload,
        hashlib.sha256,
    ).hexdigest()


def make_backup_manifest(*, backup_type, database_format, payloads, includes_media, includes_chatbot):
    manifest = {
        "format_version": BACKUP_FORMAT_VERSION,
        "product": "TicketSolve",
        "backup_type": backup_type,
        "created_at": timezone.now().isoformat(),
        "database_engine": current_database_engine(),
        "database_format": database_format,
        "field_encryption_key_fingerprint": encryption_key_fingerprint(),
        "includes_media": bool(includes_media),
        "includes_chatbot": bool(includes_chatbot),
        "payloads": payloads,
        "runtime_secrets_included": False,
    }
    manifest["manifest_signature"] = _manifest_signature(manifest)
    return manifest


def _safe_archive_name(name):
    if not name or "\\" in name or name.startswith(("/", "\\")):
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "." != str(path)


def _archive_limits_ok(member_count, expanded_size, compressed_size):
    if member_count > BACKUP_MAX_MEMBERS:
        return False, f"Archive contains more than {BACKUP_MAX_MEMBERS} entries."
    if expanded_size > BACKUP_MAX_EXPANDED_BYTES:
        return False, "Expanded archive size exceeds the configured safety limit."
    ratio_base = max(compressed_size, 1)
    if expanded_size > ratio_base * BACKUP_MAX_COMPRESSION_RATIO:
        return False, "Archive compression ratio exceeds the configured safety limit."
    return True, ""


def _manifest_result(manifest, names, archive_reader, archive_sha):
    backup_type = manifest.get("backup_type")
    if backup_type == "SYSTEM_DATA_NO_TICKETS":
        backup_type = BackupLog.TYPE_SYSTEM
    if backup_type not in {
        BackupLog.TYPE_FULL,
        BackupLog.TYPE_INCREMENTAL,
        BackupLog.TYPE_SYSTEM,
    }:
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": BackupLog.TYPE_FULL,
            "format_version": str(manifest.get("format_version", ""))[:20],
            "sha256": archive_sha,
            "details": "The backup manifest contains an unsupported backup type.",
            "restore_supported": False,
            "manifest": manifest,
        }

    format_version = str(manifest.get("format_version", ""))
    if not format_version:
        return {
            "valid": True,
            "status": BackupLog.VALIDATION_LEGACY,
            "backup_type": backup_type,
            "format_version": "legacy",
            "sha256": archive_sha,
            "details": "Legacy TicketSolve archive: retained, but one-click restore is disabled.",
            "restore_supported": False,
            "manifest": manifest,
        }
    if format_version != BACKUP_FORMAT_VERSION or manifest.get("product") != "TicketSolve":
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": backup_type,
            "format_version": format_version[:20],
            "sha256": archive_sha,
            "details": "The backup format or product identifier is not supported by this release.",
            "restore_supported": False,
            "manifest": manifest,
        }
    supplied_signature = str(manifest.get("manifest_signature", ""))
    if not supplied_signature or not hmac.compare_digest(
        supplied_signature,
        _manifest_signature(manifest),
    ):
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": backup_type,
            "format_version": format_version,
            "sha256": archive_sha,
            "details": "Backup manifest signature is missing or invalid.",
            "restore_supported": False,
            "manifest": manifest,
        }

    payloads = manifest.get("payloads")
    if not isinstance(payloads, dict) or not payloads:
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": backup_type,
            "format_version": format_version,
            "sha256": archive_sha,
            "details": "The backup manifest does not contain payload checksums.",
            "restore_supported": False,
            "manifest": manifest,
        }
    for payload_name, expected_digest in payloads.items():
        if not _safe_archive_name(payload_name) or payload_name not in names:
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": f"Required payload is missing: {payload_name}",
                "restore_supported": False,
                "manifest": manifest,
            }
        source = archive_reader(payload_name)
        if source is None:
            actual_digest = ""
        else:
            try:
                actual_digest = stream_sha256(source)
            finally:
                source.close()
        if not expected_digest or len(str(expected_digest)) != 64:
            actual_digest = "invalid-manifest-digest"
        if not hmac.compare_digest(actual_digest, str(expected_digest)):
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": f"Payload checksum mismatch: {payload_name}",
                "restore_supported": False,
                "manifest": manifest,
            }

    if manifest.get("includes_media"):
        if MEDIA_INDEX_PATH not in payloads:
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": "Full backup media is not covered by a signed file index.",
                "restore_supported": False,
                "manifest": manifest,
            }
        index_source = archive_reader(MEDIA_INDEX_PATH)
        try:
            raw_index = index_source.read(MEDIA_INDEX_MAX_BYTES + 1) if index_source else b""
        finally:
            if index_source:
                index_source.close()
        if len(raw_index) > MEDIA_INDEX_MAX_BYTES:
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": "The signed media file index exceeds the configured safety limit.",
                "restore_supported": False,
                "manifest": manifest,
            }
        try:
            media_index = json.loads(raw_index.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            media_index = None
        media_files = media_index.get("files") if isinstance(media_index, dict) else None
        if (
            not isinstance(media_index, dict)
            or media_index.get("format_version") != "1"
            or not isinstance(media_files, dict)
            or len(media_files) > BACKUP_MAX_MEMBERS
        ):
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": "The signed media file index is invalid.",
                "restore_supported": False,
                "manifest": manifest,
            }
        indexed_names = set(media_files)
        archived_media_names = {name for name in names if name.startswith("media/")}
        if indexed_names != archived_media_names:
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": "Archived media files do not match the signed media file index.",
                "restore_supported": False,
                "manifest": manifest,
            }
        for media_name, expected_digest in media_files.items():
            if (
                not _safe_archive_name(media_name)
                or not media_name.startswith("media/")
                or len(str(expected_digest)) != 64
            ):
                return {
                    "valid": False,
                    "status": BackupLog.VALIDATION_INVALID,
                    "backup_type": backup_type,
                    "format_version": format_version,
                    "sha256": archive_sha,
                    "details": "The signed media file index contains an invalid entry.",
                    "restore_supported": False,
                    "manifest": manifest,
                }
            media_source = archive_reader(media_name)
            try:
                actual_digest = stream_sha256(media_source) if media_source else ""
            finally:
                if media_source:
                    media_source.close()
            if not hmac.compare_digest(actual_digest, str(expected_digest)):
                return {
                    "valid": False,
                    "status": BackupLog.VALIDATION_INVALID,
                    "backup_type": backup_type,
                    "format_version": format_version,
                    "sha256": archive_sha,
                    "details": f"Media checksum mismatch: {media_name}",
                    "restore_supported": False,
                    "manifest": manifest,
                }

    if backup_type == BackupLog.TYPE_FULL:
        database_format = manifest.get("database_format")
        if database_format == "sqlite3":
            database_payload = "database/db.sqlite3"
            expected_magic = b"SQLite format 3\x00"
        elif database_format == "postgresql_custom":
            database_payload = "database/postgresql.dump"
            expected_magic = b"PGDMP"
        else:
            database_payload = ""
            expected_magic = b""
        database_source = archive_reader(database_payload) if database_payload in names else None
        try:
            database_magic = database_source.read(len(expected_magic)) if database_source else b""
        finally:
            if database_source:
                database_source.close()
        if not database_payload or not expected_magic or database_magic != expected_magic:
            return {
                "valid": False,
                "status": BackupLog.VALIDATION_INVALID,
                "backup_type": backup_type,
                "format_version": format_version,
                "sha256": archive_sha,
                "details": "Database payload signature does not match the declared format.",
                "restore_supported": False,
                "manifest": manifest,
            }

    engine_matches = manifest.get("database_engine") == current_database_engine()
    key_matches = manifest.get("field_encryption_key_fingerprint") == encryption_key_fingerprint()
    database_format = manifest.get("database_format")
    expected_format = (
        "postgresql_custom"
        if current_database_engine() == "PostgreSQL"
        else "sqlite3"
    )
    restore_supported = bool(
        backup_type == BackupLog.TYPE_FULL
        and engine_matches
        and key_matches
        and database_format == expected_format
    )
    compatibility_notes = []
    if backup_type != BackupLog.TYPE_FULL:
        compatibility_notes.append("only Full Backup supports complete restore")
    if not engine_matches:
        compatibility_notes.append("database engine differs")
    if not key_matches:
        compatibility_notes.append("field encryption key differs")
    if database_format != expected_format:
        compatibility_notes.append("database payload format differs")
    details = "Validated TicketSolve backup archive."
    if compatibility_notes:
        details += " Restore unavailable: " + ", ".join(compatibility_notes) + "."
    return {
        "valid": True,
        "status": BackupLog.VALIDATION_VALID,
        "backup_type": backup_type,
        "format_version": format_version,
        "sha256": archive_sha,
        "details": details,
        "restore_supported": restore_supported,
        "manifest": manifest,
    }


def _legacy_result(names, archive_sha):
    if "tickets.json" in names:
        backup_type = BackupLog.TYPE_INCREMENTAL
    elif "system_data.json" in names or "backup_manifest.json" in names:
        backup_type = BackupLog.TYPE_SYSTEM
    elif {"db_dump.json", "db.sqlite3"}.intersection(names):
        backup_type = BackupLog.TYPE_FULL
    else:
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": BackupLog.TYPE_FULL,
            "format_version": "",
            "sha256": archive_sha,
            "details": "The archive is not a recognized TicketSolve backup.",
            "restore_supported": False,
            "manifest": {},
        }
    return {
        "valid": True,
        "status": BackupLog.VALIDATION_LEGACY,
        "backup_type": backup_type,
        "format_version": "legacy",
        "sha256": archive_sha,
        "details": "Legacy TicketSolve archive: retained, but one-click restore is disabled.",
        "restore_supported": False,
        "manifest": {},
    }


def validate_backup_archive(path, expected_sha256=""):
    """Validate an archive without extracting it into an application directory."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": BackupLog.TYPE_FULL,
            "format_version": "",
            "sha256": "",
            "details": "Backup file is not available.",
            "restore_supported": False,
            "manifest": {},
        }
    compressed_size = os.path.getsize(path)
    if compressed_size <= 0:
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": BackupLog.TYPE_FULL,
            "format_version": "",
            "sha256": "",
            "details": "Backup file is empty.",
            "restore_supported": False,
            "manifest": {},
        }
    archive_sha = file_sha256(path)
    if expected_sha256 and not hmac.compare_digest(archive_sha, expected_sha256):
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": BackupLog.TYPE_FULL,
            "format_version": "",
            "sha256": archive_sha,
            "details": "Archive checksum does not match the recorded checksum.",
            "restore_supported": False,
            "manifest": {},
        }

    try:
        if tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                members = archive.getmembers()
                canonical_names = [str(PurePosixPath(member.name)) for member in members]
                if len(canonical_names) != len(set(canonical_names)):
                    raise ValueError("Archive contains duplicate or ambiguous paths.")
                for member in members:
                    if not _safe_archive_name(member.name):
                        raise ValueError("Archive contains an unsafe path.")
                    if member.issym() or member.islnk() or member.isdev():
                        raise ValueError("Archive contains a blocked link or device entry.")
                    if not (member.isfile() or member.isdir()):
                        raise ValueError("Archive contains an unsupported entry type.")
                expanded_size = sum(member.size for member in members if member.isfile())
                limits_ok, limit_error = _archive_limits_ok(
                    len(members), expanded_size, compressed_size
                )
                if not limits_ok:
                    raise ValueError(limit_error)
                names = {member.name for member in members if member.isfile()}
                manifest = None
                if "backup_manifest.json" in names:
                    manifest_member = archive.getmember("backup_manifest.json")
                    if manifest_member.size > 1024 * 1024:
                        raise ValueError("Backup manifest is too large.")
                    manifest_source = archive.extractfile(manifest_member)
                    if manifest_source is None:
                        raise ValueError("Backup manifest cannot be read.")
                    manifest = json.loads(manifest_source.read().decode("utf-8"))
                if manifest is not None:
                    return _manifest_result(
                        manifest,
                        names,
                        lambda name: archive.extractfile(archive.getmember(name)),
                        archive_sha,
                    )
                return _legacy_result(names, archive_sha)

        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                canonical_names = [str(PurePosixPath(member.filename)) for member in members]
                if len(canonical_names) != len(set(canonical_names)):
                    raise ValueError("Archive contains duplicate or ambiguous paths.")
                for member in members:
                    if not _safe_archive_name(member.filename):
                        raise ValueError("Archive contains an unsafe path.")
                    if member.flag_bits & 0x1:
                        raise ValueError("Encrypted ZIP entries are not supported.")
                    unix_mode = (member.external_attr >> 16) & 0o170000
                    if unix_mode not in {0, 0o040000, 0o100000}:
                        raise ValueError("Archive contains a blocked special entry.")
                expanded_size = sum(member.file_size for member in members)
                limits_ok, limit_error = _archive_limits_ok(
                    len(members), expanded_size, compressed_size
                )
                if not limits_ok:
                    raise ValueError(limit_error)
                names = {member.filename for member in members if not member.is_dir()}
                manifest = None
                if "backup_manifest.json" in names:
                    if archive.getinfo("backup_manifest.json").file_size > 1024 * 1024:
                        raise ValueError("Backup manifest is too large.")
                    manifest = json.loads(archive.read("backup_manifest.json").decode("utf-8"))
                if manifest is not None:
                    result = _manifest_result(
                        manifest,
                        names,
                        lambda name: archive.open(name, "r"),
                        archive_sha,
                    )
                    if result.get("restore_supported"):
                        result["restore_supported"] = False
                        result["details"] += " Complete restore requires a .tar.gz Full Backup."
                    return result
                return _legacy_result(names, archive_sha)
        raise ValueError("Only TicketSolve .tar.gz and .zip archives are supported.")
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return {
            "valid": False,
            "status": BackupLog.VALIDATION_INVALID,
            "backup_type": BackupLog.TYPE_FULL,
            "format_version": "",
            "sha256": archive_sha,
            "details": str(exc)[:1000],
            "restore_supported": False,
            "manifest": {},
        }


def safe_backup_extension(filename):
    lowered = os.path.basename(str(filename).replace("\\", "/")).lower()
    if lowered.endswith(".tar.gz"):
        return ".tar.gz"
    if lowered.endswith(".zip"):
        return ".zip"
    return ""


def quarantine_path(temp_filename):
    if not temp_filename or os.path.basename(temp_filename) != temp_filename:
        return None
    ensure_backup_directories()
    path = os.path.abspath(os.path.join(BACKUP_QUARANTINE_DIR, temp_filename))
    try:
        if os.path.commonpath([BACKUP_QUARANTINE_DIR, path]) != BACKUP_QUARANTINE_DIR:
            return None
    except ValueError:
        return None
    return path


def finalize_upload_session(upload_session):
    """Validate a completed quarantined upload and register or reject it."""
    temp_path = quarantine_path(upload_session.temp_filename)
    if not temp_path or not os.path.isfile(temp_path):
        raise FileNotFoundError("Quarantined upload file is not available.")
    validation = validate_backup_archive(temp_path)
    duplicate = BackupLog.objects.filter(
        sha256=validation.get("sha256", ""),
        file_size_bytes=upload_session.expected_size,
    ).first()
    duplicate_path = (
        os.path.join(BACKUP_DIR, duplicate.filename)
        if duplicate and os.path.basename(duplicate.filename) == duplicate.filename
        else ""
    )
    if duplicate and validation.get("sha256") and os.path.isfile(duplicate_path):
        os.remove(temp_path)
        upload_session.status = BackupUploadSession.STATUS_COMPLETED
        upload_session.backup_log = duplicate
        upload_session.save(update_fields=["status", "backup_log", "updated_at"])
        return duplicate, validation, True

    if not validation["valid"]:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        log = BackupLog.objects.create(
            filename=f"rejected_{upload_session.upload_id}.invalid",
            original_filename=os.path.basename(upload_session.original_filename)[:255],
            file_size_bytes=upload_session.expected_size,
            backup_type=validation["backup_type"],
            status=BackupLog.STATUS_FAILED,
            source=BackupLog.SOURCE_IMPORTED,
            sha256=validation.get("sha256", ""),
            format_version=validation.get("format_version", ""),
            validation_status=BackupLog.VALIDATION_INVALID,
            validation_details=validation["details"],
            restore_supported=False,
            uploaded_by=upload_session.uploaded_by,
            details="Imported archive rejected during security validation.",
        )
        upload_session.status = BackupUploadSession.STATUS_FAILED
        upload_session.error_message = validation["details"]
        upload_session.backup_log = log
        upload_session.save(
            update_fields=["status", "error_message", "backup_log", "updated_at"]
        )
        return log, validation, False

    extension = safe_backup_extension(upload_session.original_filename)
    timestamp = timezone.now().strftime("%Y-%m-%d_%H-%M-%S")
    final_name = f"imported_{timestamp}_{str(upload_session.upload_id)[:8]}{extension}"
    final_path = os.path.join(BACKUP_DIR, final_name)
    os.replace(temp_path, final_path)
    os.chmod(final_path, 0o640)
    log = BackupLog.objects.create(
        filename=final_name,
        original_filename=os.path.basename(upload_session.original_filename)[:255],
        file_size_bytes=os.path.getsize(final_path),
        backup_type=validation["backup_type"],
        status=BackupLog.STATUS_SUCCESS,
        source=BackupLog.SOURCE_IMPORTED,
        sha256=validation["sha256"],
        format_version=validation.get("format_version", ""),
        validation_status=validation["status"],
        validation_details=validation["details"],
        restore_supported=validation["restore_supported"],
        uploaded_by=upload_session.uploaded_by,
        details="Imported TicketSolve backup archive.",
    )
    upload_session.status = BackupUploadSession.STATUS_COMPLETED
    upload_session.backup_log = log
    upload_session.save(update_fields=["status", "backup_log", "updated_at"])
    return log, validation, False


def queue_restore_trigger(job_id):
    """Create a bounded one-job trigger consumed by the root-owned path unit."""
    trigger_dir = os.path.dirname(RESTORE_TRIGGER_FILE)
    os.makedirs(trigger_dir, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(RESTORE_TRIGGER_FILE, flags, 0o640)
    try:
        os.write(descriptor, (str(job_id) + "\n").encode("ascii"))
    finally:
        os.close(descriptor)


def extract_validated_full_archive(path, destination, expected_sha256=""):
    validation = validate_backup_archive(path, expected_sha256=expected_sha256)
    if not validation.get("restore_supported"):
        raise ValueError(validation.get("details") or "Archive is not restorable.")
    os.makedirs(destination, exist_ok=False)
    destination = os.path.abspath(destination)
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or not _safe_archive_name(member.name):
                raise ValueError("Archive changed after validation.")
            target = os.path.abspath(os.path.join(destination, *PurePosixPath(member.name).parts))
            if os.path.commonpath([destination, target]) != destination:
                raise ValueError("Archive path escaped the restore staging directory.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Unable to read archive member: {member.name}")
            with source, open(target, "wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return validation


def _postgres_environment():
    database = settings.DATABASES["default"]
    environment = os.environ.copy()
    if database.get("PASSWORD"):
        environment["PGPASSWORD"] = str(database["PASSWORD"])
    return environment


def restore_database_payload(staging_directory, manifest):
    """Replace the configured database from a validated v2 Full Backup payload."""
    database = settings.DATABASES["default"]
    connections.close_all()
    if manifest["database_format"] == "postgresql_custom":
        payload_path = os.path.join(staging_directory, "database", "postgresql.dump")
        command = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "--single-transaction",
            "--dbname",
            str(database["NAME"]),
        ]
        if database.get("HOST"):
            command.extend(["--host", str(database["HOST"])])
        if database.get("PORT"):
            command.extend(["--port", str(database["PORT"])])
        if database.get("USER"):
            command.extend(["--username", str(database["USER"])])
        command.append(payload_path)
        subprocess.run(
            command,
            check=True,
            env=_postgres_environment(),
            capture_output=True,
            text=True,
            timeout=1800,
        )
    elif manifest["database_format"] == "sqlite3":
        payload_path = os.path.join(staging_directory, "database", "db.sqlite3")
        database_path = os.path.abspath(str(database["NAME"]))
        replacement = database_path + ".restore-new"
        shutil.copy2(payload_path, replacement)
        os.replace(replacement, database_path)
    else:
        raise ValueError("Unsupported database restore payload format.")
    connections.close_all()
    call_command("migrate", interactive=False, verbosity=0)


def replace_directory_from_staging(staging_source, live_destination):
    """Replace a live directory only after a complete staging copy exists."""
    if not os.path.isdir(staging_source):
        return False
    live_destination = os.path.abspath(live_destination)
    parent = os.path.dirname(live_destination)
    os.makedirs(parent, exist_ok=True)
    replacement = tempfile.mkdtemp(prefix=".restore-new-", dir=parent)
    shutil.rmtree(replacement)
    shutil.copytree(staging_source, replacement)
    old_destination = live_destination + ".restore-old"
    if os.path.exists(old_destination):
        shutil.rmtree(old_destination)
    if os.path.exists(live_destination):
        os.replace(live_destination, old_destination)
    os.replace(replacement, live_destination)
    if os.path.exists(old_destination):
        shutil.rmtree(old_destination)
    return True


def restore_non_database_payloads(staging_directory, manifest):
    if manifest.get("includes_media"):
        replace_directory_from_staging(
            os.path.join(staging_directory, "media"),
            str(settings.MEDIA_ROOT),
        )
    if manifest.get("includes_chatbot"):
        chatbot_source = os.path.join(staging_directory, "chatbot", "chatbot.db")
        chatbot_destination = os.path.abspath(
            os.environ.get("CHATBOT_DB_PATH", "/var/lib/ticketsolve-chatbot/chatbot.db")
        )
        if os.path.isfile(chatbot_source):
            os.makedirs(os.path.dirname(chatbot_destination), exist_ok=True)
            replacement = chatbot_destination + ".restore-new"
            shutil.copy2(chatbot_source, replacement)
            os.replace(replacement, chatbot_destination)
