import logging
import time

from django.utils import timezone

from .backup_service import FileLock
from .email_to_ticket import (
    import_all_active_email_to_ticket_configs,
    import_email_to_tickets,
)
from .models import EmailToTicketRunLog, EmailToTicketSchedule


logger = logging.getLogger(__name__)


def _ten_minute_timer_slot(at):
    return at.replace(
        minute=(at.minute // 10) * 10,
        second=0,
        microsecond=0,
    )


def _result_summary(config, result):
    error = result.get('error') or ''
    summary = (
        f"{config.name}: found={result.get('found', 0)} "
        f"pending={result.get('pending', 0)} "
        f"imported={result.get('imported', 0)} "
        f"skipped={result.get('skipped', 0)} "
        f"duplicates={result.get('duplicates', 0)} "
        f"failed={result.get('failed', 0)}"
    )
    if error:
        summary += f" error={error}"
    return summary


def run_email_to_ticket_cycle(*, trigger, actor=None, config=None):
    schedule = EmailToTicketSchedule.get_solo()
    now = timezone.now()

    if trigger == EmailToTicketRunLog.TRIGGER_TIMER:
        if not schedule.is_active:
            return {
                'executed': False,
                'reason': 'Email timer is disabled.',
                'log': None,
                'results': [],
            }
        if not schedule.is_due(now):
            return {
                'executed': False,
                'reason': (
                    f'Next scan is not due yet '
                    f'(interval {schedule.interval_minutes} minutes).'
                ),
                'log': None,
                'results': [],
            }

    run_log = EmailToTicketRunLog.objects.create(
        schedule=schedule,
        trigger=trigger,
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        status=EmailToTicketRunLog.STATUS_RUNNING,
        started_at=now,
    )
    started = time.monotonic()
    results = []
    completed_scheduled_run = False

    try:
        with FileLock('email_to_ticket_cycle.lock', timeout=2):
            if config is not None:
                results = [(config, import_email_to_tickets(config))]
            else:
                results = import_all_active_email_to_ticket_configs()
            completed_scheduled_run = trigger == EmailToTicketRunLog.TRIGGER_TIMER

        run_log.mailbox_count = len(results)
        for _, result in results:
            run_log.found_count += result.get('found', 0)
            run_log.pending_count += result.get('pending', 0)
            run_log.imported_count += result.get('imported', 0)
            run_log.skipped_count += result.get('skipped', 0)
            run_log.duplicate_count += result.get('duplicates', 0)
            run_log.failed_count += result.get('failed', 0)

        if not results:
            run_log.status = EmailToTicketRunLog.STATUS_SKIPPED
            run_log.details = 'No active Email to Ticket SMTP configuration.'
        else:
            failed_results = [result for _, result in results if not result.get('success')]
            if not failed_results:
                run_log.status = EmailToTicketRunLog.STATUS_SUCCESS
            elif len(failed_results) < len(results):
                run_log.status = EmailToTicketRunLog.STATUS_PARTIAL
            else:
                run_log.status = EmailToTicketRunLog.STATUS_FAILED
            run_log.details = '\n'.join(
                _result_summary(mailbox, result)
                for mailbox, result in results
            )
    except TimeoutError as exc:
        run_log.status = EmailToTicketRunLog.STATUS_SKIPPED
        run_log.details = f'Another email scan is already running: {exc}'
    except Exception as exc:
        run_log.status = EmailToTicketRunLog.STATUS_FAILED
        run_log.failed_count += 1
        run_log.details = str(exc)[:4000]
        logger.exception('Email to Ticket cycle failed.')
    finally:
        completed_at = timezone.now()
        run_log.completed_at = completed_at
        run_log.duration_ms = max(0, int((time.monotonic() - started) * 1000))
        run_log.save(update_fields=[
            'status',
            'mailbox_count',
            'found_count',
            'pending_count',
            'imported_count',
            'skipped_count',
            'duplicate_count',
            'failed_count',
            'duration_ms',
            'details',
            'completed_at',
        ])

        schedule.last_run_at = completed_at
        schedule.last_status = run_log.status
        update_fields = ['last_run_at', 'last_status', 'updated_at']
        if completed_scheduled_run:
            schedule.last_scheduled_run_at = _ten_minute_timer_slot(now)
            update_fields.append('last_scheduled_run_at')
        schedule.save(update_fields=update_fields)

    return {
        'executed': True,
        'reason': run_log.details,
        'log': run_log,
        'results': results,
    }
