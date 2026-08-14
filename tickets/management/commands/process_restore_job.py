import json
import os
import shutil
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections
from django.utils import timezone

from tickets.backup_restore_service import (
    extract_validated_full_archive,
    restore_database_payload,
    restore_non_database_payloads,
    validate_backup_archive,
)
from tickets.backup_service import BACKUP_DIR, FileLock, get_backup_file_path, perform_full_backup
from tickets.models import BackupLog, CustomUser, MaintenanceSetting, RestoreJob


class Command(BaseCommand):
    help = 'Process one administrator-approved, validated Full Backup restore job.'

    def add_arguments(self, parser):
        parser.add_argument('job_id', help='RestoreJob UUID queued by the web application.')

    def _external_log(self, job_id, event, details, outcome='INFO'):
        log_dir = os.path.abspath(
            os.environ.get(
                'RESTORE_LOG_DIR',
                os.path.join(settings.BASE_DIR, '.restore', 'logs'),
            )
        )
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f'{job_id}.jsonl')
        record = {
            'timestamp': timezone.now().isoformat(),
            'job_id': str(job_id),
            'event': event,
            'outcome': outcome,
            'details': str(details)[:4000],
        }
        with open(log_path, 'a', encoding='utf-8') as output:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')
        return log_path

    def _set_job(self, job, status, progress, details):
        job.status = status
        job.progress_percent = progress
        job.details = str(details)[:10000]
        if not job.started_at:
            job.started_at = timezone.now()
        job.save(update_fields=[
            'status',
            'progress_percent',
            'details',
            'started_at',
            'updated_at',
        ])

    @staticmethod
    def _backup_metadata(backup):
        return {
            'filename': backup.filename,
            'original_filename': backup.original_filename,
            'file_size_bytes': backup.file_size_bytes,
            'backup_type': backup.backup_type,
            'source': backup.source,
            'sha256': backup.sha256,
            'format_version': backup.format_version,
            'validation_status': backup.validation_status,
            'validation_details': backup.validation_details,
            'restore_supported': backup.restore_supported,
            'details': backup.details,
            'is_protected': backup.is_protected,
        }

    @staticmethod
    def _ensure_backup(metadata):
        backup = BackupLog.objects.filter(
            filename=metadata['filename'],
            sha256=metadata['sha256'],
        ).first()
        if backup:
            return backup
        return BackupLog.objects.create(**metadata, status=BackupLog.STATUS_SUCCESS)

    @staticmethod
    def _maintenance_state(setting):
        return {
            'is_enabled': True,
            'title': setting.title,
            'message': setting.message,
            'scheduled_start': None,
            'expected_end': setting.expected_end,
            'allow_test_access': setting.allow_test_access,
            'access_code_hash': setting.access_code_hash,
            'access_version': setting.access_version,
            'access_session_minutes': setting.access_session_minutes,
            'updated_by_username': setting.updated_by.username if setting.updated_by else '',
        }

    @staticmethod
    def _restore_maintenance_state(state):
        setting = MaintenanceSetting.get_solo()
        updated_by = None
        if state.get('updated_by_username'):
            updated_by = CustomUser.objects.filter(
                username=state['updated_by_username']
            ).first()
        for field in (
            'is_enabled',
            'title',
            'message',
            'scheduled_start',
            'expected_end',
            'allow_test_access',
            'access_code_hash',
            'access_version',
            'access_session_minutes',
        ):
            setattr(setting, field, state[field])
        setting.updated_by = updated_by
        setting.save()

    def _restore_archive(self, archive_path, expected_sha256):
        staging_parent = os.path.join(BACKUP_DIR, '.restore-staging')
        os.makedirs(staging_parent, exist_ok=True)
        operation_directory = tempfile.mkdtemp(prefix='restore-', dir=staging_parent)
        staging_directory = os.path.join(operation_directory, 'payload')
        staged_archive = os.path.join(operation_directory, 'validated-full-backup.tar.gz')
        try:
            # Copy into a root-owned 0700 directory first. Validation and
            # extraction then use the immutable worker-side copy instead of a
            # web-writable backup path that could change between those steps.
            shutil.copy2(archive_path, staged_archive)
            validation = extract_validated_full_archive(
                staged_archive,
                staging_directory,
                expected_sha256=expected_sha256,
            )
            manifest = validation['manifest']
            restore_database_payload(staging_directory, manifest)
            restore_non_database_payloads(staging_directory, manifest)
            connections.close_all()
            call_command('check', verbosity=0)
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            return validation
        finally:
            shutil.rmtree(operation_directory, ignore_errors=True)

    def handle(self, *args, **options):
        job_id = options['job_id']
        try:
            job = RestoreJob.objects.select_related(
                'backup',
                'requested_by',
            ).get(job_id=job_id)
        except RestoreJob.DoesNotExist as exc:
            raise CommandError('Restore job was not found.') from exc
        if job.status != RestoreJob.STATUS_QUEUED:
            raise CommandError(f'Restore job is not queued (status={job.status}).')

        backup = job.backup
        archive_path = get_backup_file_path(backup.filename)
        requester_username = job.requested_by.username if job.requested_by else ''
        backup_metadata = self._backup_metadata(backup)
        maintenance_state = self._maintenance_state(MaintenanceSetting.get_solo())
        rollback_path = ''
        rollback_metadata = None
        external_log_path = self._external_log(
            job.job_id,
            'RESTORE_STARTED',
            f'Restore requested for {backup.filename}.',
        )
        job.external_log_path = external_log_path
        job.save(update_fields=['external_log_path', 'updated_at'])

        with FileLock('restore_operation.lock', timeout=5):
            try:
                self._set_job(job, RestoreJob.STATUS_VALIDATING, 10, 'Validating archive checksum and compatibility.')
                validation = validate_backup_archive(
                    archive_path or '',
                    expected_sha256=backup.sha256,
                )
                if not validation.get('restore_supported'):
                    raise ValueError(validation.get('details') or 'Backup is not restorable.')
                self._external_log(job.job_id, 'VALIDATION_COMPLETE', validation['details'])

                self._set_job(job, RestoreJob.STATUS_PRE_BACKUP, 25, 'Creating protected pre-restore rollback backup.')
                rollback_result = perform_full_backup()
                if not rollback_result.get('success'):
                    raise RuntimeError(
                        f"Pre-restore backup failed: {rollback_result.get('error', 'unknown error')}"
                    )
                rollback_backup = rollback_result['log']
                rollback_backup.is_protected = True
                rollback_backup.save(update_fields=['is_protected'])
                rollback_path = rollback_result['file_path']
                rollback_metadata = self._backup_metadata(rollback_backup)
                job.rollback_backup = rollback_backup
                job.save(update_fields=['rollback_backup', 'updated_at'])
                self._external_log(job.job_id, 'ROLLBACK_BACKUP_CREATED', rollback_backup.filename)

                self._set_job(job, RestoreJob.STATUS_RESTORING, 50, 'Replacing validated database and file payloads.')
                self._restore_archive(archive_path, backup.sha256)

                # The restored database predates this request in the usual case,
                # so reconstruct the auditable restore records after reconnecting.
                connections.close_all()
                self._restore_maintenance_state(maintenance_state)
                restored_backup = self._ensure_backup(backup_metadata)
                restored_rollback = self._ensure_backup(rollback_metadata)
                requested_by = CustomUser.objects.filter(username=requester_username).first()
                restored_job, _ = RestoreJob.objects.update_or_create(
                    job_id=job.job_id,
                    defaults={
                        'backup': restored_backup,
                        'rollback_backup': restored_rollback,
                        'requested_by': requested_by,
                        'status': RestoreJob.STATUS_VERIFYING,
                        'progress_percent': 85,
                        'details': 'Restore payload applied; running final verification.',
                        'external_log_path': external_log_path,
                        'started_at': job.started_at or timezone.now(),
                    },
                )
                call_command('check', deploy=not settings.DEBUG, verbosity=0)
                restored_job.status = RestoreJob.STATUS_AWAITING_REVIEW
                restored_job.progress_percent = 100
                restored_job.details = (
                    'Restore completed and automated checks passed. '
                    'Maintenance mode remains active until an administrator completes review.'
                )
                restored_job.save(update_fields=[
                    'status',
                    'progress_percent',
                    'details',
                    'updated_at',
                ])
                self._external_log(job.job_id, 'RESTORE_AWAITING_REVIEW', restored_job.details, 'SUCCESS')
                self.stdout.write(self.style.SUCCESS(restored_job.details))
            except Exception as exc:
                self._external_log(job.job_id, 'RESTORE_FAILED', str(exc), 'FAILURE')
                rollback_error = None
                if rollback_path and rollback_metadata:
                    try:
                        self._restore_archive(rollback_path, rollback_metadata['sha256'])
                        connections.close_all()
                        self._restore_maintenance_state(maintenance_state)
                        restored_backup = self._ensure_backup(backup_metadata)
                        restored_rollback = self._ensure_backup(rollback_metadata)
                        requested_by = CustomUser.objects.filter(username=requester_username).first()
                        RestoreJob.objects.update_or_create(
                            job_id=job.job_id,
                            defaults={
                                'backup': restored_backup,
                                'rollback_backup': restored_rollback,
                                'requested_by': requested_by,
                                'status': RestoreJob.STATUS_ROLLED_BACK,
                                'progress_percent': 100,
                                'details': f'Restore failed and was rolled back safely: {exc}',
                                'external_log_path': external_log_path,
                                'started_at': job.started_at or timezone.now(),
                                'completed_at': timezone.now(),
                            },
                        )
                        self._external_log(job.job_id, 'AUTOMATIC_ROLLBACK_COMPLETE', str(exc), 'SUCCESS')
                    except Exception as rollback_exc:
                        rollback_error = rollback_exc
                        self._external_log(
                            job.job_id,
                            'AUTOMATIC_ROLLBACK_FAILED',
                            str(rollback_exc),
                            'FAILURE',
                        )
                else:
                    try:
                        job.status = RestoreJob.STATUS_FAILED
                        job.details = str(exc)[:10000]
                        job.completed_at = timezone.now()
                        job.save(update_fields=['status', 'details', 'completed_at', 'updated_at'])
                        # No database/file replacement began because a rollback
                        # archive was never created. Release the target from
                        # retention protection while the failed job remains in
                        # the audit trail.
                        backup.is_protected = False
                        backup.save(update_fields=['is_protected'])
                    except Exception:
                        pass
                if rollback_error:
                    raise CommandError(
                        f'Restore failed ({exc}); automatic rollback also failed ({rollback_error}).'
                    ) from rollback_error
                raise CommandError(f'Restore failed and rollback was applied: {exc}') from exc
