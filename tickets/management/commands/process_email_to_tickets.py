from django.core.management.base import BaseCommand

from tickets.email_to_ticket import import_all_active_email_to_ticket_configs


class Command(BaseCommand):
    help = 'Import unread IMAP messages into TicketSolve tickets.'

    def handle(self, *args, **options):
        results = import_all_active_email_to_ticket_configs()
        if not results:
            self.stdout.write('No active Email to Ticket SMTP configuration.')
            return

        has_failure = False
        for config, result in results:
            summary = (
                f"{config.name}: found={result['found']} imported={result['imported']} "
                f"skipped={result['skipped']} duplicates={result['duplicates']} "
                f"failed={result['failed']}"
            )
            if result['success']:
                self.stdout.write(self.style.SUCCESS(summary))
            else:
                has_failure = True
                error = result.get('error') or 'One or more messages failed.'
                self.stderr.write(self.style.ERROR(f'{summary} error={error}'))

        if has_failure:
            raise RuntimeError('One or more Email to Ticket imports failed.')
