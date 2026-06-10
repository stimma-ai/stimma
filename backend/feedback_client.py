"""
Cloud feedback submission client.

Talks to the stimma-cloud feedback API:

    POST {cloud.base_url}/api/feedback            -> {id, uploadUrls}
    PUT  <presigned R2 URL per requested asset>
    POST {cloud.base_url}/api/feedback/:id/complete

Identity: every request carries the Stimma User-Agent (user_agent.py — the
single sanctioned install-id egress). Signed-in submissions also carry the
Firebase bearer token; anonymous is fine (the server keys on the UA).

This is an explicit user-initiated act: it works under DO_NOT_TRACK and in
dev builds (menu feedback, D13 — the server stamps branch 'dev' from the UA
so source-build reports are never mistaken for the official fleet).
"""
from typing import Dict, Optional

import httpx

from core.logging import get_logger

log = get_logger(__name__)

SUBMIT_TIMEOUT_SECONDS = 30.0
UPLOAD_TIMEOUT_SECONDS = 300.0  # packages can be up to 100 MB


class FeedbackSubmitError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


async def submit_feedback(
    *,
    kind: str,
    message: str,
    thumb: Optional[str] = None,
    agent_context: Optional[str] = None,
    error_hash: Optional[str] = None,
    package: Optional[bytes] = None,
    logs: Optional[bytes] = None,
    screenshot: Optional[bytes] = None,
    crash: Optional[bytes] = None,
) -> str:
    """Submit one feedback row + its assets. Returns the feedback id."""
    from config import get_settings
    from user_agent import ua_headers

    assets: Dict[str, bytes] = {}
    if package is not None:
        assets["package"] = package
    if logs is not None:
        assets["logs"] = logs
    if screenshot is not None:
        assets["screenshot"] = screenshot
    if crash is not None:
        assets["crash"] = crash

    base_url = get_settings().cloud.base_url.rstrip("/")
    headers = dict(ua_headers())

    # Firebase bearer when signed in (optional — anonymous is fine).
    try:
        from firebase_auth import get_valid_id_token
        token = await get_valid_id_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass

    body = {
        "kind": kind,
        "message": message,
        "wants": {asset: True for asset in assets},
    }
    if thumb:
        body["thumb"] = thumb
    if agent_context:
        body["agentContext"] = agent_context
    if error_hash:
        body["errorHash"] = error_hash

    async with httpx.AsyncClient(timeout=httpx.Timeout(SUBMIT_TIMEOUT_SECONDS)) as client:
        resp = await client.post(f"{base_url}/api/feedback", json=body, headers=headers)
        if resp.status_code == 429:
            raise FeedbackSubmitError(
                "Daily feedback limit reached — try again tomorrow.", 429
            )
        if resp.status_code >= 400:
            raise FeedbackSubmitError(
                f"Feedback submission failed ({resp.status_code})", resp.status_code
            )
        data = resp.json()
        feedback_id = data["id"]
        upload_urls = data.get("uploadUrls") or {}

    # Upload assets straight to R2 via the presigned PUTs.
    async with httpx.AsyncClient(timeout=httpx.Timeout(UPLOAD_TIMEOUT_SECONDS)) as client:
        for asset, content in assets.items():
            url = upload_urls.get(asset)
            if not url:
                log.warning("feedback: no upload url for asset", asset=asset)
                continue
            put = await client.put(url, content=content)
            if put.status_code >= 400:
                raise FeedbackSubmitError(
                    f"Upload of {asset} failed ({put.status_code})", put.status_code
                )

    async with httpx.AsyncClient(timeout=httpx.Timeout(SUBMIT_TIMEOUT_SECONDS)) as client:
        resp = await client.post(
            f"{base_url}/api/feedback/{feedback_id}/complete", headers=headers
        )
        if resp.status_code >= 400:
            raise FeedbackSubmitError(
                f"Feedback completion failed ({resp.status_code})", resp.status_code
            )

    log.info("feedback submitted", kind=kind, feedback_id=feedback_id)
    return feedback_id
