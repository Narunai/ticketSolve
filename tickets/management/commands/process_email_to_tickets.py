from django.core.management.base import BaseCommand

from tickets.email_to_ticket_scheduler import run_email_to_ticket_cycle
from tickets.models import EmailToTicketRunLog


class Command(BaseCommand):
    help = 'Import unread IMAP messages into TicketSolve tickets.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Run immediately instead of waiting for the configured timer interval.',
        )

    def handle(self, *args, **options):
        trigger = (
            EmailToTicketRunLog.TRIGGER_MANUAL
            if options['force']
            else EmailToTicketRunLog.TRIGGER_TIMER
        )
        outcome = run_email_to_ticket_cycle(trigger=trigger)
        if not outcome['executed']:
            self.stdout.write(outcome['reason'])
            return

        run_log = outcome['log']
        summary = (
            f"status={run_log.status} mailboxes={run_log.mailbox_count} "
            f"found={run_log.found_count} pending={run_log.pending_count} "
            f"imported={run_log.imported_count} "
            f"skipped={run_log.skipped_count} duplicates={run_log.duplicate_count} "
            f"failed={run_log.failed_count} duration_ms={run_log.duration_ms}"
        )

        if run_log.status in {
            EmailToTicketRunLog.STATUS_FAILED,
            EmailToTicketRunLog.STATUS_PARTIAL,
        }:
            self.stderr.write(self.style.ERROR(summary))
            raise RuntimeError('One or more Email to Ticket imports failed.')
        self.stdout.write(self.style.SUCCESS(summary))
