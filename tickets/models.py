from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
import calendar
import datetime
from zoneinfo import ZoneInfo

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
                raise ValidationError({'parent': "บริษัทไม่สามารถตั้งค่าตัวเองเป็นบริษัทแม่ได้"})
            
            # Check for circular reference
            curr = self.parent
            while curr:
                if self.pk and curr.pk == self.pk:
                    raise ValidationError({'parent': "ไม่สามารถเลือกบริษัทลูกหรือหลานของบริษัทนี้มาเป็นบริษัทแม่ได้ (เกิดวงรอบวนลูป)"})
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
    CLIENT_USER = 'CLIENT_USER'

    ROLE_CHOICES = [
        (SYSTEM_ADMIN, 'System Administrator'),
        (SYSTEM_SUB_ADMIN, 'System Sub-Administrator'),
        (CLIENT_ADMIN, 'Client Administrator'),
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

    def __str__(self):
        role_display = self.get_role_display()
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
        comp = self.company.name if self.company else 'Global (ทุกบริษัท)'
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
        comp = self.company.name if self.company else 'Global (ทุกบริษัท)'
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
    ticket_prefix = models.CharField(max_length=10, blank=True, default='', help_text='เช่น ACME-, SEC-')
    require_resolution_note = models.BooleanField(default=True, help_text='บังคับใส่รายละเอียดวิธีแก้ไขปัญหาเมื่อปิด Ticket')
    custom_help_text = models.TextField(blank=True, default='', help_text='คำแนะนำคำอธิบายประจำฟอร์มแจ้งปัญหาของบริษัท')
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
        (FIELD_TYPE_TEXT, 'Text Input (บรรทัดเดียว)'),
        (FIELD_TYPE_TEXTAREA, 'Text Area (หลายบรรทัด)'),
        (FIELD_TYPE_NUMBER, 'Number (ตัวเลข)'),
        (FIELD_TYPE_SELECT, 'Dropdown Select (ตัวเลือก)'),
        (FIELD_TYPE_DATE, 'Date Picker (วันที่)'),
        (FIELD_TYPE_BOOLEAN, 'Checkbox (สวิตช์ ใช่/ไม่ใช่)'),
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
    options = models.JSONField(default=list, blank=True, help_text='รายการตัวเลือกสำหรับ Dropdown')
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
            {'field_key': 'title', 'label': 'หัวข้อปัญหา', 'field_type': cls.FIELD_TYPE_TEXT, 'placeholder': 'ระบุหัวข้อปัญหา...', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 10},
            {'field_key': 'description', 'label': 'รายละเอียดปัญหา', 'field_type': cls.FIELD_TYPE_TEXTAREA, 'placeholder': 'อธิบายรายละเอียดของปัญหา...', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 20},
            {'field_key': 'priority', 'label': 'ระดับความสำคัญ', 'field_type': cls.FIELD_TYPE_SELECT, 'placeholder': '', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 30},
            {'field_key': 'ticket_category', 'label': 'หมวดหมู่ปัญหา', 'field_type': cls.FIELD_TYPE_SELECT, 'placeholder': '', 'is_required': True, 'is_visible': True, 'is_custom': False, 'order': 40},
            {'field_key': 'attachment', 'label': 'ไฟล์แนบประกอบ', 'field_type': cls.FIELD_TYPE_TEXT, 'placeholder': '', 'is_required': False, 'is_visible': True, 'is_custom': False, 'order': 50},
        ]
        for d in defaults:
            cls.objects.get_or_create(
                company=company,
                field_key=d['field_key'],
                defaults=d
            )



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
    description = models.TextField()
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

    def get_ticket_code(self):
        if hasattr(self.company, 'ticket_config') and self.company.ticket_config.ticket_prefix:
            return f"{self.company.ticket_config.ticket_prefix}{self.id:04d}"
        return f"#{self.id}"

    def get_category_name(self):
        if self.ticket_category:
            return self.ticket_category.name
        return self.get_category_display()

    def __str__(self):
        return f"{self.get_ticket_code()} - {self.title} ({self.status})"


class EmailLog(models.Model):
    RECIPIENT_TO = 'TO'
    RECIPIENT_CC = 'CC'
    RECIPIENT_TYPE_CHOICES = [
        (RECIPIENT_TO, 'ผู้รับหลัก (To)'),
        (RECIPIENT_CC, 'สำเนา (CC)'),
    ]

    ACTION_TICKET_CREATED = 'TICKET_CREATED'
    ACTION_TICKET_UPDATED = 'TICKET_UPDATED'
    ACTION_WELCOME_USER = 'WELCOME_USER'
    ACTION_COMPANY_REGISTERED = 'COMPANY_REGISTERED'
    ACTION_MONTHLY_REPORT = 'MONTHLY_REPORT'
    ACTION_COMMENT_ADDED = 'COMMENT_ADDED'

    ACTION_CHOICES = [
        (ACTION_TICKET_CREATED, 'เปิด Ticket ใหม่'),
        (ACTION_TICKET_UPDATED, 'อัปเดต Ticket'),
        (ACTION_WELCOME_USER, 'ต้อนรับสมาชิกใหม่'),
        (ACTION_COMPANY_REGISTERED, 'ลงทะเบียนบริษัท'),
        (ACTION_MONTHLY_REPORT, 'รายงานประจำเดือน'),
        (ACTION_COMMENT_ADDED, 'แสดงความคิดเห็นใหม่'),
    ]

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
        help_text='รหัสรวมผู้รับ To/CC ของการส่งอีเมลครั้งเดียวกัน',
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
        (TIMEZONE_BANGKOK, 'ประเทศไทย (UTC+7)'),
        (TIMEZONE_HONG_KONG, 'ฮ่องกง (UTC+8)'),
    ]

    name = models.CharField(max_length=150, verbose_name="ชื่อตารางส่ง")
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='monthly_report_schedules',
        null=True,
        blank=True,
        help_text="เว้นว่างสำหรับรายงานรวมทุกบริษัท",
    )
    recipients = models.ManyToManyField(
        CustomUser,
        related_name='monthly_report_schedules_as_recipient',
        verbose_name="ผู้รับหลัก",
    )
    cc_recipients = models.ManyToManyField(
        CustomUser,
        blank=True,
        related_name='monthly_report_schedules_as_cc',
        verbose_name="ผู้รับสำเนา (CC)",
    )
    smtp_configuration = models.ForeignKey(
        'SMTPConfiguration',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='monthly_report_schedules',
        verbose_name="บัญชีอีเมลผู้ส่ง",
    )
    day_of_month = models.PositiveSmallIntegerField(
        default=31,
        verbose_name="วันที่ส่งของเดือน",
        help_text="หากเดือนนั้นไม่มีวันที่ระบุ ระบบจะใช้วันสุดท้ายของเดือน",
    )
    send_time = models.TimeField(default=datetime.time(17, 0), verbose_name="เวลาส่ง")
    timezone_name = models.CharField(
        max_length=50,
        choices=TIMEZONE_CHOICES,
        default=TIMEZONE_BANGKOK,
        verbose_name="เขตเวลา",
    )
    is_active = models.BooleanField(default=True, verbose_name="เปิดใช้งาน")
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
            raise ValidationError({'day_of_month': 'วันที่ส่งต้องอยู่ระหว่าง 1 ถึง 31'})

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
        return f"{self.name} - วันที่ {self.day_of_month} เวลา {self.send_time.strftime('%H:%M')} ({self.get_timezone_name_display()})"


class SMTPConfiguration(models.Model):
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
    password = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.is_active:
            SMTPConfiguration.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()} - {self.username}) - Active: {self.is_active}"


def get_smtp_connection():
    from django.core.mail.backends.smtp import EmailBackend
    config = SMTPConfiguration.objects.filter(is_active=True).first()
    if config and config.provider != 'SIMULATION':
        return EmailBackend(
            host=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            use_tls=config.use_tls,
            fail_silently=True
        )
    return None





def get_smtp_from_email(default_from_email):
    config = SMTPConfiguration.objects.filter(is_active=True).first()
    if config and config.username:
        return config.username
    return default_from_email


class NotificationConfig(models.Model):
    STATUS_NOTIFY_ALL = 'ALL'
    STATUS_NOTIFY_IMPORTANT_ONLY = 'IMPORTANT_ONLY'
    STATUS_NOTIFY_CUSTOM = 'CUSTOM'
    STATUS_NOTIFY_NONE = 'NONE'

    STATUS_NOTIFY_CHOICES = [
        (STATUS_NOTIFY_ALL, 'ทุกสถานะ (All Statuses)'),
        (STATUS_NOTIFY_IMPORTANT_ONLY, 'เฉพาะสถานะสำคัญเท่านั้น (Production Deployment Request, Ready to Deploy, Resolved, Closed)'),
        (STATUS_NOTIFY_CUSTOM, 'กำหนดเลือกสถานะเฉพาะ (Custom Select Statuses)'),
        (STATUS_NOTIFY_NONE, 'ปิดการแจ้งเตือนการเปลี่ยนสถานะ (None)'),
    ]


    name = models.CharField(max_length=255, default="กฎการตั้งค่าการแจ้งเตือน")
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='notification_configs'
    )
    target_users = models.ManyToManyField(
        CustomUser,
        blank=True,
        related_name='notification_configs',
        help_text="หากไม่ระบุผู้ใช้ กฎนี้จะบังคับใช้กับสมาชิกทุกคนในบริษัท"
    )
    notify_ticket_created = models.BooleanField(default=True, verbose_name="แจ้งเตือนการเปิด Ticket ใหม่")
    status_notification_mode = models.CharField(
        max_length=20,
        choices=STATUS_NOTIFY_CHOICES,
        default=STATUS_NOTIFY_ALL,
        verbose_name="โหมดแจ้งเตือนการเปลี่ยนสถานะ"
    )
    allowed_statuses = models.JSONField(
        default=list,
        blank=True,
        verbose_name="รายการสถานะที่เลือกให้แจ้งเตือน"
    )
    notify_comments = models.BooleanField(default=True, verbose_name="แจ้งเตือนความคิดเห็น / ตอบกลับ")
    apply_to_subsidiaries = models.BooleanField(
        default=True,
        verbose_name="บังคับใช้กับบริษัทลูกทั้งหมดด้วย"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.company.name}"


def should_send_email_notification(recipient_email, ticket=None, event_type=None, new_status=None):
    """
    ตรวจสอบว่า recipient_email ควรได้รับอีเมลตามเงื่อนไข notification_configs หรือไม่
    """
    if not recipient_email:
        return False

    user = CustomUser.objects.filter(email=recipient_email).first()
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
