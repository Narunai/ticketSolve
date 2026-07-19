from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tickets.models import Ticket, TicketAuditLog, TicketAutomationConfig


class Command(BaseCommand):
    help = 'Move stale OPEN tickets to IN_PROGRESS using saved company automation rules.'

    def add_arguments(self, parser):
        parser.add_argument('--ticket-id', type=int, help='Process only one ticket ID.')
        parser.add_argument('--force', action='store_true', help='Ignore the configured age for testing.')

    def handle(self, *args, **options):
        now = timezone.now()
        queryset = Ticket.objects.filter(status=Ticket.STATUS_OPEN).select_related('company')
        if options.get('ticket_id'):
            queryset = queryset.filter(pk=options['ticket_id'])

        changed = 0
        skipped = 0
        for ticket_id in queryset.values_list('id', flat=True).iterator():
            with transaction.atomic():
                ticket = Ticket.objects.select_for_update().select_related('company').get(pk=ticket_id)
                if ticket.status != Ticket.STATUS_OPEN:
                    skipped += 1
                    continue

                config = TicketAutomationConfig.resolve_for_company(ticket.company)
                if not config:
                    skipped += 1
                    continue

                due_at = ticket.status_changed_at + config.threshold_delta()
                if not options.get('force') and now < due_at:
                    skipped += 1
                    continue

                old_status = ticket.status
                ticket.status = Ticket.STATUS_IN_PROGRESS
                ticket.status_changed_at = now
                ticket.save(update_fields=['status', 'status_changed_at', 'updated_at'])
                TicketAuditLog.objects.create(
                    ticket=ticket,
                    actor=None,
                    old_status=old_status,
                    new_status=ticket.status,
                    details=(
                        'ระบบอัตโนมัติเปลี่ยนสถานะจาก Open เป็น In Progress '
                        f'หลังจากค้าง Open ครบ {config.open_age_value} '
                        f'{config.get_open_age_unit_display()} (Ticket Auto Schedule)'
                    ),
                )
                TicketAutomationConfig.objects.filter(pk=config.pk).update(last_applied_at=now)
                changed += 1

        self.stdout.write(self.style.SUCCESS(f'Changed {changed} ticket(s); skipped {skipped} ticket(s).'))
