from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from tickets.models import Company, Ticket, CustomUser

class Command(BaseCommand):
    help = "Compile monthly ticket summaries for each company and send to their Client Admins."

    def handle(self, *args, **options):
        companies = Company.objects.all()
        if not companies.exists():
            self.stdout.write(self.style.WARNING("No companies found in the database."))
            return

        for company in companies:
            self.stdout.write(f"Processing report for company: {company.name}")
            
            # Fetch tickets for this company
            tickets = Ticket.objects.filter(company=company)
            total_tickets = tickets.count()
            
            open_count = tickets.filter(status=Ticket.STATUS_OPEN).count()
            in_progress_count = tickets.filter(status=Ticket.STATUS_IN_PROGRESS).count()
            resolved_count = tickets.filter(status=Ticket.STATUS_RESOLVED).count()
            closed_count = tickets.filter(status=Ticket.STATUS_CLOSED).count()

            # Get list of active Client Admins for this company
            admins = CustomUser.objects.filter(company=company, role=CustomUser.CLIENT_ADMIN)
            recipient_list = [admin.email for admin in admins if admin.email]

            if not recipient_list:
                self.stdout.write(self.style.WARNING(f"  - No Client Admin emails found for {company.name} (skipping)"))
                continue

            # Build report message in Thai as requested by system spec
            subject = f"[TicketSolve] รายงานสรุปสถานะ Ticket ประจำเดือน: {company.name}"
            message = f"เรียน ผู้ดูแลระบบบริษัท {company.name} (Client Admin),\n\n" \
                      f"ระบบทำการรวบรวมรายงานสรุปจำนวนความคืบหน้าของ Ticket แจ้งปัญหาทั้งหมดภายในเดือนนี้:\n" \
                      f"--------------------------------------------------\n" \
                      f"- จำนวน Ticket ทั้งหมด: {total_tickets} รายการ\n" \
                      f"- สถานะเปิดใหม่ (Open): {open_count} รายการ\n" \
                      f"- สถานะกำลังดำเนินการ (In Progress): {in_progress_count} รายการ\n" \
                      f"- สถานะแก้ไขเสร็จสิ้น (Resolved): {resolved_count} รายการ\n" \
                      f"- สถานะปิดสมบูรณ์ (Closed): {closed_count} รายการ\n" \
                      f"--------------------------------------------------\n\n" \
                      f"ท่านสามารถล็อกอินเข้าสู่ระบบหลังบ้าน หรือหน้าจอหลักเพื่อติดตามความคืบหน้าของแต่ละปัญหาเพิ่มเติมได้ตลอด 24 ชั่วโมง\n\n" \
                      f"ขอแสดงความนับถือ,\nทีมงาน TicketSolve Support"

            # Send Email
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email='reports@ticketsolve.com',
                    recipient_list=recipient_list,
                    fail_silently=False
                )
                self.stdout.write(self.style.SUCCESS(f"  - Successfully sent summary of {total_tickets} tickets to {', '.join(recipient_list)}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  - Error sending report: {str(e)}"))

        self.stdout.write(self.style.SUCCESS("Monthly report compilation completed!"))
