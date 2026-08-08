from django.db import models
from django.db.models.signals import pre_save, post_save, post_delete, post_migrate
from django.dispatch import receiver
from django.core.mail import EmailMultiAlternatives, send_mail
from django.conf import settings
from django.utils import timezone
import uuid
from .email_formatting import build_formal_email
from .models import (
    Ticket,
    TicketComment,
    CustomUser,
    Company,
    EmailLog,
    InAppNotification,
    InboundEmailAttachment,
    get_smtp_connection,
    get_smtp_from_email,
    should_send_email_notification,
)


@receiver(post_delete, sender=InboundEmailAttachment)
def delete_inbound_email_attachment_file(sender, instance, **kwargs):
    """Pending email files are private and must not outlive their DB record."""
    if instance.file and instance.file.name:
        instance.file.storage.delete(instance.file.name)


def create_in_app_notifications(recipients, event_type, title, message, ticket, actor=None):
    """Create one private notification per active recipient."""
    recipient_ids = {
        user.pk
        for user in recipients
        if user and user.pk and user.is_active
    }
    if actor:
        recipient_ids.discard(actor.pk)
    InAppNotification.objects.bulk_create([
        InAppNotification(
            recipient_id=recipient_id,
            ticket=ticket,
            actor=actor,
            event_type=event_type,
            title=title[:255],
            message=message,
        )
        for recipient_id in recipient_ids
    ])

def log_and_send_email(subject, message, recipient_list, action_type, ticket=None, new_status=None, html_message=None):
    """
    Saves EmailLog to database for auditing and statistics, and sends emails to recipients individually
    to prevent invalid emails from blocking delivery to other recipients.
    """
    subject = ' '.join((subject or '').split())
    recipients = list(set([e for e in recipient_list if e]))
    if not recipients:
        return
        
    connection = get_smtp_connection()
    from_email = get_smtp_from_email('noreply@ticketsolve.com')
    delivery_group = uuid.uuid4()

    for email in recipients:
        if not should_send_email_notification(email, ticket=ticket, event_type=action_type, new_status=new_status):
            print(f"[Notification Filtered] Skipped email to {email} based on notification rules.")
            EmailLog.objects.create(
                ticket=ticket,
                recipient=email,
                recipient_type=EmailLog.RECIPIENT_TO,
                delivery_group=delivery_group,
                subject=subject,
                message=message,
                action_type=action_type,
                success=False,
                error_message="Filtered out by recipient/company notification rules (Notification Filtered)"
            )
            continue

        sent_count = 0
        err_msg = ""
        try:
            kwargs = {
                'subject': subject,
                'message': message,
                'html_message': html_message,
                'from_email': from_email,
                'recipient_list': [email],
                'fail_silently': False
            }
            if connection:
                kwargs['connection'] = connection
            sent_count = send_mail(**kwargs)
        except Exception as e:
            print(f"[Email Notification Error] Failed to send email to {email}: {e}")
            err_msg = str(e)
            sent_count = 0

        EmailLog.objects.create(
            ticket=ticket,
            recipient=email,
            recipient_type=EmailLog.RECIPIENT_TO,
            delivery_group=delivery_group,
            subject=subject,
            message=message,
            action_type=action_type,
            success=(sent_count > 0),
            error_message=err_msg
        )




def send_status_change_email(ticket, subject, message, html_message=None):
    """Send one status email: custom override recipients (if specified for this action) or ticket creator in To and assignee in CC."""
    custom_recipients = getattr(ticket, '_custom_recipient_emails', None)
    if custom_recipients is not None:
        log_and_send_email(
            subject=subject,
            message=message,
            recipient_list=custom_recipients,
            action_type=EmailLog.ACTION_TICKET_UPDATED,
            ticket=ticket,
            new_status=ticket.status,
            html_message=html_message
        )
        return

    delivery_group = uuid.uuid4()
    candidates = []
    creator = ticket.created_by
    assignee = ticket.assigned_to
    creator_email = creator.email if creator else ''
    assignee_email = assignee.email if assignee else ''

    if creator_email:
        candidates.append((creator, creator_email, EmailLog.RECIPIENT_TO))
    if assignee_email and assignee_email != creator_email:
        candidates.append((assignee, assignee_email, EmailLog.RECIPIENT_CC))

    allowed = []
    for recipient_user, email, recipient_type in candidates:
        if should_send_email_notification(
            email,
            ticket=ticket,
            event_type=EmailLog.ACTION_TICKET_UPDATED,
            new_status=ticket.status,
            recipient_user=recipient_user,
        ):
            allowed.append((email, recipient_type))
        else:
            EmailLog.objects.create(
                recipient=email,
                recipient_type=recipient_type,
                delivery_group=delivery_group,
                subject=subject,
                message=message,
                action_type=EmailLog.ACTION_TICKET_UPDATED,
                success=False,
                error_message='Filtered out by recipient/company notification rules (Notification Filtered)',
            )

    if not allowed:
        return

    to_recipients = [email for email, kind in allowed if kind == EmailLog.RECIPIENT_TO]
    cc_recipients = [email for email, kind in allowed if kind == EmailLog.RECIPIENT_CC]
    connection = get_smtp_connection()
    from_email = get_smtp_from_email('noreply@ticketsolve.com')
    success = False
    error_message = ''
    try:
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=from_email,
            to=to_recipients,
            cc=cc_recipients,
            connection=connection,
        )
        if html_message:
            email_message.attach_alternative(html_message, 'text/html')
        sent_count = email_message.send(fail_silently=False)
        if sent_count <= 0:
            raise RuntimeError('SMTP did not confirm email delivery (sent 0).')
        success = True
    except Exception as exc:
        error_message = str(exc)
        print(f"[Status Email Error] Ticket #{ticket.id}: {exc}")

    for email, recipient_type in allowed:
        EmailLog.objects.create(
            recipient=email,
            recipient_type=recipient_type,
            delivery_group=delivery_group,
            subject=subject,
            message=message,
            action_type=EmailLog.ACTION_TICKET_UPDATED,
            success=success,
            error_message=error_message,
        )


@receiver(pre_save, sender=Ticket)
def remember_previous_ticket_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = Ticket.objects.filter(
        pk=instance.pk
    ).values_list('status', flat=True).first()
    if instance._previous_status != instance.status:
        instance.status_changed_at = timezone.now()


@receiver(post_save, sender=Ticket)
def send_ticket_notifications(sender, instance, created, **kwargs):
    """
    Send email notifications and save EmailLog when a ticket is created or updated.
    """
    if created:
        email_source = (instance.custom_fields_data or {}).get('email_to_ticket') or {}
        if not isinstance(email_source, dict):
            email_source = {}
        is_email_ticket = email_source.get('source') == 'EMAIL_TO_TICKET'
        in_app_recipients = set(
            CustomUser.objects.filter(
                is_active=True
            ).filter(
                models.Q(company=instance.company, role__in=[CustomUser.CLIENT_ADMIN, CustomUser.CLIENT_STAFF]) |
                models.Q(role__in=[CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN])
            )
        )
        if instance.assigned_to:
            in_app_recipients.add(instance.assigned_to)
        if not is_email_ticket and instance.created_by:
            in_app_recipients.discard(instance.created_by)

        if is_email_ticket:
            sender_label = email_source.get('sender_name') or email_source.get('sender_email') or 'Unknown sender'
            notification_title = f'New email ticket #{instance.id}'
            notification_message = f'Imported from {sender_label}'
            if email_source.get('sender_email') and email_source.get('sender_name'):
                notification_message += f" <{email_source['sender_email']}>"
        else:
            notification_title = f'New ticket #{instance.id}'
            notification_message = f'Created by {instance.created_by.username}'

        create_in_app_notifications(
            in_app_recipients,
            InAppNotification.EVENT_TICKET_CREATED,
            notification_title,
            notification_message,
            instance,
        )

        subject = f"[TicketSolve] Ticket Created | #{instance.id} - {instance.title}"
        details_list = [
            ('Ticket reference', f'#{instance.id}'),
            ('Subject', instance.title),
            ('Priority', instance.get_priority_display()),
            ('Organization', instance.company.name if instance.company else 'Central Administration'),
            ('Assignee', instance.assigned_to.username if instance.assigned_to else 'Unassigned'),
        ]
        if is_email_ticket:
            sender_info = email_source.get('sender_email') or 'Email Sender'
            if email_source.get('sender_name'):
                sender_info = f"{email_source['sender_name']} <{email_source['sender_email']}>"
            details_list.append(('Original Email Sender', sender_info))
            if email_source.get('routing_rule_id'):
                details_list.append(('Routing Rule', f"Auto-routed to {instance.assigned_to.username}"))
        details_list.append(('Description', instance.description or 'No description provided'))

        greeting_name = instance.assigned_to.username if (is_email_ticket and instance.assigned_to) else instance.created_by.username
        intro_text = 'A new email support request has been imported and assigned.' if is_email_ticket else 'Your support request has been registered successfully. The service desk will review the request and provide updates through TicketSolve.'

        message, html_message = build_formal_email(
            heading='Support Ticket Confirmation',
            greeting=f'Dear {greeting_name},',
            introduction=intro_text,
            details=details_list,
            action_label='View ticket details',
            action_url=f'{settings.PUBLIC_BASE_URL}/ticket/{instance.id}/',
        )
        
        recipients = set()
        if instance.created_by.email:
            recipients.add(instance.created_by.email)
            
        if instance.assigned_to and instance.assigned_to.email:
            recipients.add(instance.assigned_to.email)

        if is_email_ticket and email_source.get('sender_email'):
            recipients.add(email_source['sender_email'])

        client_admins = CustomUser.objects.filter(company=instance.company, role=CustomUser.CLIENT_ADMIN)
        for admin in client_admins:
            if admin.email:
                recipients.add(admin.email)
                
        log_and_send_email(
            subject, message, list(recipients), EmailLog.ACTION_TICKET_CREATED,
            ticket=instance, html_message=html_message,
        )
    else:
        previous_status = getattr(instance, '_previous_status', None)
        if previous_status == instance.status:
            return

        status_recipients = set(
            CustomUser.objects.filter(
                role__in=[CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN],
                is_active=True
            )
        )
        if instance.created_by:
            status_recipients.add(instance.created_by)
        if instance.assigned_to:
            status_recipients.add(instance.assigned_to)

        create_in_app_notifications(
            status_recipients,
            InAppNotification.EVENT_STATUS_CHANGED,
            f'Ticket #{instance.id} status changed',
            f'{previous_status or "Unknown"} → {instance.get_status_display()}',
            instance,
        )

        # Keep the status clock correct when save(update_fields=['status']) is used.
        Ticket.objects.filter(pk=instance.pk).update(status_changed_at=instance.status_changed_at)

        # Action 2: Send status change email notifications
        if instance.status == Ticket.STATUS_DEPLOYMENT_REQUESTED:
            confirm_url = f"{settings.PUBLIC_BASE_URL}/ticket/{instance.id}/confirm-deployment/"
            subject = f"[TicketSolve] Approval Required | Production Deployment - Ticket #{instance.id}"
            message, html_message = build_formal_email(
                heading='Production Deployment Approval Required',
                greeting='Dear Administrator or Stakeholder,',
                introduction=f'A production deployment has been requested for Ticket #{instance.id}. Review the request before granting approval.',
                details=[
                    ('Ticket reference', f'#{instance.id}'),
                    ('Subject', instance.title),
                    ('Priority', instance.get_priority_display()),
                    ('Organization', instance.company.name if instance.company else 'Central Administration'),
                    ('Assignee', instance.assigned_to.username if instance.assigned_to else 'Unassigned'),
                ],
                paragraphs=["After approval, the ticket status will be updated to Ready to Deploy."],
                action_label='Review deployment request',
                action_url=confirm_url,
            )
        else:
            subject = f"[TicketSolve] Ticket Status Update | #{instance.id} - {instance.title}"
            message, html_message = build_formal_email(
                heading='Ticket Status Update',
                greeting=f'Dear {instance.created_by.username},',
                introduction=f'The status of Ticket #{instance.id} has been updated.',
                details=[
                    ('Ticket reference', f'#{instance.id}'),
                    ('Subject', instance.title),
                    ('Current status', instance.get_status_display()),
                    ('Priority', instance.get_priority_display()),
                    ('Assignee', instance.assigned_to.username if instance.assigned_to else 'Unassigned'),
                ],
                action_label='View ticket details',
                action_url=f'{settings.PUBLIC_BASE_URL}/ticket/{instance.id}/',
            )
                  
        send_status_change_email(instance, subject, message, html_message=html_message)


@receiver(post_save, sender=TicketComment)
def notify_ticket_comment(sender, instance, created, **kwargs):
    if not created:
        return
    comment_recipients = set(
        CustomUser.objects.filter(
            role__in=[CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN],
            is_active=True
        )
    )
    if instance.ticket.created_by:
        comment_recipients.add(instance.ticket.created_by)
    if instance.ticket.assigned_to:
        comment_recipients.add(instance.ticket.assigned_to)

    create_in_app_notifications(
        comment_recipients,
        InAppNotification.EVENT_COMMENT_ADDED,
        f'New comment on Ticket #{instance.ticket_id}',
        f'{instance.author.username}: {instance.content[:180]}',
        instance.ticket,
        actor=instance.author,
    )


@receiver(post_migrate)
def ensure_default_categories_and_configs(sender, **kwargs):
    if sender.name == 'tickets':
        from .models import TicketCategory, ResolutionCategory
        defaults_cats = [
            ('Hardware', 'Computer hardware issues (monitor, mouse, keyboard, printer, etc.)', 'cpu', '#f59e0b'),
            ('Software', 'Software usage, installation, licensing, or access issues', 'code', '#3b82f6'),
            ('Network & Internet', 'Network, WiFi, VPN, or LAN connection issues', 'wifi', '#10b981'),
            ('Account & Access', 'Forgotten password, locked account, access permissions request', 'user-check', '#8b5cf6'),
            ('Other', 'General questions or miscellaneous issues', 'help-circle', '#6b7280'),
        ]
        for name, desc, icon, color in defaults_cats:
            if not TicketCategory.objects.filter(name=name, company=None).exists():
                TicketCategory.objects.create(
                    name=name,
                    company=None,
                    description=desc,
                    icon_code=icon,
                    color_code=color
                )

        default_resolutions = [
            ('Hardware Replacement', 'Replaced faulty hardware or components'),
            ('System Configuration Adjustments', 'Adjusted config settings or permissions'),
            ('Program Update / Repair', 'Software patch updates or clean reinstallation'),
            ('User Guidance & FAQs', 'Provided instructions or training to resolve the issue'),
            ('Remote Support (TeamViewer/AnyDesk)', 'Resolved issue via remote desktop support'),
            ('On-Site Support', 'Dispatched technician to resolve issue in-person'),
            ('Other / Cancelled', 'Other types of resolutions or user cancelled request'),
        ]
        for name, desc in default_resolutions:
            if not ResolutionCategory.objects.filter(name=name, company=None).exists():
                ResolutionCategory.objects.create(
                    name=name,
                    company=None,
                    description=desc
                )



@receiver(post_save, sender=CustomUser)
def send_user_welcome_email(sender, instance, created, **kwargs):
    """
    Action 3: Send welcome email and save EmailLog when admin creates a new user account
    """
    if created and instance.email:
        subject = '[TicketSolve] Account Registration Confirmation'
        message, html_message = build_formal_email(
            heading='Your TicketSolve Account Is Ready',
            greeting=f'Dear {instance.username},',
            introduction='Your TicketSolve user account has been created successfully.',
            details=[
                ('Username', instance.username),
                ('Email address', instance.email),
                ('Access role', instance.effective_role_display),
                ('Organization', instance.company.name if instance.company else 'Central Administration'),
            ],
            paragraphs=['Use the credentials supplied by your administrator to sign in. Contact your organization administrator if you require assistance.'],
            action_label='Open TicketSolve',
            action_url=f'{settings.PUBLIC_BASE_URL}/login/',
            closing='TicketSolve System Administration',
        )
        log_and_send_email(
            subject, message, [instance.email], EmailLog.ACTION_WELCOME_USER,
            html_message=html_message,
        )


@receiver(post_save, sender=Company)
def send_company_registration_email(sender, instance, created, **kwargs):
    """
    Action 4: Send alert email and save EmailLog when a new company is registered
    """
    if created:
        system_admins = CustomUser.objects.filter(
            role=CustomUser.SYSTEM_ADMIN
        ).exclude(email='').values_list('email', flat=True)

        if system_admins:
            subject = f"[TicketSolve] Company Registration Notice | {instance.name}"
            message, html_message = build_formal_email(
                heading='Company Registration Notice',
                greeting='Dear System Administrator,',
                introduction='A new tenant organization has been registered in TicketSolve.',
                details=[
                    ('Organization', instance.name),
                    ('Company ID', instance.id),
                ],
                paragraphs=["Review the organization profile and user access assignments in the administration area."],
                action_label='Manage organizations',
                action_url=f'{settings.PUBLIC_BASE_URL}/companies/',
                closing='TicketSolve System Administration',
            )
            log_and_send_email(
                subject, message, system_admins, EmailLog.ACTION_COMPANY_REGISTERED,
                html_message=html_message,
            )
