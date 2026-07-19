from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tickets.models import MonthlyReportSchedule
from tickets.views import send_scheduled_monthly_report


class Command(BaseCommand):
    help = 'Send active monthly report schedules that have reached their configured day and time.'

    def add_arguments(self, parser):
        parser.add_argument('--schedule-id', type=int, help='Process only one schedule ID')
        parser.add_argument('--force', action='store_true', help='Send even when the schedule is not due')

    def handle(self, *args, **options):
        schedule_ids = MonthlyReportSchedule.objects.filter(is_active=True).values_list('id', flat=True)
        if options['schedule_id']:
            schedule_ids = schedule_ids.filter(id=options['schedule_id'])
            if not schedule_ids.exists():
                raise CommandError('Active schedule not found.')

        sent_count = 0
        failed_count = 0
        for schedule_id in list(schedule_ids):
            with transaction.atomic():
                schedule = MonthlyReportSchedule.objects.select_for_update().get(pk=schedule_id)
                now = timezone.now()
                if not options['force'] and not schedule.is_due(now):
                    continue

                schedule.last_attempted_at = now
                schedule.save(update_fields=['last_attempted_at', 'updated_at'])
                try:
                    to_count, cc_count = send_scheduled_monthly_report(schedule)
                except Exception as exc:
                    schedule.last_error = str(exc)
                    schedule.save(update_fields=['last_error', 'updated_at'])
                    failed_count += 1
                    self.stderr.write(self.style.ERROR(f'[{schedule.id}] {schedule.name}: {exc}'))
                    continue

                schedule.last_sent_at = timezone.now()
                schedule.last_error = ''
                schedule.save(update_fields=['last_sent_at', 'last_error', 'updated_at'])
                sent_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f'[{schedule.id}] {schedule.name}: sent to {to_count} recipient(s), CC {cc_count}'
                ))

        self.stdout.write(f'Completed: {sent_count} sent, {failed_count} failed.')
