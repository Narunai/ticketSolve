from datetime import timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
from tickets.models import BackupLog
from tickets.backup_service import perform_full_backup, perform_incremental_backup

class Command(BaseCommand):
    help = 'Run 2-Hour Incremental Backup or Full System Backup for TicketSolve'

    def add_arguments(self, parser):
        parser.add_argument(
            '--full',
            action='store_true',
            help='Run a full system backup (db + media + env) instead of 2-hour incremental backup.'
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=2,
            help='Number of hours to look back for new tickets (default: 2).'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force execution even if a backup was recently completed.'
        )

    def handle(self, *args, **options):
        if options.get('full'):
            self.stdout.write("Starting Full System Backup...")
            result = perform_full_backup()
        else:
            hours = options.get('hours', 2)
            # Throttling check: Skip if an incremental backup was executed within the last (hours * 60 - 5) minutes unless --force is passed
            if not options.get('force'):
                recent_backup = BackupLog.objects.filter(
                    backup_type=BackupLog.TYPE_INCREMENTAL,
                    created_at__gte=timezone.now() - timedelta(minutes=hours * 60 - 5)
                ).first()
                if recent_backup:
                    self.stdout.write(f"Skipping: Incremental backup already completed at {recent_backup.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    return

            self.stdout.write(f"Starting {hours}-Hour Incremental Backup...")
            result = perform_incremental_backup(hours=hours)

        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(f"Backup completed successfully: {result.get('details', result.get('message', ''))}"))
        else:
            self.stdout.write(self.style.ERROR(f"Backup failed: {result.get('error')}"))
