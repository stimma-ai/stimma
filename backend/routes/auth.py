"""
API routes for desktop authentication flow.

This module provides endpoints to:
1. Start a localhost callback server for OAuth redirect
2. Poll for callback results
3. The callback server exchanges the code with stimma.cloud
"""
import asyncio
import secrets
import socket
import httpx
from aiohttp import web
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import get_settings
from core.logging import get_logger

log = get_logger(__name__)


def _get_cloud_base_url() -> str:
    """Get the cloud base URL from settings."""
    return get_settings().cloud.base_url


def _html_page(title: str, message: str, is_error: bool = False) -> str:
    """Generate a styled HTML response page matching stimma.ai design."""
    icon_color = "#f87171" if is_error else "#6366f1"
    icon = (
        # Error X icon
        '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>'
        if is_error else
        # Success checkmark icon
        '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>'
    )
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} - Stimma</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #0a0a0a;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #fff;
        }}
        .container {{
            text-align: center;
            padding: 2rem;
            max-width: 400px;
        }}
        .icon {{
            color: {icon_color};
            margin-bottom: 1.5rem;
        }}
        h1 {{
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
        }}
        p {{
            color: #a1a1aa;
            font-size: 1rem;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">{icon}</div>
        <h1>{title}</h1>
        <p>{message}</p>
    </div>
    <script>window.close()</script>
</body>
</html>"""

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Store for pending auth sessions
# session_id -> {state, port, result, completed, runner}
_pending_sessions: dict = {}


class StartAuthResponse(BaseModel):
    session_id: str
    port: int
    state: str
    login_url: str


class AuthResult(BaseModel):
    custom_token: str
    user: dict


@router.post("/start")
async def start_auth() -> StartAuthResponse:
    """
    Start the desktop auth flow.

    Creates a localhost callback server and returns the login URL
    for the system browser.
    """
    session_id = secrets.token_urlsafe(16)
    state = secrets.token_urlsafe(32)

    # Find an available port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]

    # Create the callback handler
    async def handle_callback(request):
        """Handle the OAuth callback redirect from browser."""
        code = request.query.get('code')
        received_state = request.query.get('state')
        error = request.query.get('error')

        session = _pending_sessions.get(session_id)
        if not session:
            return web.Response(
                text=_html_page("Session Expired", "Please close this window and try again.", is_error=True),
                content_type='text/html'
            )

        # Validate state
        if received_state != session['state']:
            session['result'] = {'error': 'State mismatch - possible CSRF attack'}
            session['completed'] = True
            return web.Response(
                text=_html_page("Security Error", "Validation failed. Please close this window and try again.", is_error=True),
                content_type='text/html'
            )

        if error:
            session['result'] = {'error': error}
            session['completed'] = True
            return web.Response(
                text=_html_page("Sign In Failed", f"{error}. You can close this window.", is_error=True),
                content_type='text/html'
            )

        if code:
            # Exchange code for custom token with stimma.cloud
            try:
                exchange_url = f"{_get_cloud_base_url()}/api/auth/desktop/exchange"
                log.info("exchanging code with stimma.cloud", url=exchange_url)

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        exchange_url,
                        json={"code": code},
                        timeout=30.0
                    )

                    log.info("stimma.cloud exchange response", status=response.status_code)

                    if response.status_code == 200:
                        data = response.json()
                        custom_token = data['custom_token']
                        user = data['user']

                        # Backend now owns the full auth flow
                        try:
                            # 1. Exchange custom_token for Firebase tokens
                            from firebase_auth import exchange_custom_token
                            from auth_storage import save_auth_state
                            from cloud_api import fetch_user_account
                            from routes.cloud import connect_cloud_internal

                            tokens = await exchange_custom_token(custom_token)
                            log.info("exchanged custom token for firebase tokens")

                            # 2. Fetch user account from stimma.cloud
                            account = await fetch_user_account(tokens['id_token'])
                            tier = account.get('tier', 'free')
                            credits = account.get('credits', 0)
                            log.info("fetched user account", tier=tier, credits=credits)

                            # 3. Persist auth state
                            save_auth_state({
                                'user': user,
                                'tier': tier,
                                'credits': credits,
                                'refresh_token': tokens['refresh_token'],
                                'id_token': tokens['id_token'],
                                'id_token_expiry': tokens['expiry'],
                            })
                            log.info("saved auth state to disk")

                            # 4. Connect to cloud tools if non-free tier (non-blocking)
                            if tier != 'free':
                                log.info("non-free tier, connecting to stimma cloud")
                                # Don't await - let it connect in the background
                                asyncio.create_task(connect_cloud_internal(tokens['id_token']))

                            # 5. Track sign-in telemetry
                            from telemetry import get_telemetry_client
                            get_telemetry_client().track("cloud_signed_in", {"tier": tier}, category="account")

                            # 6. Re-fetch feature flags with the new identity
                            from feature_flags import get_feature_flags
                            get_feature_flags().refresh()

                            # 7. Return user info to frontend (NOT tokens - backend owns those)
                            session['result'] = {
                                'user': user,
                                'tier': tier,
                                'completed': True
                            }

                        except Exception as auth_error:
                            # If backend auth flow fails, still return success to user
                            # but log the error. User is logged in, just without cloud tools.
                            log.error("backend auth flow failed", error=str(auth_error))
                            session['result'] = {
                                'user': user,
                                'tier': 'free',  # Fallback to free tier
                                'completed': True,
                                'auth_warning': str(auth_error)
                            }

                        session['completed'] = True

                        # Schedule server shutdown
                        asyncio.create_task(_shutdown_session(session_id))

                        return web.Response(
                            text=_html_page("Success!", "You can close this window and return to Stimma."),
                            content_type='text/html'
                        )
                    else:
                        error_data = response.json() if response.content else {}
                        error_msg = error_data.get('error', 'Token exchange failed')
                        log.error("stimma.cloud exchange failed",
                                  status=response.status_code,
                                  error=error_msg,
                                  response_body=response.text[:500] if response.text else None)
                        session['result'] = {'error': error_msg}
                        session['completed'] = True
                        return web.Response(
                            text=_html_page("Sign In Failed", error_msg, is_error=True),
                            content_type='text/html'
                        )
            except Exception as e:
                log.error(f"Token exchange failed: {e}")
                session['result'] = {'error': str(e)}
                session['completed'] = True
                return web.Response(
                    text=_html_page("Sign In Failed", f"Authentication failed: {e}", is_error=True),
                    content_type='text/html'
                )

        session['result'] = {'error': 'No authorization code received'}
        session['completed'] = True
        return web.Response(
            text=_html_page("Sign In Failed", "No authorization code received.", is_error=True),
            content_type='text/html'
        )

    # Set up aiohttp server
    app = web.Application()
    app.router.add_get('/callback', handle_callback)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', port)
    await site.start()

    log.info(f"Started auth callback server on port {port} for session {session_id}")

    # Store the session
    _pending_sessions[session_id] = {
        'state': state,
        'port': port,
        'result': None,
        'completed': False,
        'runner': runner,
    }

    # Set timeout to clean up after 5 minutes
    asyncio.create_task(_cleanup_session_after_timeout(session_id, 300))

    # Build login URL
    login_url = f"{_get_cloud_base_url()}/auth/desktop-login?port={port}&state={state}"

    return StartAuthResponse(
        session_id=session_id,
        port=port,
        state=state,
        login_url=login_url
    )


@router.get("/poll/{session_id}")
async def poll_auth(session_id: str):
    """Poll for auth result."""
    session = _pending_sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session['completed']:
        result = session['result']
        return {"completed": True, **result}

    return {"completed": False}


async def _shutdown_session(session_id: str):
    """Shut down the callback server after a brief delay."""
    await asyncio.sleep(1)  # Give browser time to receive response

    session = _pending_sessions.get(session_id)
    if session and session.get('runner'):
        try:
            await session['runner'].cleanup()
            log.info(f"Shut down auth callback server for {session_id}")
        except Exception as e:
            log.warning(f"Error shutting down callback server: {e}")


async def _cleanup_session_after_timeout(session_id: str, timeout_seconds: int):
    """Clean up session after timeout."""
    await asyncio.sleep(timeout_seconds)

    session = _pending_sessions.pop(session_id, None)
    if session:
        if session.get('runner'):
            try:
                await session['runner'].cleanup()
                log.info(f"Cleaned up timed-out auth session {session_id}")
            except Exception as e:
                log.warning(f"Error cleaning up session: {e}")


@router.get("/status")
async def get_auth_status():
    """Get current auth status.

    Returns authenticated user info if logged in, or unauthenticated status.
    Used by frontend to check login state on startup.
    """
    from auth_storage import load_auth_state

    auth_state = load_auth_state()
    if not auth_state:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "user": auth_state.get('user'),
        "tier": auth_state.get('tier', 'free'),
        "credits": auth_state.get('credits'),
    }


@router.get("/account")
async def get_account_info():
    """Get fresh account info from stimma.cloud.

    Fetches the latest tier and balance info. Use this when displaying
    account details that need to be up-to-date.
    """
    from auth_storage import load_auth_state, save_auth_state
    from firebase_auth import get_valid_id_token
    from cloud_api import fetch_user_account

    auth_state = load_auth_state()
    if not auth_state:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get fresh token
    id_token = await get_valid_id_token()
    if not id_token:
        raise HTTPException(status_code=401, detail="Failed to get valid token")

    try:
        # Fetch fresh account info from stimma.cloud
        account = await fetch_user_account(id_token)

        # Update cached values
        auth_state['tier'] = account.get('tier', 'free')
        auth_state['credits'] = account.get('credits', 0)
        auth_state['createdAt'] = account.get('createdAt')
        save_auth_state(auth_state)

        # Return the full account data from stimma.cloud
        return {
            "tier": account.get('tier', 'free'),
            "tierDisplayName": account.get('tierDisplayName'),
            "credits": account.get('credits', 0),
            "createdAt": account.get('createdAt'),
            "usageWindows": account.get('usageWindows'),
            "usage": account.get('usage'),
            "subscription": account.get('subscription'),
        }
    except Exception as e:
        log.error("failed to fetch account info", error=str(e))
        raise HTTPException(status_code=502, detail="Failed to fetch account info")


@router.post("/logout")
async def logout():
    """Clear stored auth and disconnect cloud.

    Removes persisted auth state and disconnects from Stimma Cloud if connected.
    """
    from auth_storage import clear_auth_state
    from routes.cloud import disconnect_cloud_internal

    # Disconnect from cloud first (if connected)
    await disconnect_cloud_internal()

    # Clear stored auth state
    clear_auth_state()

    from telemetry import get_telemetry_client
    get_telemetry_client().track("cloud_signed_out", category="account")

    # Re-fetch feature flags without the signed-in identity
    from feature_flags import get_feature_flags
    get_feature_flags().refresh()

    log.info("user logged out")

    return {"success": True}
