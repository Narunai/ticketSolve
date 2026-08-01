from django.core.management.base import BaseCommand

from tickets.backup_service import perform_system_data_backup
from tickets.models import BackupLog, BackupSchedule


class Command(BaseCommand):
    help = 'Run the configured system-data backup without Ticket rows or media files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Run immediately even when the timer is disabled or not due.',
        )

    def handle(self, *args, **options):
        schedule = BackupSchedule.get_solo()
        if not options.get('force'):
            is_active, _, interval_label = schedule.settings_for(BackupLog.TYPE_SYSTEM)
            if not is_active:
                self.stdout.write('Skipping: Automatic System Data Backup is disabled.')
                return
            if not schedule.is_due(BackupLog.TYPE_SYSTEM):
                self.stdout.write(
                    'Skipping: System Data Backup is not due yet '
                    f'({interval_label}).'
                )
                return

        self.stdout.write('Starting System Data Backup (No Tickets)...')
        result = perform_system_data_backup()
        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f"Backup completed successfully: {result.get('details', '')}"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"Backup failed: {result.get('error')}"
            ))
