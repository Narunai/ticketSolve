from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from tickets.email_formatting import build_formal_email
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

            subject = f"[TicketSolve] Monthly Ticket Summary Report - {company.name}"
            report_month = timezone.localtime().strftime('%B %Y')
            message, html_message = build_formal_email(
                heading='Monthly Ticket Summary Report',
                greeting=f'Dear {company.name} Administrator,',
                introduction=f'The TicketSolve ticket summary for {report_month} is available for management review.',
                details=[
                    ('Organization', company.name),
                    ('Total tickets', total_tickets),
                    ('Open', open_count),
                    ('In progress', in_progress_count),
                    ('Resolved', resolved_count),
                    ('Closed', closed_count),
                ],
                paragraphs=['Sign in to TicketSolve to review current ticket information and service progress.'],
                action_label='Open monthly reports',
                action_url=f'{settings.PUBLIC_BASE_URL}/report/',
                notice='This summary may contain confidential operational information. Distribute it only to authorized recipients.',
            )

            # Send Email
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    html_message=html_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipient_list,
                    fail_silently=False
                )
                self.stdout.write(self.style.SUCCESS(f"  - Successfully sent summary of {total_tickets} tickets to {', '.join(recipient_list)}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  - Error sending report: {str(e)}"))

        self.stdout.write(self.style.SUCCESS("Monthly report compilation completed!"))
