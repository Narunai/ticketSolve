import queue
import logging
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from .events import register_listener, unregister_listener

logger = logging.getLogger(__name__)

@login_required
def event_stream_view(request):
    """
    Server-Sent Events (SSE) stream endpoint for live real-time notifications
    and dynamic ticket table updates without reloading the page.
    """
    listener_queue = register_listener(request.user)

    def event_generator():
        yield ": sse-stream-connected\n\n"
        try:
            while True:
                try:
                    # Wait up to 15 seconds for a message
                    msg = listener_queue.get(timeout=15.0)
                    yield msg
                except queue.Empty:
                    # Send keep-alive heartbeat to prevent timeouts
                    yield ": ping\n\n"
        except GeneratorExit:
            logger.debug(f"[SSE] Client closed connection for user {request.user.username}")
        except Exception as e:
            logger.warning(f"[SSE] Exception in stream for user {request.user.username}: {e}")
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
