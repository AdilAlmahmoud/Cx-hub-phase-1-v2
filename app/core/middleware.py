"""
Request ID middleware — Phase 4.

Adds an X-Request-ID header to every response.
If the incoming request already has an X-Request-ID header, that value
is reused (pass-through for clients that set their own trace IDs).
Otherwise a fresh UUID4 is generated.

This enables log correlation: every structured log entry that uses
`get_logger(__name__)` can be extended to carry the request ID.
"""
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique X-Request-ID to every request/response pair."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        # Store on request state so routes/services can access it if needed
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
