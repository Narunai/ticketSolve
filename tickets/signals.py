from django.db.models.signals import pre_save, post_save, post_migrate
from django.dispatch import receiver
from django.core.mail import EmailMessage, send_mail
from django.conf import settings
from django.utils import timezone
import uuid
from .models import Ticket, CustomUser, Company, EmailLog, get_smtp_connection, get_smtp_from_email, should_send_email_notification

def log_and_send_email(subject, message, recipient_list, action_type, ticket=None, new_status=None):
    """
    Saves EmailLog to database for auditing and statistics, and sends emails to recipients individually
    to prevent invalid emails from blocking delivery to other recipients.
    """
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
            recipient=email,
            recipient_type=EmailLog.RECIPIENT_TO,
            delivery_group=delivery_group,
            subject=subject,
            message=message,
            action_type=action_type,
            success=(sent_count > 0),
            error_message=err_msg
        )


def send_status_change_email(ticket, subject, message):
    """Send one status email: ticket creator in To and assignee in CC."""
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
        email_message = EmailMessage(
            subject=subject,
            body=message,
            from_email=from_email,
            to=to_recipients,
            cc=cc_recipients,
            connection=connection,
        )
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
        subject = f"[TicketSolve] New Support Ticket Created: Ticket #{instance.id} - {instance.title}"
        message = (
            f"Dear {instance.created_by.username},\n\n"
            f"We have successfully received your support ticket. Here are the details:\n"
            f"----------------------------------------\n"
            f"📌 Ticket ID: #{instance.id}\n"
            f"📌 Title: {instance.title}\n"
            f"📌 Priority: {instance.get_priority_display()}\n"
            f"📌 Organization: {instance.company.name if instance.company else 'Central'}\n"
            f"📌 Description: {instance.description}\n"
            f"----------------------------------------\n\n"
            f"Our team will review your request and begin working on a resolution shortly.\n"
            f"Best regards,\n"
            f"TicketSolve Support Team"
        )
        
        recipients = set()
        if instance.created_by.email:
            recipients.add(instance.created_by.email)
            
        if instance.assigned_to and instance.assigned_to.email:
            recipients.add(instance.assigned_to.email)

        client_admins = CustomUser.objects.filter(company=instance.company, role=CustomUser.CLIENT_ADMIN)
        for admin in client_admins:
            if admin.email:
                recipients.add(admin.email)
                
        log_and_send_email(subject, message, list(recipients), EmailLog.ACTION_TICKET_CREATED, ticket=instance)
    else:
        previous_status = getattr(instance, '_previous_status', None)
        if previous_status == instance.status:
            return

        # Keep the status clock correct when save(update_fields=['status']) is used.
        Ticket.objects.filter(pk=instance.pk).update(status_changed_at=instance.status_changed_at)

        # Action 2: Send status change email notifications
        if instance.status == Ticket.STATUS_DEPLOYMENT_REQUESTED:
            confirm_url = f"http://127.0.0.1:8000/ticket/{instance.id}/confirm-deployment/"
            subject = f"[TicketSolve Approval Required] Production Deployment Request: Ticket #{instance.id} - {instance.title}"
            message = (
                f"Dear Admin / Stakeholder,\n\n"
                f"A deployment to production has been requested for Ticket #{instance.id}.\n\n"
                f"----------------------------------------\n"
                f"📌 Ticket ID: #{instance.id}\n"
                f"📌 Title: {instance.title}\n"
                f"📌 Priority: {instance.get_priority_display()}\n"
                f"📌 Company: {instance.company.name if instance.company else 'Central'}\n"
                f"📌 Assignee: {instance.assigned_to.username if instance.assigned_to else 'Not Assigned'}\n"
                f"----------------------------------------\n\n"
                f"Please review and approve the deployment request using the following link:\n"
                f"👉 {confirm_url}\n\n"
                f"Once confirmed, the ticket status will be automatically updated to 'Ready to Deploy'.\n\n"
                f"Best regards,\n"
                f"TicketSolve Support Team"
            )
        else:
            subject = f"[TicketSolve] Status Update: Ticket #{instance.id} - {instance.title}"
            message = (
                f"Dear {instance.created_by.username},\n\n"
                f"Your Ticket #{instance.id} has been updated in the system:\n\n"
                f"----------------------------------------\n"
                f"📌 Latest Status: {instance.get_status_display()}\n"
                f"📌 Priority: {instance.get_priority_display()}\n"
                f"📌 Assignee: {instance.assigned_to.username if instance.assigned_to else 'Not Assigned'}\n"
                f"----------------------------------------\n\n"
                f"You can log in to your dashboard to track details.\n\n"
                f"Best regards,\n"
                f"TicketSolve Support Team"
            )
                  
        send_status_change_email(instance, subject, message)
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
            TicketCategory.objects.get_or_create(
                name=name,
                company=None,
                defaults={'description': desc, 'icon_code': icon, 'color_code': color}
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
            ResolutionCategory.objects.get_or_create(
                name=name,
                company=None,
                defaults={'description': desc}
            )



@receiver(post_save, sender=CustomUser)
def send_user_welcome_email(sender, instance, created, **kwargs):
    """
    Action 3: Send welcome email and save EmailLog when admin creates a new user account
    """
    if created and instance.email:
        subject = f"[TicketSolve] Welcome! Your New Account Details"
        message = (
            f"Dear {instance.username},\n\n"
            f"Welcome to TicketSolve! Your user account has been successfully created. Here are your account details:\n"
            f"----------------------------------------\n"
            f"👤 Username: {instance.username}\n"
            f"📧 Email: {instance.email}\n"
            f"🔑 Role: {instance.get_role_display()}\n"
            f"🏢 Company: {instance.company.name if instance.company else 'Central (System Admin)'}\n"
            f"----------------------------------------\n\n"
            f"Please log in using the credentials provided by your system administrator.\n"
            f"If you have any questions, please contact your organization administrator.\n\n"
            f"Best regards,\n"
            f"TicketSolve System Administrator"
        )
        log_and_send_email(subject, message, [instance.email], EmailLog.ACTION_WELCOME_USER)


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
            subject = f"[TicketSolve Log] New Company Registered Successfully: {instance.name}"
            message = (
                f"Dear System Administrator,\n\n"
                f"A new tenant company has been registered in the system:\n"
                f"----------------------------------------\n"
                f"🏢 Company Name: {instance.name}\n"
                f"🆔 Company ID: {instance.id}\n"
                f"----------------------------------------\n\n"
                f"You can review and manage this company's users through the custom Admin Dashboard.\n"
                f"TicketSolve System Log"
            )
            log_and_send_email(subject, message, system_admins, EmailLog.ACTION_COMPANY_REGISTERED)
