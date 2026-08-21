import json
import queue
import threading
import logging
from typing import Dict, Any, Generator

logger = logging.getLogger(__name__)

# Thread-safe pub-sub memory broker for SSE streaming
_lock = threading.Lock()
_listeners = []  # List of dicts: {'queue': Queue, 'user_id': int, 'role': str, 'company_id': int, 'is_superuser': bool}

def register_listener(user) -> queue.Queue:
    """Register a new SSE stream listener for the authenticated user."""
    q = queue.Queue(maxsize=50)
    company_id = user.company_id if hasattr(user, 'company_id') else None
    listener = {
        'queue': q,
        'user_id': user.id,
        'role': getattr(user, 'role', 'CLIENT_USER'),
        'company_id': company_id,
        'is_superuser': getattr(user, 'is_superuser', False),
    }
    with _lock:
        _listeners.append(listener)
    logger.debug(f"[SSE] Registered listener for user {user.username} (Total: {len(_listeners)})")
    return q

def unregister_listener(q: queue.Queue):
    """Unregister an SSE stream listener when client disconnects."""
    with _lock:
        to_remove = [l for l in _listeners if l['queue'] is q]
        for l in to_remove:
            _listeners.remove(l)
    logger.debug(f"[SSE] Unregistered listener (Remaining: {len(_listeners)})")

def is_user_authorized_for_event(listener: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> bool:
    """Multi-tenant security check for SSE events."""
    # Private in-app notifications must ONLY go to their intended recipient
    if event_type == 'notification_created':
        target_recipient_id = payload.get('recipient_id')
        if target_recipient_id is not None:
            return listener['user_id'] == target_recipient_id
        return False

    if listener['is_superuser'] or listener['role'] in ['SYSTEM_ADMIN', 'SYSTEM_SUB_ADMIN']:
        return True

    event_company_id = payload.get('company_id')
    if event_company_id is not None:
        if listener['company_id'] != event_company_id:
            return False

    # Check internal comment permission
    if event_type == 'comment_created' and payload.get('is_internal'):
        if listener['role'] not in ['SYSTEM_ADMIN', 'SYSTEM_SUB_ADMIN', 'CLIENT_ADMIN', 'CLIENT_STAFF']:
            return False

    return True

def broadcast_event(event_type: str, payload: Dict[str, Any]):
    """Broadcast an event to all authorized active listeners."""
    msg = f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"
    with _lock:
        current_listeners = list(_listeners)

    for listener in current_listeners:
        if is_user_authorized_for_event(listener, event_type, payload):
            try:
                listener['queue'].put_nowait(msg)
            except queue.Full:
                # If queue is full (stale connection), drain one item to avoid blocking
                try:
                    listener['queue'].get_nowait()
                    listener['queue'].put_nowait(msg)
                except Exception:
                    pass
