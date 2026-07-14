from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import Ticket, CustomUser, Company, EmailLog, get_smtp_connection, get_smtp_from_email

def log_and_send_email(subject, message, recipient_list, action_type):
    """
    บันทึก EmailLog ลงในฐานข้อมูลสำหรับการตรวจสอบสถิติและ audit พร้อมส่งอีเมล
    """
    recipients = [e for e in recipient_list if e]
    if not recipients:
        return
        
    for email in recipients:
        EmailLog.objects.create(
            recipient=email,
            subject=subject,
            message=message,
            action_type=action_type,
            success=True
        )
        
    connection = get_smtp_connection()
    from_email = get_smtp_from_email('noreply@ticketsolve.com')
        
    send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipients,
        fail_silently=True,
        connection=connection
    )


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

        if instance.company:
            admin_emails = CustomUser.objects.filter(
                company=instance.company, 
                role=CustomUser.CLIENT_ADMIN
            ).exclude(email='').values_list('email', flat=True)
            recipients.update(admin_emails)

        log_and_send_email(subject, message, recipients, EmailLog.ACTION_TICKET_CREATED)

    else:
        # Action 2: แจ้งเตือนเมื่อมีการอัปเดตสถานะหรือรายละเอียด Ticket
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
                  
        recipients = set()
        if instance.created_by.email:
            recipients.add(instance.created_by.email)
            
        if instance.assigned_to and instance.assigned_to.email:
            recipients.add(instance.assigned_to.email)
            
        log_and_send_email(subject, message, recipients, EmailLog.ACTION_TICKET_UPDATED)


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
