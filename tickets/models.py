from django.db import models
from django.contrib.auth.models import AbstractUser

class Company(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

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

class Ticket(models.Model):
    STATUS_OPEN = 'OPEN'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_CLOSED = 'CLOSED'

    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_IN_PROGRESS, 'In Progress'),
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
        max_length=20,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_OTHER
    )
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

    def __str__(self):
        return f"#{self.id} - {self.title} ({self.status})"

class EmailLog(models.Model):
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
    subject = models.CharField(max_length=255)
    message = models.TextField()
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)

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
            fail_silently=False
        )
    return None


def get_smtp_from_email(default_from_email):
    config = SMTPConfiguration.objects.filter(is_active=True).first()
    if config and config.username:
        return config.username
    return default_from_email
