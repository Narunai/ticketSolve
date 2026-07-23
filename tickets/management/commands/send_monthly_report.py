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

            # Build report message in English
            subject = f"[TicketSolve] Monthly Ticket Summary Report: {company.name}"
            message = f"Dear {company.name} Administrator (Client Admin),\n\n" \
                      f"Please find below the monthly summary report of all support tickets for your company:\n" \
                      f"--------------------------------------------------\n" \
                      f"- Total Tickets: {total_tickets}\n" \
                      f"- Open Status: {open_count}\n" \
                      f"- In Progress Status: {in_progress_count}\n" \
                      f"- Resolved Status: {resolved_count}\n" \
                      f"- Closed Status: {closed_count}\n" \
                      f"--------------------------------------------------\n\n" \
                      f"You can log in to your dashboard to monitor status updates at any time.\n\n" \
                      f"Best regards,\nTicketSolve Support Team"

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
