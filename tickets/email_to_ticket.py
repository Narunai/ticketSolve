import email
import imaplib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr

from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .backup_service import FileLock
from .security import validate_attachment
from .models import (
    InboundEmailAttachment,
    InboundEmailContact,
    InboundEmailReceipt,
    SMTPConfiguration,
    Ticket,
    TicketAttachment,
)


logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_TICKET = 10
MAX_TOTAL_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_RAW_EMAIL_BYTES = 55 * 1024 * 1024
MAX_BODY_CHARACTERS = 100_000

DEFAULT_ISSUE_KEYWORDS = (
    'ปัญหา', 'ปันหา', 'แจ้งปัญหา', 'แจ้งปันหา', 'รายงานปัญหา',
    'ขัดข้อง', 'ใช้งานไม่ได้', 'ใช้ไม่ได้', 'เข้าไม่ได้', 'โหลดไม่ได้',
    'ระบบล่ม', 'ระบบค้าง', 'หน้าจอค้าง', 'ผิดพลาด', 'แจ้งซ่อม',
    'issue', 'isue', 'bug', 'error', 'eror', 'problem', 'incident',
    'failed', 'failure', 'broken', 'not working', 'down', 'exception',
    'crash', 'support', 'help', 'cannot access', 'unable to login',
)


@dataclass
class InboundMessage:
    uid: bytes
    message_id: str
    subject: str
    body: str
    sender_name: str = ''
    sender_email: str = ''
    attachments: list[dict] = field(default_factory=list)


def clean_email_body(raw_content, is_html=False):
    if not raw_content:
        return ''

    text = raw_content
    if is_html or '<html' in raw_content.lower() or '<body' in raw_content.lower():
        soup = BeautifulSoup(raw_content, 'html.parser')
        for unwanted in soup(['script', 'style', 'head', 'meta']):
            unwanted.decompose()
        text = soup.get_text(separator='\n')

    quote_markers = (
        '-----original message-----',
        '________________________________',
        '----- ข้อความดั้งเดิม -----',
    )
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered in quote_markers:
            break
        if lowered.startswith('on ') and lowered.endswith(' wrote:'):
            break
        if stripped.startswith('>'):
            continue
        cleaned_lines.append(line)

    result = '\n'.join(cleaned_lines).strip()
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')
    return result


def _decode_header(value):
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value))).strip()
    except (LookupError, UnicodeDecodeError):
        fragments = []
        for part, charset in decode_header(value):
            if isinstance(part, bytes):
                fragments.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                fragments.append(str(part))
        return ''.join(fragments).strip()


def _decode_payload(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        return ''
    charset = part.get_content_charset() or 'utf-8'
    try:
        return payload.decode(charset, errors='replace')
    except LookupError:
        return payload.decode('utf-8', errors='replace')


def _parse_message(uid, raw_email):
    parsed = email.message_from_bytes(raw_email)
    subject = _decode_header(parsed.get('Subject')) or '(No subject)'
    sender_name, sender_email = parseaddr(_decode_header(parsed.get('From')))

    plain_body = ''
    html_body = ''
    attachments = []
    for part in parsed.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        filename = part.get_filename()
        disposition = (part.get('Content-Disposition') or '').lower()
        if filename or 'attachment' in disposition:
            content = part.get_payload(decode=True) or b''
            if content:
                attachments.append({
                    'filename': _decode_header(filename) or 'email-attachment',
                    'content': content,
                    'size': len(content),
                })
            continue
        if part.get_content_type() == 'text/plain' and not plain_body:
            plain_body = _decode_payload(part)
        elif part.get_content_type() == 'text/html' and not html_body:
            html_body = _decode_payload(part)

    body = clean_email_body(
        plain_body or html_body,
        is_html=not plain_body and bool(html_body),
    ) or '(No email body)'
    if len(body) > MAX_BODY_CHARACTERS:
        body = (
            body[:MAX_BODY_CHARACTERS]
            + '\n\n[Email body truncated at 100,000 characters.]'
        )
    message_id = (parsed.get('Message-ID') or '').strip()
    if not message_id:
        uid_text = uid.decode('ascii', errors='ignore') if isinstance(uid, bytes) else str(uid)
        message_id = f'imap-uid:{uid_text}'

    return InboundMessage(
        uid=uid,
        message_id=message_id[:512],
        subject=subject[:255],
        body=body,
        sender_name=(sender_name or '')[:255],
        sender_email=(sender_email or '')[:254],
        attachments=attachments,
    )


def _issue_keywords(config):
    configured = [
        item.strip().casefold()
        for item in config.issue_keywords.split(',')
        if item.strip()
    ]
    built_in = [item.casefold() for item in DEFAULT_ISSUE_KEYWORDS]
    return list(dict.fromkeys(built_in + configured))


def _is_issue_message(config, message):
    if message.subject.strip().casefold().startswith('[ticketsolve]'):
        return False, ['system-generated']
    if not config.filter_issue_only:
        return True, []
    subject = message.subject.casefold()
    matched = [keyword for keyword in _issue_keywords(config) if keyword in subject]
    return bool(matched), matched


def _safe_attachment_name(filename):
    normalized = (filename or 'email-attachment').replace('\\', '/')
    return os.path.basename(normalized)[:255] or 'email-attachment'


def _validated_attachments(message):
    skipped = []
    accepted = []
    total_bytes = 0
    for attachment in message.attachments:
        filename = _safe_attachment_name(attachment.get('filename'))
        content = attachment.get('content') or b''
        size = len(content)
        if len(accepted) >= MAX_ATTACHMENTS_PER_TICKET:
            skipped.append(f'{filename}: over 10-file limit')
            continue
        if size > MAX_ATTACHMENT_BYTES:
            skipped.append(f'{filename}: over 10 MB')
            continue
        if total_bytes + size > MAX_TOTAL_ATTACHMENT_BYTES:
            skipped.append(f'{filename}: total would exceed 50 MB')
            continue
        validation_error = validate_attachment(content, filename)
        if validation_error:
            skipped.append(validation_error)
            continue
        accepted.append((filename, content))
        total_bytes += size
    return accepted, skipped


def _record_contact(config, message):
    sender_email = (message.sender_email or '').strip().casefold()
    if not sender_email:
        return None
    now = timezone.now()
    contact, created = InboundEmailContact.objects.get_or_create(
        smtp_configuration=config,
        email=sender_email,
        defaults={
            'display_name': message.sender_name,
            'message_count': 1,
            'last_subject': message.subject,
            'first_seen_at': now,
            'last_seen_at': now,
        },
    )
    if not created:
        updates = {
            'message_count': F('message_count') + 1,
            'last_subject': message.subject,
            'last_seen_at': now,
        }
        if message.sender_name:
            updates['display_name'] = message.sender_name
        InboundEmailContact.objects.filter(pk=contact.pk).update(**updates)
        contact.refresh_from_db()
    return contact


def _queue_email_for_approval(config, message, matched_keywords=None):
    accepted, skipped = _validated_attachments(message)
    with transaction.atomic():
        receipt, _ = InboundEmailReceipt.objects.update_or_create(
            smtp_configuration=config,
            message_id=message.message_id,
            defaults={
                'sender_name': message.sender_name,
                'sender_email': message.sender_email,
                'subject': message.subject,
                'body': message.body,
                'matched_keywords': matched_keywords or [],
                'status': InboundEmailReceipt.STATUS_PENDING,
                'details': (
                    'Waiting for an authorized administrator to approve import; '
                    f'accepted attachments: {len(accepted)}.'
                    + (f" Skipped: {'; '.join(skipped)}" if skipped else '')
                ),
                'ticket': None,
                'decided_by': None,
                'decided_at': None,
            },
        )
        for old_attachment in list(receipt.attachments.all()):
            old_attachment.delete()
        with FileLock('system_backup.lock', timeout=30):
            for filename, content in accepted:
                InboundEmailAttachment.objects.create(
                    receipt=receipt,
                    file=ContentFile(content, name=filename),
                    filename=filename,
                    file_size=len(content),
                )
    return receipt, skipped


def _resolve_ticket_route(config, message):

    routing_rule = config.inbound_routing_rules.filter(
        is_active=True,
        sender_email__iexact=message.sender_email,
        assignee__is_active=True,
    ).select_related('assignee').first()
    assignee = (
        routing_rule.assignee
        if routing_rule and routing_rule.assignee_id
        else config.email_to_ticket_assignee
    )
    ticket_company = (
        assignee.company
        if routing_rule and assignee and assignee.company_id
        else config.email_to_ticket_company
    )
    ticket_creator = config.email_to_ticket_creator
    creator_source = 'SMTP_DEFAULT'
    if (
        routing_rule
        and assignee
        and ticket_creator.company_id != ticket_company.id
    ):
        ticket_creator = assignee
        creator_source = 'ROUTED_ASSIGNEE'
    return routing_rule, assignee, ticket_company, ticket_creator, creator_source


def _create_ticket(config, message, matched_keywords=None, decided_by=None):
    accepted, skipped = _validated_attachments(message)
    routing_rule, assignee, ticket_company, ticket_creator, creator_source = (
        _resolve_ticket_route(config, message)
    )
    source_metadata = {
        'source': 'EMAIL_TO_TICKET',
        'smtp_configuration_id': config.pk,
        'sender_name': message.sender_name,
        'sender_email': message.sender_email,
        'message_id': message.message_id,
        'routing_rule_id': routing_rule.pk if routing_rule else None,
        'assignment_source': 'SENDER_RULE' if routing_rule else 'SMTP_DEFAULT',
        'company_source': 'ASSIGNEE_COMPANY' if routing_rule else 'SMTP_DEFAULT',
        'creator_source': creator_source,
        'matched_keywords': matched_keywords or [],
    }
    with transaction.atomic():
        ticket = Ticket.objects.create(
            title=message.subject,
            description=message.body,
            company=ticket_company,
            created_by=ticket_creator,
            assigned_to=assignee,
            category=Ticket.CATEGORY_OTHER,
            custom_fields_data={'email_to_ticket': source_metadata},
        )
        with FileLock('system_backup.lock', timeout=30):
            for index, (filename, content) in enumerate(accepted):
                attachment = TicketAttachment.objects.create(
                    ticket=ticket,
                    file=ContentFile(content, name=filename),
                    filename=filename,
                    file_size=len(content),
                )
                if index == 0:
                    ticket.attachment = attachment.file
                    ticket.save(update_fields=['attachment'])
        InboundEmailReceipt.objects.update_or_create(
            smtp_configuration=config,
            message_id=message.message_id,
            defaults={
                'sender_name': message.sender_name,
                'sender_email': message.sender_email,
                'subject': message.subject,
                'status': InboundEmailReceipt.STATUS_IMPORTED,
                'details': (
                    f'Imported as Ticket #{ticket.pk}; '
                    f'assignee: {assignee.username if assignee else "Unassigned"}; '
                    f'company: {ticket_company.name}; '
                    f'matched keywords: {", ".join(matched_keywords or []) or "not required"}; '
                    f'accepted attachments: {len(accepted)}.'
                    + (f" Skipped: {'; '.join(skipped)}" if skipped else '')
                ),
                'ticket': ticket,
                'body': message.body,
                'matched_keywords': matched_keywords or [],
                'decided_by': decided_by,
                'decided_at': timezone.now() if decided_by else None,
            },
        )
    return ticket, skipped


def approve_inbound_email(receipt_id, actor):
    with transaction.atomic():
        receipt = InboundEmailReceipt.objects.select_for_update().select_related(
            'smtp_configuration',
        ).get(pk=receipt_id)
        if receipt.status != InboundEmailReceipt.STATUS_PENDING:
            raise ValueError('This email is no longer waiting for approval.')
        if not receipt.smtp_configuration_id:
            raise ValueError('The source mailbox configuration no longer exists.')
        receipt.smtp_configuration.full_clean()

        attachments = []
        for pending_attachment in receipt.attachments.all():
            with pending_attachment.file.open('rb') as source_file:
                attachments.append({
                    'filename': pending_attachment.filename,
                    'content': source_file.read(),
                    'size': pending_attachment.file_size,
                })
        message = InboundMessage(
            uid=b'',
            message_id=receipt.message_id,
            subject=receipt.subject,
            body=receipt.body,
            sender_name=receipt.sender_name,
            sender_email=receipt.sender_email,
            attachments=attachments,
        )
        ticket, skipped = _create_ticket(
            receipt.smtp_configuration,
            message,
            matched_keywords=receipt.matched_keywords,
            decided_by=actor,
        )
        for pending_attachment in list(receipt.attachments.all()):
            pending_attachment.delete()
    return ticket, skipped


def reject_inbound_email(receipt_id, actor, reason=''):
    with transaction.atomic():
        receipt = InboundEmailReceipt.objects.select_for_update().get(pk=receipt_id)
        if receipt.status != InboundEmailReceipt.STATUS_PENDING:
            raise ValueError('This email is no longer waiting for approval.')
        receipt.status = InboundEmailReceipt.STATUS_REJECTED
        receipt.details = (
            f'Rejected by {actor.username}.'
            + (f' Reason: {reason.strip()}' if reason.strip() else '')
        )
        receipt.decided_by = actor
        receipt.decided_at = timezone.now()
        receipt.save(update_fields=[
            'status', 'details', 'decided_by', 'decided_at', 'processed_at',
        ])
        for pending_attachment in list(receipt.attachments.all()):
            pending_attachment.delete()
    return receipt


def _mark_seen(client, uid):
    try:
        status, _ = client.uid('store', uid, '+FLAGS', '(\\Seen)')
        if status != 'OK':
            logger.warning('IMAP server did not confirm Seen flag for UID %r.', uid)
    except Exception:
        # The queue/receipt is already durable. A flagging failure must not
        # overwrite it as FAILED or strand private staged attachments.
        logger.warning('Unable to mark IMAP UID %r as seen.', uid, exc_info=True)


def _imap_since_date(days_back):
    target = timezone.localdate() - timedelta(days=days_back)
    months = (
        '', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    )
    return f'{target.day:02d}-{months[target.month]}-{target.year}'


def import_email_to_tickets(config):
    result = {
        'success': False,
        'found': 0,
        'pending': 0,
        'imported': 0,
        'skipped': 0,
        'duplicates': 0,
        'failed': 0,
        'error': '',
    }
    now = timezone.now()
    SMTPConfiguration.objects.filter(pk=config.pk).update(last_inbound_check_at=now)

    if not config.is_active or not config.uses_email_to_ticket:
        result['error'] = 'SMTP configuration is not active for Email to Ticket.'
        return result
    try:
        config.full_clean()
        client = imaplib.IMAP4_SSL(config.incoming_host, config.incoming_port, timeout=30)
        client.login(config.username, config.password)
        select_status, _ = client.select(config.incoming_folder)
        if select_status != 'OK':
            raise RuntimeError(f"Unable to select IMAP folder '{config.incoming_folder}'.")

        since_date = _imap_since_date(config.fetch_days_back)
        status, payload = client.uid('search', None, 'UNSEEN', 'SINCE', since_date)
        if status != 'OK':
            raise RuntimeError('IMAP search failed.')
        uids = (payload[0] or b'').split()
        if len(uids) > config.max_emails_per_fetch:
            uids = uids[-config.max_emails_per_fetch:]
        result['found'] = len(uids)

        for uid in uids:
            message = None
            try:
                size_status, size_parts = client.uid('fetch', uid, '(RFC822.SIZE)')
                if size_status == 'OK':
                    size_payload = b' '.join(
                        item[0] if isinstance(item, tuple) else item
                        for item in size_parts
                        if isinstance(item, (tuple, bytes))
                    )
                    size_match = re.search(br'RFC822\.SIZE\s+(\d+)', size_payload)
                    if size_match and int(size_match.group(1)) > MAX_RAW_EMAIL_BYTES:
                        uid_text = uid.decode('ascii', errors='ignore') if isinstance(uid, bytes) else str(uid)
                        InboundEmailReceipt.objects.update_or_create(
                            smtp_configuration=config,
                            message_id=f'imap-uid:{uid_text}'[:512],
                            defaults={
                                'status': InboundEmailReceipt.STATUS_SKIPPED,
                                'details': 'Raw email exceeded the 55 MB safety limit.',
                                'ticket': None,
                            },
                        )
                        result['skipped'] += 1
                        if config.mark_processed_as_read:
                            _mark_seen(client, uid)
                        continue

                fetch_status, message_parts = client.uid('fetch', uid, '(BODY.PEEK[])')
                if fetch_status != 'OK':
                    raise RuntimeError('IMAP fetch failed.')
                raw_email = next(
                    (
                        item[1]
                        for item in message_parts
                        if isinstance(item, tuple) and isinstance(item[1], bytes)
                    ),
                    None,
                )
                if not raw_email:
                    raise RuntimeError('IMAP message body was empty.')
                message = _parse_message(uid, raw_email)

                existing = InboundEmailReceipt.objects.filter(
                    smtp_configuration=config,
                    message_id=message.message_id,
                    status__in=[
                        InboundEmailReceipt.STATUS_IMPORTED,
                        InboundEmailReceipt.STATUS_PENDING,
                        InboundEmailReceipt.STATUS_REJECTED,
                        InboundEmailReceipt.STATUS_SKIPPED,
                    ],
                ).first()
                if existing:
                    result['duplicates'] += 1
                    if config.mark_processed_as_read:
                        _mark_seen(client, uid)
                    continue

                _record_contact(config, message)
                is_issue, matched = _is_issue_message(config, message)
                if not is_issue:
                    if matched == ['system-generated']:
                        skip_details = (
                            'Skipped a TicketSolve-generated message to prevent an email loop.'
                        )
                    else:
                        skip_details = 'Skipped because the subject did not match any issue keyword.'
                    InboundEmailReceipt.objects.update_or_create(
                        smtp_configuration=config,
                        message_id=message.message_id,
                        defaults={
                            'sender_name': message.sender_name,
                            'sender_email': message.sender_email,
                            'subject': message.subject,
                            'body': message.body,
                            'matched_keywords': matched,
                            'status': InboundEmailReceipt.STATUS_SKIPPED,
                            'details': skip_details,
                            'ticket': None,
                        },
                    )
                    result['skipped'] += 1
                    if config.mark_processed_as_read:
                        _mark_seen(client, uid)
                    continue

                receipt, skipped_attachments = _queue_email_for_approval(
                    config,
                    message,
                    matched_keywords=matched,
                )
                result['pending'] += 1
                logger.info(
                    "Queued IMAP message %s for approval as receipt #%s (keywords=%s, skipped_attachments=%s)",
                    message.message_id,
                    receipt.pk,
                    ','.join(matched),
                    len(skipped_attachments),
                )
                if config.mark_processed_as_read:
                    _mark_seen(client, uid)
            except Exception as exc:
                result['failed'] += 1
                logger.exception('Email to Ticket message import failed for UID %r.', uid)
                if message is not None:
                    try:
                        _record_contact(config, message)
                    except Exception:
                        pass
                uid_text = uid.decode('ascii', errors='ignore') if isinstance(uid, bytes) else str(uid)
                failure_message_id = (
                    message.message_id
                    if message is not None
                    else f'imap-uid:{uid_text}'
                )
                InboundEmailReceipt.objects.update_or_create(
                    smtp_configuration=config,
                    message_id=failure_message_id[:512],
                    defaults={
                        'sender_name': message.sender_name if message else '',
                        'sender_email': message.sender_email if message else '',
                        'subject': message.subject if message else '',
                        'status': InboundEmailReceipt.STATUS_FAILED,
                        'details': str(exc)[:2000],
                        'ticket': None,
                    },
                )

        try:
            client.close()
        except imaplib.IMAP4.error:
            pass
        client.logout()
        result['success'] = result['failed'] == 0
        SMTPConfiguration.objects.filter(pk=config.pk).update(
            last_inbound_error='' if result['success'] else f"{result['failed']} message(s) failed.",
        )
    except Exception as exc:
        result['error'] = str(exc)
        SMTPConfiguration.objects.filter(pk=config.pk).update(
            last_inbound_error=str(exc)[:2000],
        )
        logger.exception('Email to Ticket import failed for SMTP configuration %s.', config.pk)
    return result


def import_all_active_email_to_ticket_configs():
    results = []
    configs = SMTPConfiguration.objects.filter(
        is_active=True,
        feature_scope__in=[
            SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            SMTPConfiguration.FEATURE_BOTH,
        ],
    ).select_related(
        'email_to_ticket_company',
        'email_to_ticket_creator',
        'email_to_ticket_assignee',
    )
    for config in configs:
        results.append((config, import_email_to_tickets(config)))
    return results
