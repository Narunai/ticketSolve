from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
import calendar
import datetime
import os
import uuid
from zoneinfo import ZoneInfo
from .security import EncryptedCharField

class Company(models.Model):
    name = models.CharField(max_length=255, unique=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subsidiaries'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent:
            if self.pk and self.parent_id == self.pk:
                raise ValidationError({'parent': "A company cannot set itself as its own parent."})
            
            # Check for circular reference
            curr = self.parent
            while curr:
                if self.pk and curr.pk == self.pk:
                    raise ValidationError({'parent': "Cannot select a child or grandchild of this company as its parent (circular loop detected)."})
                curr = curr.parent

    def get_all_subsidiary_ids(self):
        """
        Returns a list of IDs including self and all recursive descendants.
        """
        ids = [self.id]
        for child in self.subsidiaries.all():
            ids.extend(child.get_all_subsidiary_ids())
        return ids

    def get_all_subsidiaries(self):
        """
        Returns a list of Company objects including self and all recursive descendants.
        """
        companies = [self]
        for child in self.subsidiaries.all():
            companies.extend(child.get_all_subsidiaries())
        return companies

    def get_parents(self):
        """
        Returns a list of parent companies from immediate parent up to root parent.
        """
        parents = []
        curr = self.parent
        while curr:
            parents.append(curr)
            curr = curr.parent
        return parents

    def get_depth(self):
        """
        Returns depth level in the hierarchy (0 for root parent).
        """
        return len(self.get_parents())

    def get_full_path(self):
        """
        Returns full hierarchy string, e.g. "Parent Corp > Branch A > Unit 1".
        """
        ancestors = self.get_parents()
        ancestors.reverse()
        names = [p.name for p in ancestors] + [self.name]
        return " > ".join(names)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    SYSTEM_ADMIN = 'SYSTEM_ADMIN'
    SYSTEM_SUB_ADMIN = 'SYSTEM_SUB_ADMIN'
    CLIENT_ADMIN = 'CLIENT_ADMIN'
    CLIENT_STAFF = 'CLIENT_STAFF'
    CLIENT_USER = 'CLIENT_USER'

    ROLE_CHOICES = [
        (SYSTEM_ADMIN, 'System Administrator'),
        (SYSTEM_SUB_ADMIN, 'System Sub-Administrator'),
        (CLIENT_ADMIN, 'Client Administrator'),
        (CLIENT_STAFF, 'Client Staff'),
        (CLIENT_USER, 'Client User'),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=CLIENT_USER
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users'
    )
    simple_password_enabled = models.BooleanField(
        default=False,
        help_text='Allows this user to set a persistent password with a minimum length of 6 characters.',
    )
    simple_password_approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='simple_password_approvals',
    )
    simple_password_approved_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get_system_admins_qs(cls):
        """Returns queryset of all active System Admins, Sub-Admins, and Superusers."""
        return cls.objects.filter(
            models.Q(role__in=[cls.SYSTEM_ADMIN, cls.SYSTEM_SUB_ADMIN]) |
            models.Q(is_superuser=True) |
            models.Q(is_staff=True, company__isnull=True),
            is_active=True
        )

    def save(self, *args, **kwargs):
        if self.is_superuser and self.role == self.CLIENT_USER:
            self.role = self.SYSTEM_ADMIN
        super().save(*args, **kwargs)

    @property
    def effective_role_display(self):
        """Return the security-effective role for account identity displays.

        Legacy superusers can have CLIENT_USER stored in ``role``. Their
        effective privileges still come from ``is_superuser``, so presenting
        them as a Client User is misleading even though authorization remains
        correct.
        """
        if self.is_superuser:
            return dict(self.ROLE_CHOICES)[self.SYSTEM_ADMIN]
        return self.get_role_display()

    def __str__(self):
        role_display = self.effective_role_display
        company_name = self.company.name if self.company else "No Company"
        return f"{self.username} ({role_display} - {company_name})"

class TicketCategory(models.Model):
    name = models.CharField(max_length=100)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ticket_categories'
    )
    description = models.TextField(blank=True)
    icon_code = models.CharField(max_length=50, default='folder', blank=True)
    color_code = models.CharField(max_length=20, default='#6366f1', blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company', 'name']
        verbose_name_plural = 'Ticket Categories'

    def __str__(self):
        comp = self.company.name if self.company else 'Global (All Companies)'
        return f"{self.name} [{comp}]"


class ResolutionCategory(models.Model):
    name = models.CharField(max_length=100)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='resolution_categories'
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company', 'name']

    def __str__(self):
        comp = self.company.name if self.company else 'Global (All Companies)'
        return f"{self.name} [{comp}]"


class ModuleCategory(models.Model):
    name = models.CharField(max_length=100)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='module_categories'
    )
    description = models.TextField(blank=True)
    icon_code = models.CharField(max_length=50, default='cpu', blank=True)
    color_code = models.CharField(max_length=20, default='#10b981', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company', 'name']
        verbose_name_plural = 'Module Categories'

    def __str__(self):
        comp = self.company.name if self.company else 'Global (All Companies)'
        return f"{self.name} [{comp}]"



class TicketStatusConfig(models.Model):
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    color_badge_class = models.CharField(max_length=100, default='bg-slate-500/10 text-slate-400 border-slate-500/20')
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='status_configs'
    )
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        comp = self.company.name if self.company else 'Global'
        return f"{self.name} ({self.code}) [{comp}]"


class CompanyTicketConfig(models.Model):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='ticket_config'
    )
    ticket_prefix = models.CharField(max_length=10, blank=True, default='', help_text='e.g. ACME-, SEC-')
    require_resolution_note = models.BooleanField(default=True, help_text='Require resolution note when resolving/closing ticket.')
    custom_help_text = models.TextField(blank=True, default='', help_text='Help text guidelines displayed at the top of the ticket creation form.')
    allow_file_attachments = models.BooleanField(default=True)

    def __str__(self):
        return f"Ticket Config - {self.company.name}"


class CompanyTicketField(models.Model):
    FIELD_TYPE_TEXT = 'TEXT'
    FIELD_TYPE_TEXTAREA = 'TEXTAREA'
    FIELD_TYPE_NUMBER = 'NUMBER'
    FIELD_TYPE_SELECT = 'SELECT'
    FIELD_TYPE_DATE = 'DATE'
    FIELD_TYPE_BOOLEAN = 'BOOLEAN'

    FIELD_TYPE_CHOICES = [
        (FIELD_TYPE_TEXT, 'Text Input (Single Line)'),
        (FIELD_TYPE_TEXTAREA, 'Text Area (Multi Line)'),
        (FIELD_TYPE_NUMBER, 'Number'),
        (FIELD_TYPE_SELECT, 'Dropdown Select'),
        (FIELD_TYPE_DATE, 'Date Picker'),
        (FIELD_TYPE_BOOLEAN, 'Checkbox (Yes/No)'),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='ticket_fields'
    )
    field_key = models.CharField(max_length=50)
    label = models.CharField(max_length=150)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPE_CHOICES, default=FIELD_TYPE_TEXT)
    placeholder = models.CharField(max_length=255, blank=True, default='')
    is_required = models.BooleanField(default=True)
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True, help_text='Dropdown choices options list')
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        unique_together = ['company', 'field_key']

    def __str__(self):
        return f"{self.company.name} - {self.label} ({self.field_key})"

    @classmethod
    def ensure_default_fields(cls, company):
        if not company:
            return
        defaults = [
            {'field_key': 'title', 'label': 'Title', 'field_type': cls.FIELD_TYPE_TEXT, 'placeholder': 'Enter ticket title...', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 10},
            {'field_key': 'description', 'label': 'Description', 'field_type': cls.FIELD_TYPE_TEXTAREA, 'placeholder': 'Describe issue details (optional)...', 'is_required': False, 'is_visible': True, 'is_custom': False, 'order': 20},
            {'field_key': 'priority', 'label': 'Priority', 'field_type': cls.FIELD_TYPE_SELECT, 'placeholder': '', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 30},
            {'field_key': 'ticket_category', 'label': 'Category', 'field_type': cls.FIELD_TYPE_SELECT, 'placeholder': '', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 40},
            {'field_key': 'module_category', 'label': 'Module Category', 'field_type': cls.FIELD_TYPE_SELECT, 'placeholder': '', 'is_required': False, 'is_visible': True, 'is_custom': False, 'order': 45},
            {'field_key': 'attachment', 'label': 'Attachments', 'field_type': cls.FIELD_TYPE_TEXT, 'placeholder': '', 'is_required': False, 'is_visible': True, 'is_custom': False, 'order': 50},
        ]
        for d in defaults:
            cls.objects.get_or_create(
                company=company,
                field_key=d['field_key'],
                defaults=d
            )
        # Update description requirement for existing records
        cls.objects.filter(company=company, field_key='description', is_custom=False).update(is_required=False)




class TicketAutomationConfig(models.Model):
    """Company rule for automatically moving stale OPEN tickets to IN_PROGRESS."""

    UNIT_MINUTES = 'MINUTES'
    UNIT_HOURS = 'HOURS'
    UNIT_DAYS = 'DAYS'
    UNIT_CHOICES = [
        (UNIT_MINUTES, 'Minutes'),
        (UNIT_HOURS, 'Hours'),
        (UNIT_DAYS, 'Days'),
    ]

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='ticket_automation_config',
        verbose_name='Company',
    )
    open_age_value = models.PositiveIntegerField(default=24, verbose_name='Duration')
    open_age_unit = models.CharField(
        max_length=10,
        choices=UNIT_CHOICES,
        default=UNIT_HOURS,
        verbose_name='Unit',
    )
    is_active = models.BooleanField(default=True, verbose_name='Active')
    apply_to_subsidiaries = models.BooleanField(default=True, verbose_name='Apply to Subsidiaries')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ticket_automation_configs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['company__name']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.open_age_value < 1:
            raise ValidationError({'open_age_value': 'Duration must be greater than or equal to 1.'})

    def threshold_delta(self):
        if self.open_age_unit == self.UNIT_MINUTES:
            return datetime.timedelta(minutes=self.open_age_value)
        if self.open_age_unit == self.UNIT_DAYS:
            return datetime.timedelta(days=self.open_age_value)
        return datetime.timedelta(hours=self.open_age_value)

    @classmethod
    def resolve_for_company(cls, company):
        """Return the nearest applicable rule; a local disabled rule is an opt-out."""
        if not company:
            return None
        local_rule = cls.objects.filter(company=company).first()
        if local_rule:
            return local_rule if local_rule.is_active else None
        for parent in company.get_parents():
            parent_rule = cls.objects.filter(company=parent).first()
            if parent_rule:
                if parent_rule.is_active and parent_rule.apply_to_subsidiaries:
                    return parent_rule
                return None
        return None

    def __str__(self):
        return f"{self.company.name}: OPEN {self.open_age_value} {self.get_open_age_unit_display()} -> IN_PROGRESS"


class Ticket(models.Model):
    STATUS_OPEN = 'OPEN'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_DEPLOYMENT_REQUESTED = 'DEPLOYMENT_REQUESTED'
    STATUS_READY_TO_DEPLOY = 'READY_TO_DEPLOY'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_CLOSED = 'CLOSED'

    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_DEPLOYMENT_REQUESTED, 'Production Deployment Request'),
        (STATUS_READY_TO_DEPLOY, 'Ready to Deploy'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_CLOSED, 'Closed'),
    ]



    PRIORITY_LOW = 'LOW'
    PRIORITY_MEDIUM = 'MEDIUM'
    PRIORITY_HIGH = 'HIGH'

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
    ]

    CATEGORY_HARDWARE = 'HARDWARE'
    CATEGORY_SOFTWARE = 'SOFTWARE'
    CATEGORY_NETWORK = 'NETWORK'
    CATEGORY_ACCOUNT = 'ACCOUNT'
    CATEGORY_OTHER = 'OTHER'

    CATEGORY_CHOICES = [
        (CATEGORY_HARDWARE, 'Hardware'),
        (CATEGORY_SOFTWARE, 'Software'),
        (CATEGORY_NETWORK, 'Network / Internet'),
        (CATEGORY_ACCOUNT, 'Account / Login'),
        (CATEGORY_OTHER, 'Other'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM
    )
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_OTHER
    )
    ticket_category = models.ForeignKey(
        TicketCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets'
    )
    module_category = models.ForeignKey(
        ModuleCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets'
    )
    resolution_category = models.ForeignKey(
        ResolutionCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_tickets'
    )
    resolution_notes = models.TextField(blank=True)
    custom_fields_data = models.JSONField(default=dict, blank=True)

    attachment = models.FileField(
        upload_to='ticket_attachments/',
        null=True,
        blank=True
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='tickets'
    )
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='created_tickets'
    )
    assigned_to = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tickets'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status_changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    def get_ticket_code(self):
        if hasattr(self.company, 'ticket_config') and self.company.ticket_config.ticket_prefix:
            return f"{self.company.ticket_config.ticket_prefix}{self.id:04d}"
        return f"#{self.id}"

    def get_category_name(self):
        if self.ticket_category:
            return self.ticket_category.name
        return self.get_category_display()

class BackupLog(models.Model):
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    TYPE_FULL = 'FULL'
    TYPE_INCREMENTAL = 'INCREMENTAL'
    TYPE_SYSTEM = 'SYSTEM'
    TYPE_CHOICES = [
        (TYPE_FULL, 'Full Backup'),
        (TYPE_INCREMENTAL, 'Incremental Backup'),
        (TYPE_SYSTEM, 'System Data (No Tickets)'),
    ]

    SOURCE_GENERATED = 'GENERATED'
    SOURCE_IMPORTED = 'IMPORTED'
    SOURCE_CHOICES = [
        (SOURCE_GENERATED, 'Generated by TicketSolve'),
        (SOURCE_IMPORTED, 'Imported archive'),
    ]

    VALIDATION_UNCHECKED = 'UNCHECKED'
    VALIDATION_VALID = 'VALID'
    VALIDATION_INVALID = 'INVALID'
    VALIDATION_LEGACY = 'LEGACY'
    VALIDATION_CHOICES = [
        (VALIDATION_UNCHECKED, 'Not validated'),
        (VALIDATION_VALID, 'Validated'),
        (VALIDATION_INVALID, 'Invalid'),
        (VALIDATION_LEGACY, 'Legacy archive'),
    ]

    filename = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255, blank=True, default='')
    file_size_bytes = models.BigIntegerField(default=0)
    backup_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_FULL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_GENERATED,
    )
    sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True)
    format_version = models.CharField(max_length=20, blank=True, default='')
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_CHOICES,
        default=VALIDATION_UNCHECKED,
    )
    validation_details = models.CharField(max_length=1000, blank=True, default='')
    restore_supported = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_backup_archives',
    )
    is_protected = models.BooleanField(
        default=False,
        help_text='Protected rollback archives are excluded from routine retention cleanup.',
    )
    details = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.get_backup_type_display()} - {self.status}) - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def file_size_mb(self):
        return round(self.file_size_bytes / (1024 * 1024), 2)


class BackupSchedule(models.Model):
    """Singleton schedule for automatic backups.

    The choices intentionally enforce conservative minimum intervals. The
    systemd timer may check every minute, but a backup only runs when this
    schedule is due. Failed jobs use a fixed retry delay to avoid log and disk
    pressure during an outage.
    """

    INCREMENTAL_INTERVAL_CHOICES = [
        (60, 'Every 1 hour'),
        (120, 'Every 2 hours'),
        (240, 'Every 4 hours'),
        (360, 'Every 6 hours'),
        (720, 'Every 12 hours'),
        (1440, 'Every 1 day'),
    ]
    ARCHIVE_INTERVAL_CHOICES = [
        (1440, 'Every 1 day'),
        (4320, 'Every 3 days'),
        (10080, 'Every 7 days'),
        (20160, 'Every 14 days'),
        (43200, 'Every 30 days'),
    ]
    FAILURE_RETRY_MINUTES = 30

    singleton_key = models.BooleanField(default=True, unique=True, editable=False)
    incremental_is_active = models.BooleanField(default=True)
    incremental_interval_minutes = models.PositiveIntegerField(
        choices=INCREMENTAL_INTERVAL_CHOICES,
        default=120,
    )
    full_is_active = models.BooleanField(default=True)
    full_interval_minutes = models.PositiveIntegerField(
        choices=ARCHIVE_INTERVAL_CHOICES,
        default=1440,
    )
    system_is_active = models.BooleanField(default=True)
    system_interval_minutes = models.PositiveIntegerField(
        choices=ARCHIVE_INTERVAL_CHOICES,
        default=10080,
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_backup_schedules',
    )

    @classmethod
    def get_solo(cls):
        schedule, _ = cls.objects.get_or_create(singleton_key=True)
        return schedule

    def save(self, *args, **kwargs):
        self.singleton_key = True
        super().save(*args, **kwargs)

    def settings_for(self, backup_type):
        mapping = {
            BackupLog.TYPE_INCREMENTAL: (
                self.incremental_is_active,
                self.incremental_interval_minutes,
                self.get_incremental_interval_minutes_display(),
            ),
            BackupLog.TYPE_FULL: (
                self.full_is_active,
                self.full_interval_minutes,
                self.get_full_interval_minutes_display(),
            ),
            BackupLog.TYPE_SYSTEM: (
                self.system_is_active,
                self.system_interval_minutes,
                self.get_system_interval_minutes_display(),
            ),
        }
        if backup_type not in mapping:
            raise ValueError(f'Unsupported backup type: {backup_type}')
        return mapping[backup_type]

    def next_run_at(self, backup_type, at=None):
        is_active, interval_minutes, _ = self.settings_for(backup_type)
        if not is_active:
            return None

        at = at or timezone.now()
        latest_success = BackupLog.objects.filter(
            backup_type=backup_type,
            status=BackupLog.STATUS_SUCCESS,
        ).first()
        candidate = at
        if latest_success:
            candidate = latest_success.created_at + datetime.timedelta(
                minutes=interval_minutes,
            )

        latest_failure = BackupLog.objects.filter(
            backup_type=backup_type,
            status=BackupLog.STATUS_FAILED,
        ).first()
        if latest_failure and (
            not latest_success or latest_failure.created_at > latest_success.created_at
        ):
            candidate = max(
                candidate,
                latest_failure.created_at + datetime.timedelta(
                    minutes=self.FAILURE_RETRY_MINUTES,
                ),
            )
        return max(candidate, at)

    def is_due(self, backup_type, at=None):
        at = at or timezone.now()
        next_run = self.next_run_at(backup_type, at=at)
        return bool(next_run and next_run <= at)

    def __str__(self):
        return 'Automatic backup schedule'


class MaintenanceSetting(models.Model):
    """Singleton configuration for scheduled and restore maintenance gates."""

    SESSION_MINUTE_CHOICES = [
        (30, '30 minutes'),
        (60, '1 hour'),
        (120, '2 hours'),
        (240, '4 hours'),
    ]

    singleton_key = models.BooleanField(default=True, unique=True, editable=False)
    is_enabled = models.BooleanField(default=False)
    title = models.CharField(max_length=160, default='Scheduled maintenance')
    message = models.TextField(
        blank=True,
        default='TicketSolve is temporarily unavailable while scheduled maintenance is completed.',
    )
    scheduled_start = models.DateTimeField(null=True, blank=True)
    expected_end = models.DateTimeField(null=True, blank=True)
    allow_test_access = models.BooleanField(default=True)
    access_code_hash = models.CharField(max_length=255, blank=True, default='')
    access_version = models.PositiveIntegerField(default=1)
    access_session_minutes = models.PositiveIntegerField(
        choices=SESSION_MINUTE_CHOICES,
        default=120,
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_maintenance_settings',
    )

    @classmethod
    def get_solo(cls):
        setting, _ = cls.objects.get_or_create(singleton_key=True)
        return setting

    def save(self, *args, **kwargs):
        self.singleton_key = True
        super().save(*args, **kwargs)

    def is_active(self, at=None):
        at = at or timezone.now()
        return bool(
            self.is_enabled
            and (self.scheduled_start is None or self.scheduled_start <= at)
        )

    def is_scheduled(self, at=None):
        at = at or timezone.now()
        return bool(
            self.is_enabled
            and self.scheduled_start
            and self.scheduled_start > at
        )

    @property
    def has_access_code(self):
        return bool(
            self.access_code_hash
            or getattr(settings, 'MAINTENANCE_PERMANENT_ACCESS_CODE_HASH', '')
        )

    def __str__(self):
        return 'System maintenance configuration'


class BackupUploadSession(models.Model):
    STATUS_UPLOADING = 'UPLOADING'
    STATUS_VALIDATING = 'VALIDATING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_CHOICES = [
        (STATUS_UPLOADING, 'Uploading'),
        (STATUS_VALIDATING, 'Validating'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    upload_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='backup_upload_sessions',
    )
    original_filename = models.CharField(max_length=255)
    temp_filename = models.CharField(max_length=255, unique=True)
    expected_size = models.BigIntegerField()
    received_size = models.BigIntegerField(default=0)
    next_chunk_index = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UPLOADING,
    )
    error_message = models.CharField(max_length=1000, blank=True, default='')
    backup_log = models.ForeignKey(
        BackupLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='upload_sessions',
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class RestoreJob(models.Model):
    STATUS_QUEUED = 'QUEUED'
    STATUS_VALIDATING = 'VALIDATING'
    STATUS_PRE_BACKUP = 'PRE_BACKUP'
    STATUS_RESTORING = 'RESTORING'
    STATUS_VERIFYING = 'VERIFYING'
    STATUS_AWAITING_REVIEW = 'AWAITING_REVIEW'
    STATUS_SUCCEEDED = 'SUCCEEDED'
    STATUS_FAILED = 'FAILED'
    STATUS_ROLLED_BACK = 'ROLLED_BACK'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_VALIDATING, 'Validating'),
        (STATUS_PRE_BACKUP, 'Creating rollback backup'),
        (STATUS_RESTORING, 'Restoring'),
        (STATUS_VERIFYING, 'Verifying'),
        (STATUS_AWAITING_REVIEW, 'Awaiting administrator review'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_ROLLED_BACK, 'Rolled back'),
    ]

    job_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    backup = models.ForeignKey(
        BackupLog,
        on_delete=models.PROTECT,
        related_name='restore_jobs',
    )
    rollback_backup = models.ForeignKey(
        BackupLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rollback_restore_jobs',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_restore_jobs',
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    details = models.TextField(blank=True, default='')
    external_log_path = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.job_id} - {self.status}'



class EmailLog(models.Model):
    RECIPIENT_TO = 'TO'
    RECIPIENT_CC = 'CC'
    RECIPIENT_TYPE_CHOICES = [
        (RECIPIENT_TO, 'Primary (To)'),
        (RECIPIENT_CC, 'CC'),
    ]

    ACTION_TICKET_CREATED = 'TICKET_CREATED'
    ACTION_TICKET_UPDATED = 'TICKET_UPDATED'
    ACTION_WELCOME_USER = 'WELCOME_USER'
    ACTION_COMPANY_REGISTERED = 'COMPANY_REGISTERED'
    ACTION_MONTHLY_REPORT = 'MONTHLY_REPORT'
    ACTION_COMMENT_ADDED = 'COMMENT_ADDED'
    ACTION_MAINTENANCE = 'MAINTENANCE'

    ACTION_CHOICES = [
        (ACTION_TICKET_CREATED, 'New Ticket Created'),
        (ACTION_TICKET_UPDATED, 'Ticket Updated'),
        (ACTION_WELCOME_USER, 'Welcome New User'),
        (ACTION_COMPANY_REGISTERED, 'Company Registered'),
        (ACTION_MONTHLY_REPORT, 'Monthly Report Dispatched'),
        (ACTION_COMMENT_ADDED, 'New Comment Added'),
        (ACTION_MAINTENANCE, 'System Maintenance Notice'),
    ]

    ticket = models.ForeignKey(
        'Ticket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_logs'
    )
    recipient = models.CharField(max_length=255)
    recipient_type = models.CharField(
        max_length=2,
        choices=RECIPIENT_TYPE_CHOICES,
        default=RECIPIENT_TO,
    )
    delivery_group = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Recipient mapping ID for single email batch',
    )
    subject = models.CharField(max_length=255)
    message = models.TextField()
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, default='')


    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"Email to {self.recipient} - {self.subject} ({self.sent_at.strftime('%Y-%m-%d %H:%M')})"

class TicketAuditLog(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    actor = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='action_audit_logs'
    )
    old_status = models.CharField(max_length=20, choices=Ticket.STATUS_CHOICES, null=True, blank=True)
    new_status = models.CharField(max_length=20, choices=Ticket.STATUS_CHOICES, null=True, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def get_related_email_logs(self):
        """
        Return EmailLog objects created around the same time (+/- 15 seconds) for the same ticket.
        """
        from datetime import timedelta
        start = self.created_at - timedelta(seconds=15)
        end = self.created_at + timedelta(seconds=15)
        return EmailLog.objects.filter(
            sent_at__range=(start, end),
            subject__icontains=f"Ticket #{self.ticket_id}"
        )

    def __str__(self):
        actor_name = self.actor.username if self.actor else "System"
        return f"Ticket #{self.ticket.id} modified by {actor_name}: {self.old_status} -> {self.new_status}"


class AuthenticationThrottle(models.Model):
    key_hash = models.CharField(max_length=64, unique=True)
    failed_count = models.PositiveSmallIntegerField(default=0)
    window_started = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']


class SecurityAuditLog(models.Model):
    OUTCOME_SUCCESS = 'SUCCESS'
    OUTCOME_FAILURE = 'FAILURE'
    OUTCOME_BLOCKED = 'BLOCKED'
    OUTCOME_CHOICES = [
        (OUTCOME_SUCCESS, 'Success'),
        (OUTCOME_FAILURE, 'Failure'),
        (OUTCOME_BLOCKED, 'Blocked'),
    ]

    event_type = models.CharField(max_length=50, db_index=True)
    actor = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_audit_logs',
    )
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, db_index=True)
    subject_hash = models.CharField(max_length=64, blank=True, default='')
    ip_hash = models.CharField(max_length=64, blank=True, default='')
    target_type = models.CharField(max_length=50, blank=True, default='')
    target_id = models.CharField(max_length=100, blank=True, default='')
    details = models.CharField(max_length=1000, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['event_type', '-created_at'], name='security_event_time_idx')]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.event_type} {self.outcome}"



class TicketComment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    author = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='ticket_comments'
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on Ticket #{self.ticket.id}"


class InAppNotification(models.Model):
    EVENT_TICKET_CREATED = 'TICKET_CREATED'
    EVENT_STATUS_CHANGED = 'STATUS_CHANGED'
    EVENT_COMMENT_ADDED = 'COMMENT_ADDED'
    EVENT_MAINTENANCE = 'MAINTENANCE'
    EVENT_CHOICES = [
        (EVENT_TICKET_CREATED, 'Ticket created'),
        (EVENT_STATUS_CHANGED, 'Ticket status changed'),
        (EVENT_COMMENT_ADDED, 'Comment added'),
        (EVENT_MAINTENANCE, 'System maintenance'),
    ]

    recipient = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='in_app_notifications',
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='in_app_notifications',
    )
    actor = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_in_app_notifications',
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default='')
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='ticket_attachments/')
    filename = models.CharField(max_length=255, blank=True)
    file_size = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Attachment {self.filename or self.file.name} for Ticket #{self.ticket.id}"


class CommentAttachment(models.Model):
    comment = models.ForeignKey(
        TicketComment,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='comment_attachments/')
    filename = models.CharField(max_length=255, blank=True)
    file_size = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Attachment {self.filename or self.file.name} for Comment #{self.comment.id}"



class ReportViewLog(models.Model):
    viewer = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='report_views'
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='report_views',
        null=True,
        blank=True
    )
    viewed_at = models.DateTimeField(auto_now_add=True)
    report_month = models.CharField(max_length=50)

    class Meta:
        ordering = ['-viewed_at']

    def __str__(self):
        company_name = self.company.name if self.company else "System Wide"
        return f"{self.viewer.username} viewed report for {company_name} at {self.viewed_at.strftime('%Y-%m-%d %H:%M')}"


class MonthlyReportSchedule(models.Model):
    """A persisted monthly schedule for delivering the PDF ticket report."""

    TIMEZONE_BANGKOK = 'Asia/Bangkok'
    TIMEZONE_HONG_KONG = 'Asia/Hong_Kong'
    TIMEZONE_CHOICES = [
        (TIMEZONE_BANGKOK, 'Bangkok (UTC+7)'),
        (TIMEZONE_HONG_KONG, 'Hong Kong (UTC+8)'),
    ]

    name = models.CharField(max_length=150, verbose_name="Schedule Name")
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='monthly_report_schedules',
        null=True,
        blank=True,
        help_text="Leave blank to generate a global report across all companies",
    )
    recipients = models.ManyToManyField(
        CustomUser,
        related_name='monthly_report_schedules_as_recipient',
        verbose_name="Primary Recipients",
    )
    cc_recipients = models.ManyToManyField(
        CustomUser,
        blank=True,
        related_name='monthly_report_schedules_as_cc',
        verbose_name="CC Recipients",
    )
    smtp_configuration = models.ForeignKey(
        'SMTPConfiguration',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='monthly_report_schedules',
        verbose_name="Sender SMTP Account",
    )
    day_of_month = models.PositiveSmallIntegerField(
        default=31,
        verbose_name="Send Day of Month",
        help_text="If the month does not contain this day, the last day of the month will be used",
    )
    send_time = models.TimeField(default=datetime.time(17, 0), verbose_name="Send Time")
    timezone_name = models.CharField(
        max_length=50,
        choices=TIMEZONE_CHOICES,
        default=TIMEZONE_BANGKOK,
        verbose_name="Timezone",
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_monthly_report_schedules',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-is_active', 'day_of_month', 'send_time', 'name']

    def clean(self):
        from django.core.exceptions import ValidationError
        if not 1 <= self.day_of_month <= 31:
            raise ValidationError({'day_of_month': 'Send day of month must be between 1 and 31.'})

    def scheduled_datetime(self, year, month):
        """Return the configured run time, clipping day 29-31 to month end."""
        day = min(self.day_of_month, calendar.monthrange(year, month)[1])
        value = datetime.datetime.combine(datetime.date(year, month, day), self.send_time)
        return timezone.make_aware(value, ZoneInfo(self.timezone_name))

    def is_due(self, at=None):
        if not self.is_active:
            return False
        schedule_timezone = ZoneInfo(self.timezone_name)
        at = timezone.localtime(at or timezone.now(), schedule_timezone)
        scheduled = self.scheduled_datetime(at.year, at.month)
        created_at = timezone.localtime(self.created_at, schedule_timezone) if self.created_at else scheduled
        if scheduled < created_at or at < scheduled:
            return False
        if self.last_sent_at:
            last_sent = timezone.localtime(self.last_sent_at, schedule_timezone)
            if (last_sent.year, last_sent.month) == (at.year, at.month):
                return False
        return True

    def next_run_at(self, at=None):
        schedule_timezone = ZoneInfo(self.timezone_name)
        at = timezone.localtime(at or timezone.now(), schedule_timezone)
        candidate = self.scheduled_datetime(at.year, at.month)
        created_at = timezone.localtime(self.created_at, schedule_timezone) if self.created_at else at
        already_sent = False
        if self.last_sent_at:
            sent = timezone.localtime(self.last_sent_at, schedule_timezone)
            already_sent = (sent.year, sent.month) == (at.year, at.month)
        if candidate >= at and candidate >= created_at and not already_sent:
            return candidate
        if at.month == 12:
            return self.scheduled_datetime(at.year + 1, 1)
        return self.scheduled_datetime(at.year, at.month + 1)

    def next_run_display(self):
        return self.next_run_at().strftime('%d/%m/%Y %H:%M')

    def last_sent_display(self):
        if not self.last_sent_at:
            return ''
        local_value = timezone.localtime(self.last_sent_at, ZoneInfo(self.timezone_name))
        return local_value.strftime('%d/%m/%Y %H:%M')

    def __str__(self):
        return f"{self.name} - Day {self.day_of_month} at {self.send_time.strftime('%H:%M')} ({self.get_timezone_name_display()})"


class SMTPConfiguration(models.Model):
    FEATURE_OUTBOUND_EMAIL = 'OUTBOUND_EMAIL'
    FEATURE_EMAIL_TO_TICKET = 'EMAIL_TO_TICKET'
    FEATURE_BOTH = 'BOTH'
    FEATURE_SCOPE_CHOICES = [
        (FEATURE_OUTBOUND_EMAIL, 'Send system email'),
        (FEATURE_EMAIL_TO_TICKET, 'Email to Ticket import'),
        (FEATURE_BOTH, 'Send email and Email to Ticket'),
    ]

    PROVIDER_CHOICES = [
        ('GMAIL', 'Gmail SMTP'),
        ('MICROSOFT', 'Microsoft Outlook SMTP'),
        ('CUSTOM', 'Custom SMTP'),
        ('SIMULATION', 'Simulation / Console'),
    ]
    name = models.CharField(max_length=100, default='Default SMTP')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='SIMULATION')
    host = models.CharField(max_length=255, default='smtp.gmail.com')
    port = models.IntegerField(default=587)
    use_tls = models.BooleanField(default=True)
    username = models.CharField(max_length=255, blank=True)
    password = EncryptedCharField(max_length=512, blank=True)
    feature_scope = models.CharField(
        max_length=20,
        choices=FEATURE_SCOPE_CHOICES,
        default=FEATURE_OUTBOUND_EMAIL,
    )
    incoming_host = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='IMAP host, for example imap.gmail.com',
    )
    incoming_port = models.PositiveIntegerField(default=993)
    incoming_folder = models.CharField(max_length=255, default='INBOX')
    email_to_ticket_company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_to_ticket_smtp_configurations',
    )
    email_to_ticket_creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_to_ticket_creator_configurations',
    )
    email_to_ticket_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_to_ticket_assignee_configurations',
    )
    filter_issue_only = models.BooleanField(default=True)
    issue_keywords = models.TextField(
        blank=True,
        default='',
        max_length=4000,
        help_text='Optional comma-separated subject keywords',
    )
    ignore_keyword_filter_enabled = models.BooleanField(default=False)
    ignore_keywords = models.TextField(
        blank=True,
        default='',
        max_length=4000,
        help_text='Optional comma-separated subject keywords that must never create tickets',
    )
    mark_processed_as_read = models.BooleanField(default=True)
    max_emails_per_fetch = models.PositiveSmallIntegerField(default=30)
    fetch_days_back = models.PositiveSmallIntegerField(default=7)
    last_inbound_check_at = models.DateTimeField(null=True, blank=True)
    last_inbound_error = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=False)

    @property
    def uses_outbound_email(self):
        return self.feature_scope in {
            self.FEATURE_OUTBOUND_EMAIL,
            self.FEATURE_BOTH,
        }

    @property
    def uses_email_to_ticket(self):
        return self.feature_scope in {
            self.FEATURE_EMAIL_TO_TICKET,
            self.FEATURE_BOTH,
        }

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.uses_email_to_ticket:
            if self.provider == 'SIMULATION':
                errors['provider'] = 'Simulation provider cannot import email into tickets.'
            if not self.username:
                errors['username'] = 'Mailbox username is required for Email to Ticket.'
            if not self.password:
                errors['password'] = 'Mailbox password or app password is required for Email to Ticket.'
            if not self.incoming_host:
                errors['incoming_host'] = 'IMAP host is required for Email to Ticket.'
            if not self.email_to_ticket_company:
                errors['email_to_ticket_company'] = 'Target company is required for Email to Ticket.'
            if not self.email_to_ticket_creator:
                errors['email_to_ticket_creator'] = 'Ticket creator is required for Email to Ticket.'
            elif (
                self.email_to_ticket_company_id
                and self.email_to_ticket_creator.company_id != self.email_to_ticket_company_id
            ):
                errors['email_to_ticket_creator'] = 'Ticket creator must belong to the target company.'
            if (
                self.email_to_ticket_assignee_id
                and self.email_to_ticket_company_id
                and self.email_to_ticket_assignee.company_id != self.email_to_ticket_company_id
            ):
                errors['email_to_ticket_assignee'] = 'Assignee must belong to the target company.'
            if self.max_emails_per_fetch < 1 or self.max_emails_per_fetch > 100:
                errors['max_emails_per_fetch'] = 'Maximum emails per fetch must be between 1 and 100.'
            if self.fetch_days_back < 1 or self.fetch_days_back > 90:
                errors['fetch_days_back'] = 'Fetch days back must be between 1 and 90.'
            for field_name in ('issue_keywords', 'ignore_keywords'):
                keywords = [
                    item.strip()
                    for item in (getattr(self, field_name, '') or '').split(',')
                    if item.strip()
                ]
                if len(keywords) > 100:
                    errors[field_name] = 'A keyword list can contain at most 100 entries.'
                elif any(len(keyword) > 100 for keyword in keywords):
                    errors[field_name] = 'Each keyword must be 100 characters or fewer.'
            if self.ignore_keyword_filter_enabled and not self.ignore_keywords.strip():
                errors['ignore_keywords'] = (
                    'Add at least one ignore keyword before enabling this filter.'
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.is_active:
            from django.db.models import Q

            overlapping_scope = Q()
            if self.uses_outbound_email:
                overlapping_scope |= Q(
                    feature_scope__in=[
                        self.FEATURE_OUTBOUND_EMAIL,
                        self.FEATURE_BOTH,
                    ]
                )
            if self.uses_email_to_ticket:
                overlapping_scope |= Q(
                    feature_scope__in=[
                        self.FEATURE_EMAIL_TO_TICKET,
                        self.FEATURE_BOTH,
                    ]
                )
            if overlapping_scope:
                SMTPConfiguration.objects.filter(
                    overlapping_scope,
                ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.name} ({self.get_provider_display()} - "
            f"{self.get_feature_scope_display()} - {self.username}) "
            f"- Active: {self.is_active}"
        )


def get_smtp_connection():
    from django.core.mail.backends.smtp import EmailBackend
    config = SMTPConfiguration.objects.filter(
        is_active=True,
        feature_scope__in=[
            SMTPConfiguration.FEATURE_OUTBOUND_EMAIL,
            SMTPConfiguration.FEATURE_BOTH,
        ],
    ).first()
    if config and config.provider != 'SIMULATION':
        return EmailBackend(
            host=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            use_tls=config.use_tls,
            fail_silently=False
        )
    return None





def get_smtp_from_email(default_from_email):
    config = SMTPConfiguration.objects.filter(
        is_active=True,
        feature_scope__in=[
            SMTPConfiguration.FEATURE_OUTBOUND_EMAIL,
            SMTPConfiguration.FEATURE_BOTH,
        ],
    ).first()
    if config and config.username:
        return config.username
    return default_from_email


class InboundEmailReceipt(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_IMPORTED = 'IMPORTED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_SKIPPED = 'SKIPPED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending approval'),
        (STATUS_IMPORTED, 'Imported'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_SKIPPED, 'Skipped'),
        (STATUS_FAILED, 'Failed'),
    ]

    smtp_configuration = models.ForeignKey(
        SMTPConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbound_email_receipts',
    )
    message_id = models.CharField(max_length=512)
    sender_name = models.CharField(max_length=255, blank=True, default='')
    sender_email = models.EmailField(blank=True, default='')
    subject = models.CharField(max_length=255, blank=True, default='')
    body = models.TextField(blank=True, default='')
    matched_keywords = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    details = models.TextField(blank=True, default='')
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbound_email_receipts',
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decided_inbound_email_receipts',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-processed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['smtp_configuration', 'message_id'],
                name='unique_inbound_message_per_smtp_config',
            ),
        ]

    def __str__(self):
        return f"{self.subject or self.message_id} ({self.status})"


def inbound_email_attachment_upload_to(instance, filename):
    safe_name = os.path.basename(filename or 'email-attachment')[:255]
    return f'inbound_email_pending/{timezone.now():%Y/%m/%d}/{safe_name}'


class InboundEmailAttachment(models.Model):
    receipt = models.ForeignKey(
        InboundEmailReceipt,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    file = models.FileField(upload_to=inbound_email_attachment_upload_to)
    filename = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.filename


class InboundEmailContact(models.Model):
    smtp_configuration = models.ForeignKey(
        SMTPConfiguration,
        on_delete=models.CASCADE,
        related_name='inbound_email_contacts',
    )
    email = models.EmailField()
    display_name = models.CharField(max_length=255, blank=True, default='')
    message_count = models.PositiveIntegerField(default=1)
    last_subject = models.CharField(max_length=255, blank=True, default='')
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-last_seen_at', 'email']
        constraints = [
            models.UniqueConstraint(
                fields=['smtp_configuration', 'email'],
                name='unique_inbound_contact_per_smtp',
            ),
        ]
        indexes = [
            models.Index(fields=['email'], name='inbound_contact_email_idx'),
            models.Index(fields=['-last_seen_at'], name='inbound_contact_seen_idx'),
        ]

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.email


class InboundEmailRoutingRule(models.Model):
    smtp_configuration = models.ForeignKey(
        SMTPConfiguration,
        on_delete=models.CASCADE,
        related_name='inbound_routing_rules',
    )
    sender_email = models.EmailField()
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='inbound_email_routing_rules',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['smtp_configuration__name', 'sender_email']
        constraints = [
            models.UniqueConstraint(
                fields=['smtp_configuration', 'sender_email'],
                name='unique_sender_route_per_smtp',
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if (
            self.smtp_configuration_id
            and not self.smtp_configuration.uses_email_to_ticket
        ):
            errors['smtp_configuration'] = (
                'The SMTP configuration must support Email to Ticket.'
            )
        if not self.assignee_id:
            errors['assignee'] = 'An assignee is required for an active routing rule.'
        elif not self.assignee.company_id:
            errors['assignee'] = (
                'The assignee must belong to a company.'
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.sender_email = (self.sender_email or '').strip().casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sender_email} -> {self.assignee or 'Default assignee'}"


class EmailToTicketSchedule(models.Model):
    INTERVAL_10_MINUTES = 10
    INTERVAL_20_MINUTES = 20
    INTERVAL_30_MINUTES = 30
    INTERVAL_60_MINUTES = 60
    INTERVAL_CHOICES = [
        (INTERVAL_10_MINUTES, '10 minutes'),
        (INTERVAL_20_MINUTES, '20 minutes'),
        (INTERVAL_30_MINUTES, '30 minutes (half an hour)'),
        (INTERVAL_60_MINUTES, '1 hour'),
    ]

    singleton_key = models.BooleanField(default=True, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    interval_minutes = models.PositiveSmallIntegerField(
        choices=INTERVAL_CHOICES,
        default=INTERVAL_10_MINUTES,
    )
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_scheduled_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_email_to_ticket_schedules',
    )

    @classmethod
    def get_solo(cls):
        schedule, _ = cls.objects.get_or_create(singleton_key=True)
        return schedule

    def save(self, *args, **kwargs):
        self.singleton_key = True
        super().save(*args, **kwargs)

    def is_due(self, at=None):
        if not self.is_active:
            return False
        at = at or timezone.now()
        if not self.last_scheduled_run_at:
            return True
        return at >= self.last_scheduled_run_at + datetime.timedelta(
            minutes=self.interval_minutes,
        )

    def next_run_at(self, at=None):
        if not self.is_active:
            return None
        at = at or timezone.now()
        if not self.last_scheduled_run_at:
            return at
        candidate = self.last_scheduled_run_at + datetime.timedelta(
            minutes=self.interval_minutes,
        )
        return max(candidate, at)

    def __str__(self):
        return f"Email to Ticket every {self.interval_minutes} minutes"


class EmailToTicketRunLog(models.Model):
    TRIGGER_TIMER = 'TIMER'
    TRIGGER_MANUAL = 'MANUAL'
    TRIGGER_CHOICES = [
        (TRIGGER_TIMER, 'Timer'),
        (TRIGGER_MANUAL, 'Manual'),
    ]

    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_PARTIAL = 'PARTIAL'
    STATUS_SKIPPED = 'SKIPPED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_PARTIAL, 'Partial success'),
        (STATUS_SKIPPED, 'Skipped'),
        (STATUS_FAILED, 'Failed'),
    ]

    schedule = models.ForeignKey(
        EmailToTicketSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='run_logs',
    )
    trigger = models.CharField(max_length=10, choices=TRIGGER_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RUNNING,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_to_ticket_run_logs',
    )
    mailbox_count = models.PositiveIntegerField(default=0)
    found_count = models.PositiveIntegerField(default=0)
    pending_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    details = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at'], name='email_run_started_idx'),
            models.Index(fields=['status'], name='email_run_status_idx'),
        ]

    def __str__(self):
        return f"{self.get_trigger_display()} email import ({self.status}) at {self.started_at}"


class NotificationConfig(models.Model):
    STATUS_NOTIFY_ALL = 'ALL'
    STATUS_NOTIFY_IMPORTANT_ONLY = 'IMPORTANT_ONLY'
    STATUS_NOTIFY_CUSTOM = 'CUSTOM'
    STATUS_NOTIFY_NONE = 'NONE'

    STATUS_NOTIFY_CHOICES = [
        (STATUS_NOTIFY_ALL, 'All Statuses'),
        (STATUS_NOTIFY_IMPORTANT_ONLY, 'Important Statuses Only (Production Deployment Request, Ready to Deploy, Resolved, Closed)'),
        (STATUS_NOTIFY_CUSTOM, 'Custom Select Statuses'),
        (STATUS_NOTIFY_NONE, 'Disabled (None)'),
    ]


    name = models.CharField(max_length=255, default="Notification Configuration Rule")
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='notification_configs'
    )
    target_users = models.ManyToManyField(
        CustomUser,
        blank=True,
        related_name='notification_configs',
        help_text="If no user is specified, this rule applies to all members of the company."
    )
    notify_ticket_created = models.BooleanField(default=True, verbose_name="Notify on New Ticket Created")
    status_notification_mode = models.CharField(
        max_length=20,
        choices=STATUS_NOTIFY_CHOICES,
        default=STATUS_NOTIFY_ALL,
        verbose_name="Status Change Notification Mode"
    )
    allowed_statuses = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Notify on Selected Statuses"
    )
    notify_comments = models.BooleanField(default=True, verbose_name="Notify on Comments & Replies")
    apply_to_subsidiaries = models.BooleanField(
        default=True,
        verbose_name="Apply to All Subsidiaries"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.company.name}"


def should_send_email_notification(recipient_email, ticket=None, event_type=None, new_status=None, recipient_user=None):
    """
    Check if the recipient_email is allowed to receive notification emails based on notification_configs.
    """
    if not recipient_email:
        return False

    user = recipient_user
    if user is None:
        candidates = CustomUser.objects.filter(email=recipient_email)
        if ticket:
            participant_ids = [ticket.created_by_id, ticket.assigned_to_id]
            user = candidates.filter(id__in=[pk for pk in participant_ids if pk]).first()
            if user is None and ticket.company:
                company_ids = [ticket.company_id] + [company.id for company in ticket.company.get_parents()]
                user = candidates.filter(company_id__in=company_ids).first()
        if user is None:
            user = candidates.first()
    company = None
    if user and user.company:
        company = user.company
    elif ticket and ticket.company:
        company = ticket.company

    if not company:
        return True

    # 1. Look for user-specific config first
    configs = []
    if user:
        user_configs = NotificationConfig.objects.filter(
            target_users=user,
            company__in=company.get_parents() + [company]
        ).distinct()
        if user_configs.exists():
            configs = list(user_configs)

    # 2. If no user-specific config, look for company-level config (where target_users is empty)
    if not configs:
        comp_configs = NotificationConfig.objects.filter(
            company=company,
            target_users__isnull=True
        )
        if not comp_configs.exists():
            parent_ids = [p.id for p in company.get_parents()]
            comp_configs = NotificationConfig.objects.filter(
                company_id__in=parent_ids,
                apply_to_subsidiaries=True,
                target_users__isnull=True
            )
        configs = list(comp_configs)

    if not configs:
        return True

    config = configs[0]

    # Evaluate event_type
    if event_type == EmailLog.ACTION_TICKET_CREATED:
        return config.notify_ticket_created
    elif event_type == EmailLog.ACTION_COMMENT_ADDED:
        return config.notify_comments
    elif event_type == EmailLog.ACTION_TICKET_UPDATED:
        if config.status_notification_mode == NotificationConfig.STATUS_NOTIFY_NONE:
            return False
        elif config.status_notification_mode == NotificationConfig.STATUS_NOTIFY_ALL:
            return True
        elif config.status_notification_mode == NotificationConfig.STATUS_NOTIFY_CUSTOM:
            st = new_status or (ticket.status if ticket else None)
            return bool(st and st in (config.allowed_statuses or []))
        elif config.status_notification_mode == NotificationConfig.STATUS_NOTIFY_IMPORTANT_ONLY:
            important_statuses = [
                Ticket.STATUS_DEPLOYMENT_REQUESTED,
                Ticket.STATUS_READY_TO_DEPLOY,
                Ticket.STATUS_RESOLVED,
                Ticket.STATUS_CLOSED,
            ]
            if new_status and new_status in important_statuses:
                return True
            elif ticket and ticket.status in important_statuses:
                return True
            return False

    return True


def get_ticket_default_recipients(ticket, action_type=None):
    """
    Calculate default recipient metadata list for a ticket email notification.
    Returns list of dicts: [{'email': ..., 'name': ..., 'role': ..., 'is_checked': True, 'is_system': True}]
    """
    recipients = []
    seen = set()

    if not ticket:
        return recipients

    # 1. Creator / Reporter
    if ticket.created_by and ticket.created_by.email:
        email = ticket.created_by.email.strip()
        email_key = email.lower()
        if email_key not in seen:
            seen.add(email_key)
            recipients.append({
                'email': email,
                'name': ticket.created_by.username,
                'role': 'Reporter / Creator',
                'is_checked': True,
                'is_system': True,
            })

    # 2. Assignee
    if ticket.assigned_to and ticket.assigned_to.email:
        email = ticket.assigned_to.email.strip()
        email_key = email.lower()
        if email_key not in seen:
            seen.add(email_key)
            recipients.append({
                'email': email,
                'name': ticket.assigned_to.username,
                'role': 'Assignee',
                'is_checked': True,
                'is_system': True,
            })

    # 3. Original Email Sender (if created from email)
    raw_source = (ticket.custom_fields_data or {}).get('email_to_ticket') or {}
    if isinstance(raw_source, dict) and raw_source.get('sender_email'):
        sender_email = raw_source['sender_email'].strip()
        sender_name = raw_source.get('sender_name') or sender_email
        email_key = sender_email.lower()
        if email_key not in seen:
            seen.add(email_key)
            recipients.append({
                'email': sender_email,
                'name': sender_name,
                'role': 'Original Email Sender',
                'is_checked': True,
                'is_system': True,
            })

    # 4. NotificationConfig targets for company
    if ticket.company:
        configs = NotificationConfig.objects.filter(company=ticket.company)
        for cfg in configs:
            for u in cfg.target_users.filter(is_active=True):
                if u.email:
                    email = u.email.strip()
                    email_key = email.lower()
                    if email_key not in seen:
                        seen.add(email_key)
                        recipients.append({
                            'email': email,
                            'name': u.username,
                            'role': f'Notification Rule ({cfg.name})',
                            'is_checked': True,
                            'is_system': True,
                        })

    return recipients
