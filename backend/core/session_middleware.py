"""Middleware that picks up the frontend's session id from request headers."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.session_context import update_session_id

SESSION_HEADER = "X-Stimma-Session-Id"


class SessionIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get(SESSION_HEADER)
        if session_id:
            await update_session_id(session_id)
        return await call_next(request)
