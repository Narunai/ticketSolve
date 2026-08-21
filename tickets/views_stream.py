import queue
import time
import json
import logging
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import close_old_connections
from .events import register_listener, unregister_listener
from .models import InAppNotification, Ticket

logger = logging.getLogger(__name__)

@login_required
def event_stream_view(request):
    """
    Server-Sent Events (SSE) stream endpoint for live real-time notifications
    and dynamic ticket table updates without reloading the page.
    Supports multi-process Gunicorn through dual-engine (Queue + DB event sync).
    Scales smoothly for 30-100+ concurrent real-time connections.
    """
    user = request.user
    listener_queue = register_listener(user)

    def event_generator():
        yield ": sse-stream-connected\n\n"
        
        # Track latest processed IDs to avoid duplicate streaming on connect
        try:
            close_old_connections()
            last_notif = InAppNotification.objects.filter(recipient=user).order_by('-id').first()
            last_notif_id = last_notif.id if last_notif else 0
        except Exception:
            last_notif_id = 0
        
        try:
            close_old_connections()
            if user.is_superuser or getattr(user, 'role', '') in ['SYSTEM_ADMIN', 'SYSTEM_SUB_ADMIN']:
                last_t = Ticket.objects.all().order_by('-id').first()
            elif getattr(user, 'company_id', None):
                last_t = Ticket.objects.filter(company_id=user.company_id).order_by('-id').first()
            else:
                last_t = Ticket.objects.filter(created_by=user).order_by('-id').first()
            last_ticket_id = last_t.id if last_t else 0
        except Exception:
            last_ticket_id = 0

        stream_loop = 0
        MAX_STREAM_CYCLES = 30  # ~60-75 seconds per connection cycle; EventSource auto-reconnects seamlessly
        try:
            while stream_loop < MAX_STREAM_CYCLES:
                stream_loop += 1
                
                # 1. In-memory event queue check (Instant 0ms delivery if on same worker)
                try:
                    msg = listener_queue.get(timeout=2.5)
                    yield msg
                except queue.Empty:
                    pass

                # 2. Database Sync (Cross-worker multi-process sync)
                # Free idle DB connection before querying
                close_old_connections()
                try:
                    new_notifs = list(InAppNotification.objects.filter(
                        recipient=user,
                        id__gt=last_notif_id
                    ).select_related('ticket', 'actor').order_by('id')[:10])

                    for notif in new_notifs:
                        last_notif_id = max(last_notif_id, notif.id)
                        unread_count = InAppNotification.objects.filter(recipient=user, is_read=False).count()
                        notif_payload = {
                            'id': notif.id,
                            'recipient_id': user.id,
                            'event_type': notif.event_type,
                            'title': notif.title,
                            'message': notif.message,
                            'unread_count': unread_count,
                            'created_at': notif.created_at.strftime('%d %b %Y, %H:%M') if notif.created_at else '',
                            'ticket_id': notif.ticket_id,
                            'open_url': f'/notifications/{notif.id}/open/',
                        }
                        yield f"event: notification_created\ndata: {json.dumps(notif_payload, default=str)}\n\n"
                except Exception as e:
                    logger.debug(f"[SSE] Error checking new notifications: {e}")

                # Check for new tickets visible to this user
                try:
                    ticket_qs = Ticket.objects.filter(id__gt=last_ticket_id)
                    if not (user.is_superuser or getattr(user, 'role', '') in ['SYSTEM_ADMIN', 'SYSTEM_SUB_ADMIN']):
                        if getattr(user, 'company_id', None):
                            ticket_qs = ticket_qs.filter(company_id=user.company_id)
                        else:
                            ticket_qs = ticket_qs.filter(created_by=user)

                    new_tickets = list(ticket_qs.select_related('company', 'created_by', 'assigned_to', 'ticket_category', 'module_category').order_by('id')[:10])
                    for ticket in new_tickets:
                        last_ticket_id = max(last_ticket_id, ticket.id)
                        cat_name = ticket.ticket_category.name if ticket.ticket_category else (ticket.get_category_display() if hasattr(ticket, 'get_category_display') else str(ticket.category or 'General'))
                        ticket_payload = {
                            'id': ticket.id,
                            'title': ticket.title,
                            'priority': ticket.priority,
                            'priority_display': ticket.get_priority_display(),
                            'status': ticket.status,
                            'status_display': ticket.get_status_display(),
                            'category': cat_name,
                            'module_category': ticket.module_category.name if ticket.module_category else None,
                            'company_id': ticket.company_id,
                            'company_name': ticket.company.name if ticket.company else 'Central Administration',
                            'created_by': ticket.created_by.username if ticket.created_by else 'System',
                            'assigned_to': ticket.assigned_to.username if ticket.assigned_to else 'Not Assigned',
                            'created_at': ticket.created_at.strftime('%d %b %Y, %H:%M') if ticket.created_at else timezone.now().strftime('%d %b %Y, %H:%M'),
                            'url': f'/ticket/{ticket.id}/',
                            'edit_url': f'/ticket/{ticket.id}/edit/',
                        }
                        yield f"event: ticket_created\ndata: {json.dumps(ticket_payload, default=str)}\n\n"
                except Exception as e:
                    logger.debug(f"[SSE] Error checking new tickets: {e}")

                # Send keep-alive heartbeat every 14 seconds
                if stream_loop % 7 == 0:
                    yield ": ping\n\n"

            # Gracefully cycle stream connection
            yield ": cycle-reconnect\n\n"

        except GeneratorExit:
            logger.debug(f"[SSE] Client closed connection for user {user.username}")
        except Exception as e:
            logger.warning(f"[SSE] Exception in stream for user {user.username}: {e}")
        finally:
            unregister_listener(listener_queue)

    response = StreamingHttpResponse(
        event_generator(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache, no-transform'
    response['X-Accel-Buffering'] = 'no'
    response['Connection'] = 'keep-alive'
    return response
