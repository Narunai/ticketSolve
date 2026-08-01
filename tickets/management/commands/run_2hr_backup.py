from django.core.management.base import BaseCommand
from tickets.models import BackupLog, BackupSchedule
from tickets.backup_service import perform_full_backup, perform_incremental_backup

class Command(BaseCommand):
    help = 'Run the configured Incremental Backup or Full System Backup for TicketSolve'

    def add_arguments(self, parser):
        parser.add_argument(
            '--full',
            action='store_true',
            help='Run a full system backup (database + media; runtime secrets excluded) instead of an incremental backup.'
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=None,
            help='Manual look-back window used with --force (default: configured interval).'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force execution even if a backup was recently completed.'
        )

    def handle(self, *args, **options):
        schedule = BackupSchedule.get_solo()
        force = options.get('force')
        if options.get('full'):
            is_active, _, interval_label = schedule.settings_for(BackupLog.TYPE_FULL)
            if not force:
                if not is_active:
                    self.stdout.write('Skipping: Automatic Full Backup is disabled.')
                    return
                if not schedule.is_due(BackupLog.TYPE_FULL):
                    self.stdout.write(
                        'Skipping: Full Backup is not due yet '
                        f'({interval_label}).'
                    )
                    return
            self.stdout.write("Starting Full System Backup...")
            result = perform_full_backup()
        else:
            is_active, interval_minutes, interval_label = schedule.settings_for(
                BackupLog.TYPE_INCREMENTAL,
            )
            if not force:
                if not is_active:
                    self.stdout.write('Skipping: Automatic Incremental Backup is disabled.')
                    return
                if not schedule.is_due(BackupLog.TYPE_INCREMENTAL):
                    self.stdout.write(
                        'Skipping: Incremental Backup is not due yet '
                        f'({interval_label}).'
                    )
                    return

            configured_hours = max(1, interval_minutes // 60)
            requested_hours = options.get('hours')
            hours = configured_hours
            if force and requested_hours is not None:
                hours = min(max(requested_hours, 1), 168)
            self.stdout.write(f"Starting {hours}-Hour Incremental Backup...")
            result = perform_incremental_backup(hours=hours)

        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(f"Backup completed successfully: {result.get('details', result.get('message', ''))}"))
        else:
            self.stdout.write(self.style.ERROR(f"Backup failed: {result.get('error')}"))
