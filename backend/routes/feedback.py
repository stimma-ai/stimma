"""
Sidecar API for the feedback / thumbs / crash-report client (WS-F).

The frontend talks only to these routes; this layer owns distribution
gating, consent state, package building, and the cloud submission
(feedback_client.py — UA helper + optional Firebase bearer).

Gating recap (PRIVACY_PLAN §2.5):
- Feedback submissions, thumbs, and crash-report sharing exist only in
  official builds; in source/dev builds those paths are refused here so
  nothing can egress even if the UI gate is bypassed.
"""
import base64
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logging import get_logger
from distribution import get_distribution, is_official

log = get_logger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

CONSENT_VALUES = ("ask", "always", "never")


# ── State ────────────────────────────────────────────────────────────────


@router.get("/state")
async def feedback_state():
    """Everything the frontend needs to gate the feedback surfaces."""
    from config import get_settings
    import crash_reports

    settings = get_settings()
    return {
        "distribution": get_distribution(),
        "thumbs_consent": settings.feedback.thumbs_consent,
        "crash_consent": settings.feedback.crash_reports,
        "coachmark_shown": settings.feedback.coachmark_shown,
        "pending_crashes": len(crash_reports.list_pending()) if is_official() else 0,
    }


class UpdateConsentRequest(BaseModel):
    subject: str  # thumbs | crash
    value: str    # ask | always | never


@router.patch("/consent")
async def update_consent(req: UpdateConsentRequest):
    """Settings → Privacy three-state for thumbs and crash reports."""
    if not is_official():
        raise HTTPException(status_code=403, detail="Not available in source builds")
    if req.subject not in ("thumbs", "crash") or req.value not in CONSENT_VALUES:
        raise HTTPException(status_code=400, detail="Invalid consent subject or value")

    from config import get_settings
    import config_writer

    settings = get_settings()
    section = settings.feedback.model_dump()
    key = "thumbs_consent" if req.subject == "thumbs" else "crash_reports"
    section[key] = req.value
    config_writer.patch_global_section("feedback", section)
    setattr(settings.feedback, key, req.value)

    if req.subject == "crash" and req.value == "never":
        import crash_reports
        crash_reports.discard_pending()

    from telemetry import get_telemetry_client
    get_telemetry_client().track(
        "feedback_consent_set",
        {"subject": req.subject, "value": req.value},
        category="feedback",
    )
    return {"status": "success", "subject": req.subject, "value": req.value}


@router.post("/coachmark-shown")
async def mark_coachmark_shown():
    """Persist the one-time post-onboarding coachmark flag."""
    from config import get_settings
    import config_writer

    settings = get_settings()
    section = settings.feedback.model_dump()
    section["coachmark_shown"] = True
    config_writer.patch_global_section("feedback", section)
    settings.feedback.coachmark_shown = True
    return {"status": "success"}


# ── Submission ───────────────────────────────────────────────────────────


class PackageSource(BaseModel):
    type: str  # 'chat' | 'prompt_agent'
    chat_id: Optional[int] = None
    conversation: Optional[Dict[str, Any]] = None  # prompt-agent payload


class SubmitFeedbackRequest(BaseModel):
    kind: str  # 'feedback' | 'thumbs'
    message: str = ""
    thumb: Optional[str] = None              # 'up' | 'down'
    agent_context: Optional[str] = None      # 'main' | 'flow' | 'prompt-agent'
    include_logs: bool = False
    screenshot: Optional[str] = None         # data URL (image/png)
    package: Optional[PackageSource] = None


def _decode_screenshot(data_url: str) -> bytes:
    try:
        if "," in data_url:
            data_url = data_url.split(",", 1)[1]
        return base64.b64decode(data_url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid screenshot data")


@router.post("/submit")
async def submit(req: SubmitFeedbackRequest):
    """Build attachments and submit to the cloud feedback API."""
    if req.kind not in ("feedback", "thumbs"):
        raise HTTPException(status_code=400, detail="kind must be feedback or thumbs")
    if not is_official():
        raise HTTPException(
            status_code=403,
            detail="Feedback sharing is disabled in source builds",
        )
    if req.thumb is not None and req.thumb not in ("up", "down"):
        raise HTTPException(status_code=400, detail="thumb must be up or down")
    if req.agent_context is not None and req.agent_context not in (
        "main", "flow", "prompt-agent"
    ):
        raise HTTPException(status_code=400, detail="Invalid agent_context")

    # Thumbs never egress under a recorded 'never' consent (the UI also
    # gates; this is the backstop).
    if req.kind == "thumbs":
        from config import get_settings
        if get_settings().feedback.thumbs_consent == "never":
            raise HTTPException(
                status_code=403,
                detail="Thumbs feedback is turned off in Settings",
            )

    logs_bytes = None
    if req.include_logs:
        from log_tail import tail_log_text
        logs_bytes = tail_log_text().encode("utf-8")

    screenshot_bytes = None
    if req.screenshot:
        screenshot_bytes = _decode_screenshot(req.screenshot)

    package_bytes = None
    chat_name = None
    if req.package:
        if req.package.type == "chat" and req.package.chat_id:
            from sqlalchemy import select
            from core.profile_context import get_current_profile
            from database import Chat
            from database_registry import get_database_registry
            from feedback_package import build_chat_package
            db = get_database_registry().get_database(get_current_profile())
            async with db.async_session_maker() as session:
                try:
                    package_bytes = await build_chat_package(
                        req.package.chat_id,
                        session,
                        agent_context=req.agent_context or "main",
                    )
                except ValueError:
                    raise HTTPException(status_code=404, detail="Chat not found")
                # The conversation's name at the time of rating, for the
                # admin inbox listing. Trimmed; omitted when unnamed.
                result = await session.execute(
                    select(Chat.name).where(Chat.id == req.package.chat_id)
                )
                chat_name = (result.scalar_one_or_none() or "").strip()[:256] or None
        elif req.package.type == "prompt_agent" and req.package.conversation:
            from feedback_package import build_prompt_agent_package
            package_bytes = build_prompt_agent_package(req.package.conversation)
        else:
            raise HTTPException(status_code=400, detail="Invalid package source")

    from feedback_client import submit_feedback, FeedbackSubmitError
    try:
        feedback_id = await submit_feedback(
            kind=req.kind,
            message=req.message or "",
            thumb=req.thumb,
            agent_context=req.agent_context,
            chat_name=chat_name,
            package=package_bytes,
            logs=logs_bytes,
            screenshot=screenshot_bytes,
        )
    except FeedbackSubmitError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=str(e))
    except Exception:
        log.exception("feedback submission failed")
        raise HTTPException(status_code=502, detail="Could not reach the feedback service")

    from telemetry import get_telemetry_client
    props: Dict[str, Any] = {
        "kind": req.kind,
        "hasLogs": logs_bytes is not None,
        "hasScreenshot": screenshot_bytes is not None,
        "hasPackage": package_bytes is not None,
    }
    if req.thumb:
        props["thumb"] = req.thumb
    if req.agent_context:
        props["agentContext"] = req.agent_context
    get_telemetry_client().track("feedback_submitted", props, category="feedback")

    return {"status": "success", "id": feedback_id}


# ── Crash reports ────────────────────────────────────────────────────────


@router.get("/crashes/pending")
async def pending_crashes():
    """Pending crash report summaries (always [] in source builds)."""
    if not is_official():
        return {"reports": [], "consent": "ask"}
    import crash_reports
    from config import get_settings
    return {
        "reports": crash_reports.list_pending(),
        "consent": get_settings().feedback.crash_reports,
    }


class CrashDecisionRequest(BaseModel):
    action: str  # 'dismiss' | 'send' | 'send_always'


@router.post("/crashes/decision")
async def crash_decision(req: CrashDecisionRequest):
    """One decision covers the whole pending batch."""
    if not is_official():
        raise HTTPException(
            status_code=403, detail="Crash reports are disabled in source builds"
        )
    if req.action not in ("dismiss", "send", "send_always"):
        raise HTTPException(status_code=400, detail="Invalid action")

    import crash_reports

    if req.action == "dismiss":
        discarded = crash_reports.discard_pending()
        return {"status": "success", "discarded": discarded}

    if req.action == "send_always":
        from config import get_settings
        import config_writer
        settings = get_settings()
        section = settings.feedback.model_dump()
        section["crash_reports"] = "always"
        config_writer.patch_global_section("feedback", section)
        settings.feedback.crash_reports = "always"
        from telemetry import get_telemetry_client
        get_telemetry_client().track(
            "feedback_consent_set",
            {"subject": "crash", "value": "always"},
            category="feedback",
        )

    # Client-side send throttle (rolling 24h budget / 429 backoff): keep
    # the reports pending and tell the UI so it can show a quiet note.
    if crash_reports.is_send_throttled():
        return {
            "status": "rate_limited",
            "sent": 0,
            "pending": len(crash_reports.list_pending()),
        }

    sent = await crash_reports.send_pending()
    return {"status": "success", "sent": sent}
