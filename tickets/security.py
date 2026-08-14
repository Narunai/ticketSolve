"""Security controls shared by authentication, uploads and secrets storage."""

import base64
import hashlib
import hmac
import io
import os
import zipfile
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme


ENCRYPTED_PREFIX = "enc:v1:"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".txt", ".csv", ".docx", ".xlsx", ".pptx",
}
MAINTENANCE_SESSION_KEY = "maintenance_access"


def _fernet_keys():
    keys = list(getattr(settings, "FIELD_ENCRYPTION_KEYS", []))
    if not keys:
        # Development/test convenience only. Production settings require an
        # independently generated key so rotating SECRET_KEY cannot destroy data.
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        keys = [base64.urlsafe_b64encode(digest).decode("ascii")]
    return keys


def encrypt_secret(value):
    if value in (None, "") or str(value).startswith(ENCRYPTED_PREFIX):
        return value
    token = Fernet(_fernet_keys()[0].encode("ascii")).encrypt(str(value).encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("ascii")


def decrypt_secret(value):
    if value in (None, "") or not str(value).startswith(ENCRYPTED_PREFIX):
        return value
    token = str(value)[len(ENCRYPTED_PREFIX):].encode("ascii")
    for key in _fernet_keys():
        try:
            return Fernet(key.encode("ascii")).decrypt(token).decode("utf-8")
        except InvalidToken:
            continue
    raise ValidationError("Encrypted value cannot be decrypted with the configured keys.")


class EncryptedCharField(models.CharField):
    """A CharField encrypted at rest, with transparent legacy plaintext reads."""

    description = "Fernet-encrypted character data"

    def from_db_value(self, value, expression, connection):
        return decrypt_secret(value)

    def to_python(self, value):
        return decrypt_secret(value)

    def get_prep_value(self, value):
        return encrypt_secret(super().get_prep_value(value))


def safe_redirect_target(request, candidate, fallback):
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _read_upload(upload):
    position = upload.tell() if hasattr(upload, "tell") else None
    data = upload.read(MAX_ATTACHMENT_BYTES + 1)
    if position is not None:
        upload.seek(position)
    return data


def validate_attachment(upload_or_bytes, filename=None):
    """Validate extension and file signature; return a user-safe error or None."""
    name = filename or getattr(upload_or_bytes, "name", "")
    safe_name = os.path.basename(str(name).replace("\\", "/"))
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        return f"File '{safe_name}' has a blocked or unsupported type."

    data = bytes(upload_or_bytes) if isinstance(upload_or_bytes, (bytes, bytearray)) else _read_upload(upload_or_bytes)
    if not data:
        return f"File '{safe_name}' is empty."
    if len(data) > MAX_ATTACHMENT_BYTES:
        return f"File '{safe_name}' exceeds 10 MB."

    valid = False
    if extension == ".pdf":
        valid = data.startswith(b"%PDF-")
    elif extension == ".png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension in {".jpg", ".jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    elif extension == ".gif":
        valid = data.startswith((b"GIF87a", b"GIF89a"))
    elif extension == ".webp":
        valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    elif extension in {".txt", ".csv"}:
        try:
            data.decode("utf-8-sig")
            valid = b"\x00" not in data
        except UnicodeDecodeError:
            valid = False
    else:
        expected = {".docx": "word/", ".xlsx": "xl/", ".pptx": "ppt/"}[extension]
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                total_uncompressed = sum(item.file_size for item in archive.infolist())
                valid = (
                    "[Content_Types].xml" in names
                    and any(item.startswith(expected) for item in names)
                    and total_uncompressed <= 100 * 1024 * 1024
                    and total_uncompressed <= max(len(data) * 100, 10 * 1024 * 1024)
                    and not any(item.lower().endswith("vbaproject.bin") for item in names)
                )
        except (zipfile.BadZipFile, OSError):
            valid = False

    if not valid:
        return f"File '{safe_name}' content does not match its allowed file type."
    return None


def client_ip(request):
    remote = request.META.get("REMOTE_ADDR", "")
    # Gunicorn is reachable only through the local Unix socket in production.
    # Trust the proxy-provided address only for that local/empty peer context.
    if not remote or remote in {"127.0.0.1", "::1"}:
        return request.META.get("HTTP_X_REAL_IP", remote)
    return remote


def _fingerprint(scope, value):
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, f"{scope}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def login_throttle_keys(request, username):
    normalized = (username or "").strip().casefold()
    ip = client_ip(request)
    return [_fingerprint("account", normalized), _fingerprint("ip", ip)]


def login_retry_after(request, username):
    from .models import AuthenticationThrottle
    now = timezone.now()
    rows = AuthenticationThrottle.objects.filter(
        key_hash__in=login_throttle_keys(request, username),
        locked_until__gt=now,
    )
    remaining = [int((row.locked_until - now).total_seconds()) + 1 for row in rows]
    return max(remaining, default=0)


def _uses_simple_password(username):
    from django.db.models import Q
    from .models import CustomUser
    value = (username or '').strip()
    return CustomUser.objects.filter(
        Q(username__iexact=value) | Q(email__iexact=value),
        simple_password_enabled=True,
        is_active=True,
    ).exists()


def record_login_failure(request, username):
    from .models import AuthenticationThrottle
    now = timezone.now()
    window_seconds = int(getattr(settings, "LOGIN_THROTTLE_WINDOW_SECONDS", 900))
    max_failures = int(getattr(settings, "LOGIN_THROTTLE_MAX_FAILURES", 5))
    lock_seconds = (
        int(getattr(settings, "SIMPLE_PASSWORD_LOCK_SECONDS", 600))
        if _uses_simple_password(username)
        else int(getattr(settings, "LOGIN_THROTTLE_LOCK_SECONDS", 900))
    )
    with transaction.atomic():
        for key_hash in login_throttle_keys(request, username):
            row, _ = AuthenticationThrottle.objects.select_for_update().get_or_create(key_hash=key_hash)
            if (now - row.window_started).total_seconds() > window_seconds:
                row.failed_count = 0
                row.window_started = now
                row.locked_until = None
            row.failed_count += 1
            if row.failed_count >= max_failures:
                row.locked_until = now + timezone.timedelta(seconds=lock_seconds)
            row.save()


def clear_login_failures(request, username):
    from .models import AuthenticationThrottle
    AuthenticationThrottle.objects.filter(key_hash__in=login_throttle_keys(request, username)).delete()


def clear_account_login_failures(*identifiers):
    """Clear only account-scoped counters without weakening the issuer's IP limit."""
    from .models import AuthenticationThrottle
    keys = [
        _fingerprint('account', (identifier or '').strip().casefold())
        for identifier in identifiers if identifier
    ]
    if keys:
        AuthenticationThrottle.objects.filter(key_hash__in=keys).delete()


def _maintenance_throttle_key(request, access_version):
    return _fingerprint(
        "maintenance-ip",
        f"{client_ip(request)}:{int(access_version)}",
    )


def maintenance_access_retry_after(request, access_version):
    from .models import AuthenticationThrottle
    now = timezone.now()
    row = AuthenticationThrottle.objects.filter(
        key_hash=_maintenance_throttle_key(request, access_version),
        locked_until__gt=now,
    ).first()
    if not row:
        return 0
    return max(1, int((row.locked_until - now).total_seconds()) + 1)


def record_maintenance_access_failure(request, access_version):
    from .models import AuthenticationThrottle
    now = timezone.now()
    window_seconds = int(
        getattr(settings, "MAINTENANCE_ACCESS_WINDOW_SECONDS", 600)
    )
    max_failures = int(
        getattr(settings, "MAINTENANCE_ACCESS_MAX_FAILURES", 5)
    )
    lock_seconds = int(
        getattr(settings, "MAINTENANCE_ACCESS_LOCK_SECONDS", 600)
    )
    key_hash = _maintenance_throttle_key(request, access_version)
    with transaction.atomic():
        row, _ = AuthenticationThrottle.objects.select_for_update().get_or_create(
            key_hash=key_hash
        )
        if (now - row.window_started).total_seconds() > window_seconds:
            row.failed_count = 0
            row.window_started = now
            row.locked_until = None
        row.failed_count += 1
        if row.failed_count >= max_failures:
            row.locked_until = now + timezone.timedelta(seconds=lock_seconds)
        row.save()


def clear_maintenance_access_failures(request, access_version):
    from .models import AuthenticationThrottle
    AuthenticationThrottle.objects.filter(
        key_hash=_maintenance_throttle_key(request, access_version)
    ).delete()


def maintenance_access_code_configured(maintenance_setting):
    return bool(
        maintenance_setting.access_code_hash
        or getattr(settings, 'MAINTENANCE_PERMANENT_ACCESS_CODE_HASH', '')
    )


def maintenance_access_code_matches(supplied_code, maintenance_setting):
    """Validate rotating and environment-managed maintenance codes safely."""
    if not supplied_code:
        return False
    encoded_candidates = list(dict.fromkeys(filter(None, [
        maintenance_setting.access_code_hash,
        getattr(settings, 'MAINTENANCE_PERMANENT_ACCESS_CODE_HASH', ''),
    ])))
    matched = False
    for encoded in encoded_candidates:
        # Evaluate every configured hash to avoid exposing which code matched.
        matched = check_password(supplied_code, encoded) or matched
    return matched


def grant_maintenance_access(request, maintenance_setting):
    expires_at = timezone.now() + timezone.timedelta(
        minutes=maintenance_setting.access_session_minutes
    )
    request.session[MAINTENANCE_SESSION_KEY] = {
        "version": maintenance_setting.access_version,
        "expires_at": int(expires_at.timestamp()),
    }
    request.session.cycle_key()


def has_maintenance_access(request, maintenance_setting):
    value = request.session.get(MAINTENANCE_SESSION_KEY)
    if not isinstance(value, dict):
        return False
    try:
        version_matches = int(value.get("version")) == maintenance_setting.access_version
        not_expired = int(value.get("expires_at")) > int(timezone.now().timestamp())
    except (TypeError, ValueError):
        return False
    if not (version_matches and not_expired):
        request.session.pop(MAINTENANCE_SESSION_KEY, None)
        return False
    return True


def write_security_audit(request, event_type, outcome, actor=None, target_type="", target_id="", details=""):
    from .models import SecurityAuditLog
    username = request.POST.get("username", "") if hasattr(request, "POST") else ""
    return SecurityAuditLog.objects.create(
        event_type=event_type,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        outcome=outcome,
        subject_hash=_fingerprint("subject", username) if username else "",
        ip_hash=_fingerprint("ip", client_ip(request)),
        target_type=target_type[:50],
        target_id=str(target_id)[:100],
        details=str(details)[:1000],
    )


def generate_simple_password(length=6):
    """Generate a numeric simple password for an explicitly approved user."""
    length = max(6, int(length))
    first = str(secrets.randbelow(9) + 1)
    return first + ''.join(str(secrets.randbelow(10)) for _ in range(length - 1))


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault(
            "Content-Security-Policy-Report-Only",
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com",
        )
        if getattr(request, "user", None) and request.user.is_authenticated and response.get("Content-Type", "").startswith("text/html"):
            response.setdefault("Cache-Control", "no-store, private")
        return response


class MaintenanceModeMiddleware:
    """Gate application traffic during scheduled maintenance and restores."""

    PUBLIC_PATHS = {
        "/maintenance/access/",
        "/health/",
        "/favicon.ico",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def _maintenance_response(self, request, setting=None, hard=False):
        response = render(
            request,
            "tickets/maintenance.html",
            {
                "maintenance": setting,
                "hard_maintenance": hard,
                "retry_after": 60,
            },
            status=503,
        )
        response["Retry-After"] = "60"
        response["Cache-Control"] = "no-store, max-age=0"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def __call__(self, request):
        restore_sentinel = os.path.abspath(
            getattr(
                settings,
                "RESTORE_SENTINEL_FILE",
                os.path.join(settings.BASE_DIR, ".restore", "restore-in-progress"),
            )
        )
        static_url = getattr(settings, "STATIC_URL", "/static/")
        public_path = (
            request.path in self.PUBLIC_PATHS
            or request.path.startswith(static_url)
            or request.path.startswith("/.well-known/acme-challenge/")
        )
        if os.path.isfile(restore_sentinel) and not public_path:
            request.maintenance_setting = None
            return self._maintenance_response(request, hard=True)

        try:
            from .models import MaintenanceSetting
            maintenance_setting = MaintenanceSetting.get_solo()
        except (OperationalError, ProgrammingError):
            maintenance_setting = None
        request.maintenance_setting = maintenance_setting

        if (
            maintenance_setting
            and maintenance_setting.is_active()
            and not public_path
            and not has_maintenance_access(request, maintenance_setting)
        ):
            return self._maintenance_response(request, setting=maintenance_setting)
        return self.get_response(request)
