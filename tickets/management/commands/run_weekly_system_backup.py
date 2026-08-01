from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tickets.backup_service import perform_system_data_backup
from tickets.models import BackupLog


class Command(BaseCommand):
    help = 'Run the 7-day system-data backup without Ticket rows or media files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Run even if a successful system-data backup exists within 7 days.',
        )

    def handle(self, *args, **options):
        if not options.get('force'):
            recent_backup = BackupLog.objects.filter(
                backup_type=BackupLog.TYPE_SYSTEM,
                status=BackupLog.STATUS_SUCCESS,
                created_at__gte=timezone.now() - timedelta(days=7),
            ).first()
            if recent_backup:
                self.stdout.write(
                    'Skipping: System-data backup already completed at '
                    f'{recent_backup.created_at.strftime("%Y-%m-%d %H:%M:%S")}'
                )
                return

        self.stdout.write('Starting 7-Day System Data Backup (No Tickets)...')
        result = perform_system_data_backup()
        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f"Backup completed successfully: {result.get('details', '')}"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"Backup failed: {result.get('error')}"
            ))
