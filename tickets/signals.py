from django.db.models.signals import pre_save, post_save, post_migrate
from django.dispatch import receiver
from django.core.mail import EmailMessage, send_mail
from django.conf import settings
from django.utils import timezone
import uuid
from .models import Ticket, CustomUser, Company, EmailLog, get_smtp_connection, get_smtp_from_email, should_send_email_notification

def log_and_send_email(subject, message, recipient_list, action_type, ticket=None, new_status=None):
    """
    บันทึก EmailLog ลงในฐานข้อมูลสำหรับการตรวจสอบสถิติและ audit พร้อมส่งอีเมลแยกรายบุคคล
    เพื่อป้องกันไม่ให้อีเมลแอดเดรสที่เสียปะปนอยู่นั้นขัดขวางการส่งอีเมลไปยังผู้รับคนอื่นๆ
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
                error_message="ข้ามการส่งตามกฎตั้งค่าการแจ้งเตือนของผู้รับ/บริษัท (Notification Filtered)"
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
                error_message='ข้ามการส่งตามกฎตั้งค่าการแจ้งเตือนของผู้รับ/บริษัท (Notification Filtered)',
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
            raise RuntimeError('SMTP ไม่ยืนยันการส่งอีเมล (ส่งได้ 0 ฉบับ)')
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
    ส่งอีเมลแจ้งเตือนและบันทึก EmailLog เมื่อมีการสร้างหรืออัปเดต Ticket ในระบบ
    """
    if created:
        # Action 1: แจ้งเตือนเมื่อมีการเปิด Ticket ใหม่
        subject = f"[TicketSolve] ได้รับการแจ้งปัญหาใหม่: Ticket #{instance.id} - {instance.title}"
        message = (
            f"สวัสดีคุณ {instance.created_by.username},\n\n"
            f"ระบบได้รับการแจ้งปัญหาของคุณเรียบร้อยแล้ว รายละเอียดมีดังนี้:\n"
            f"----------------------------------------\n"
            f"📌 รหัส Ticket: #{instance.id}\n"
            f"📌 หัวข้อปัญหา: {instance.title}\n"
            f"📌 ระดับความสำคัญ: {instance.get_priority_display()}\n"
            f"📌 องค์กร: {instance.company.name if instance.company else 'ส่วนกลาง'}\n"
            f"📌 รายละเอียด: {instance.description}\n"
            f"----------------------------------------\n\n"
            f"ทีมงานและแอดมินประจำองค์กรจะเข้าตรวจสอบและดำเนินการแก้ไขโดยเร็วที่สุด\n"
            f"ขอบคุณค่ะ/ครับ\n"
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

        # Action 2: แจ้งเตือนเฉพาะเมื่อสถานะ Ticket เปลี่ยนจริง
        if instance.status == Ticket.STATUS_DEPLOYMENT_REQUESTED:
            confirm_url = f"http://127.0.0.1:8000/ticket/{instance.id}/confirm-deployment/"
            subject = f"[TicketSolve Approval Required] ร้องขอการ Deploy งาน: Ticket #{instance.id} - {instance.title}"
            message = (
                f"เรียนผู้มีส่วนเกี่ยวข้องและแอดมิน,\n\n"
                f"มีการเปลี่ยนสถานะเป็น 'Production Deployment Request' (ร้องขอการ Deploy งาน) สำหรับ Ticket #{instance.id}\n"

                f"----------------------------------------\n"
                f"📌 รหัส Ticket: #{instance.id}\n"
                f"📌 หัวข้อปัญหา: {instance.title}\n"
                f"📌 ระดับความสำคัญ: {instance.get_priority_display()}\n"
                f"📌 องค์กร: {instance.company.name if instance.company else 'ส่วนกลาง'}\n"
                f"📌 ผู้รับผิดชอบ: {instance.assigned_to.username if instance.assigned_to else 'ยังไม่ได้มอบหมาย'}\n"
                f"----------------------------------------\n\n"
                f"กรุณากดยืนยันการอนุมัติให้ Deploy งานได้ที่ลิงก์ด้านล่างนี้:\n"
                f"👉 {confirm_url}\n\n"
                f"เมื่อกดยืนยันแล้ว ระบบจะปรับสถานะของ Ticket เป็น 'Ready to Deploy' โดยอัตโนมัติ\n\n"
                f"ขอบคุณค่ะ/ครับ\n"
                f"TicketSolve Support Team"
            )
        else:
            subject = f"[TicketSolve] อัปเดตความคืบหน้า: Ticket #{instance.id} - {instance.title}"
            message = (
                f"เรียนคุณ {instance.created_by.username},\n\n"
                f"Ticket #{instance.id} ของคุณได้รับการอัปเดตข้อมูลใหม่ในระบบ:\n"
                f"----------------------------------------\n"
                f"📌 สถานะล่าสุด: {instance.get_status_display()}\n"
                f"📌 ระดับความสำคัญ: {instance.get_priority_display()}\n"
                f"📌 ผู้รับผิดชอบงาน: {instance.assigned_to.username if instance.assigned_to else 'ยังไม่ได้มอบหมาย'}\n"
                f"----------------------------------------\n\n"
                f"คุณสามารถล็อกอินเข้าสู่ระบบเพื่อตรวจสอบรายละเอียดเพิ่มเติมได้ที่หน้า Dashboard\n"
                f"ขอบคุณค่ะ/ครับ\n"
                f"TicketSolve Support Team"
            )
                  
        send_status_change_email(instance, subject, message)





@receiver(post_migrate)
def ensure_default_categories_and_configs(sender, **kwargs):
    if sender.name == 'tickets':
        from .models import TicketCategory, ResolutionCategory
        defaults_cats = [
            ('Hardware / อุปกรณ์ฮาร์ดแวร์', 'ปัญหาคอมพิวเตอร์ หน้าจอ เมาส์ คีย์บอร์ด ปริ้นเตอร์', 'cpu', '#f59e0b'),
            ('Software / โปรแกรม', 'ปัญหาการใช้งานซอฟต์แวร์ แรนซัมแวร์ การเข้าไม่ได้', 'code', '#3b82f6'),
            ('Network & Internet / เครือข่าย', 'ปัญหาระบบอินเทอร์เน็ต WiFi VPN สาย LAN', 'wifi', '#10b981'),
            ('Account & Access / บัญชีและสิทธิ์', 'ลืมรหัสผ่าน ปลดล็อกบัญชี ขอสิทธิ์เข้าถึงระบบ', 'user-check', '#8b5cf6'),
            ('Other / เรื่องอื่นๆ', 'ปัญหาหรือข้อสอบถามเพิ่มเติมเรื่องอื่นๆ', 'help-circle', '#6b7280'),
        ]
        for name, desc, icon, color in defaults_cats:
            TicketCategory.objects.get_or_create(
                name=name,
                company=None,
                defaults={'description': desc, 'icon_code': icon, 'color_code': color}
            )

        default_resolutions = [
            ('การเปลี่ยนอุปกรณ์/ชิ้นส่วนใหม่', 'เปลี่ยนทดแทนฮาร์ดแวร์หรืออุปกรณ์ชำรุด'),
            ('การปรับปรุงแก้ไขตั้งค่าระบบ', 'แก้ไขการกำหนดค่า Config หรือ Permissions'),
            ('การอัปเดตและซ่อมแซมโปรแกรม', 'Patch update หรือ Reinstall software'),
            ('การให้คำแนะนำและวิธีใช้งาน', 'ให้ความรู้ คำแนะนำเพื่อแก้ปัญหาผู้ใช้'),
            ('การแก้ไขผ่านระบบทางไกล (Remote)', 'เข้าช่วยเหลือแบบ Remote Support'),
            ('การซ่อมแซมหน้างาน (On-Site)', 'ส่งเจ้าหน้าที่เข้าบริการแก้ไขในสถานที่'),
            ('อื่นๆ / ยกเลิกคำขอ', 'การแก้ไขประเภทอื่นๆ หรือผู้แจ้งยกเลิกเคส'),
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
    Action 3: ส่งอีเมลต้อนรับและบันทึก EmailLog เมื่อแอดมินสร้างบัญชีผู้ใช้งานใหม่
    """
    if created and instance.email:
        subject = f"[TicketSolve] ยินดีต้อนรับ! ข้อมูลบัญชีผู้ใช้งานใหม่ของคุณ"
        message = (
            f"ยินดีต้อนรับคุณ {instance.username} เข้าสู่ระบบ TicketSolve,\n\n"
            f"บัญชีผู้ใช้งานของคุณถูกสร้างขึ้นเรียบร้อยแล้ว รายละเอียดบัญชี:\n"
            f"----------------------------------------\n"
            f"👤 ชื่อผู้ใช้ (Username): {instance.username}\n"
            f"📧 อีเมล (Email): {instance.email}\n"
            f"🔑 บทบาท (Role): {instance.get_role_display()}\n"
            f"🏢 สังกัดองค์กร: {instance.company.name if instance.company else 'ส่วนกลาง (System Admin)'}\n"
            f"----------------------------------------\n\n"
            f"กรุณาใช้ Username และรหัสผ่านที่ได้รับจากผู้ดูแลระบบในการล็อกอินเข้าสู่ระบบ\n"
            f"หากมีข้อสงสัยเพิ่มเติม สามารถติดต่อแอดมินประจำองค์กรของคุณได้ทันที\n\n"
            f"ขอบคุณค่ะ/ครับ\n"
            f"TicketSolve System Administrator"
        )
        log_and_send_email(subject, message, [instance.email], EmailLog.ACTION_WELCOME_USER)


@receiver(post_save, sender=Company)
def send_company_registration_email(sender, instance, created, **kwargs):
    """
    Action 4: ส่งอีเมลแจ้งเตือนและบันทึก EmailLog เมื่อมีการเพิ่มองค์กรใหม่ในระบบ
    """
    if created:
        system_admins = CustomUser.objects.filter(
            role=CustomUser.SYSTEM_ADMIN
        ).exclude(email='').values_list('email', flat=True)

        if system_admins:
            subject = f"[TicketSolve Log] ลงทะเบียนองค์กรใหม่สำเร็จ: {instance.name}"
            message = (
                f"เรียน System Administrator,\n\n"
                f"มีการเพิ่มบริษัท/องค์กรใหม่เข้าสู่ระบบ Multi-tenant:\n"
                f"----------------------------------------\n"
                f"🏢 ชื่อบริษัท: {instance.name}\n"
                f"🆔 Company ID: {instance.id}\n"
                f"----------------------------------------\n\n"
                f"สามารถดูรายละเอียดและจัดการผู้ใช้ขององค์กรใหม่นี้ได้ผ่านระบบ Custom Admin Dashboard\n"
                f"TicketSolve System Log"
            )
            log_and_send_email(subject, message, system_admins, EmailLog.ACTION_COMPANY_REGISTERED)
