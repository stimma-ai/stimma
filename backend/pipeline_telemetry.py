"""
Generation-pipeline telemetry: per-job ``tool_*`` property building and the
per-pipeline ``generation_pipeline_completed`` settle event.

A *pipeline* is one user-initiated generation: the base generation job plus
its post-processing chain (if any). ``generation_pipeline_completed`` fires
exactly once, when the whole pipeline settles:

- chainless jobs settle when the job completes / fails / is cancelled;
- chained jobs settle when the chain run completes, pauses on a failed
  step (-> status ``failed`` + ``failedStepIndex``), or is dismissed while
  running (-> ``cancelled``).

Run correlation: ``runId`` is an ephemeral random UUID minted at job
creation (``_run_id`` in job parameters), carried by the pipeline's
``tool_used/completed/failed/cancelled`` events, its chain-step jobs, and
the settle event. It is never persisted to any library entity.

All identity fields go through the classification helpers — toolRef/
toolSource (tool_ref), modelFamily (model_family), errorType/errorHash
(telemetry_props). Raw tool ids for user-provider tools, raw model strings,
and raw error text never egress.
"""
import json
import uuid
from typing import Any, Dict, List, Optional

from core.logging import get_logger

log = get_logger(__name__)

# Generator instance ids with fixed source attribution. ToolView tabs use a
# per-tab UUID (or the legacy literal), so anything else maps to toolview.
_SOURCE_BY_INSTANCE = {
    "agent": "agent",
    "recipe": "recipe",
}

# job_ids whose pipeline already settled (bounded; telemetry-only state).
_settled_job_ids: set = set()
_MAX_SETTLED = 5000


def new_run_id() -> str:
    """Mint the ephemeral run-correlation UUID for one pipeline."""
    return str(uuid.uuid4())


def reset_for_retry(job_id: int) -> None:
    """Allow a retried job (same row id, new run) to settle a new pipeline."""
    _settled_job_ids.discard(job_id)


def _job_params(job) -> Dict[str, Any]:
    try:
        params = job.parameters
        if isinstance(params, str):
            params = json.loads(params)
        return params if isinstance(params, dict) else {}
    except Exception:
        return {}


def run_id_for_job(job) -> Optional[str]:
    return _job_params(job).get("_run_id")


def tool_mode(tool_id: Optional[str], backend_name: Optional[str]) -> str:
    """``cloud | byoai | local`` from the provider behind the job."""
    blob = f"{tool_id or ''} {backend_name or ''}".lower()
    if "stimma-cloud" in blob:
        return "cloud"
    if blob.strip().startswith("builtin"):
        return "local"
    provider = _provider_for_tool(tool_id)
    if provider is not None:
        ptype = (getattr(provider, "provider_type", "") or "").lower()
        if ptype == "builtin":
            return "local"
    return "byoai"


def _provider_for_tool(tool_id: Optional[str]):
    if not tool_id:
        return None
    try:
        from providers import ProviderRegistry
        registry = ProviderRegistry.get_instance()
        entry = registry.get_tool(tool_id)
        if entry:
            return entry[0]
        # Fall back to the provider-id prefix of the full tool id.
        provider_id = tool_id.rsplit(":", 1)[0] if ":" in tool_id else tool_id
        return registry.get_provider(provider_id)
    except Exception:
        return None


def provider_connection_type(provider) -> Optional[str]:
    """Closed connection-kind enum: ``builtin | stdio | websocket``.

    Same domain as ``tool_provider_added.providerType`` (connection kinds),
    with ``builtin`` for the in-process provider.
    """
    if provider is None:
        return None
    ptype = (getattr(provider, "provider_type", "") or "").lower()
    if ptype == "builtin":
        return "builtin"
    config = getattr(provider, "_config", None)
    kind = (getattr(config, "type", "") or "").lower()
    if kind in ("stdio", "websocket"):
        return kind
    return None


def tool_identity_props(tool_id: Optional[str], backend_name: Optional[str] = None) -> Dict[str, Any]:
    """{toolRef, toolSource, mode, providerType?} for a full tool id."""
    from tool_ref import tool_ref_for

    provider = _provider_for_tool(tool_id)
    provider_id = getattr(provider, "provider_id", None)
    provider_type = getattr(provider, "provider_type", None)
    if provider_id is None and tool_id and ":" in tool_id:
        provider_id = tool_id.rsplit(":", 1)[0]

    tool_ref, tool_source = tool_ref_for(tool_id, provider_id, provider_type)
    props: Dict[str, Any] = {
        "toolRef": tool_ref,
        "toolSource": tool_source,
        "mode": tool_mode(tool_id, backend_name),
    }
    connection_type = provider_connection_type(provider)
    if connection_type:
        props["providerType"] = connection_type
    return props


def tool_job_props(job) -> Dict[str, Any]:
    """The shared per-job property set for tool_used/completed/failed/cancelled."""
    from model_family import model_family

    props: Dict[str, Any] = {
        **tool_identity_props(job.tool_id, job.backend_name),
        "taskType": job.task_type,
        "modelFamily": model_family(job.model_name),
    }
    run_id = run_id_for_job(job)
    if run_id:
        props["runId"] = run_id
    return props


def job_source(job) -> str:
    """``toolview | agent | recipe | forever`` from the job's call path."""
    instance_id = job.generator_instance_id or ""
    fixed = _SOURCE_BY_INSTANCE.get(instance_id)
    if fixed:
        return fixed
    # Forever-mode submissions come through the same ToolView submit route;
    # the queue knows which instances are registered for forever mode.
    try:
        from generation_queue import get_generation_queue
        queue = get_generation_queue()
        clients = queue._forever_mode_clients.get(job.backend_name or "", {})
        if instance_id in clients:
            return "forever"
    except Exception:
        pass
    return "toolview"


def _duration_ms(start, end) -> Optional[int]:
    if not start or not end:
        return None
    try:
        return max(0, int((end - start).total_seconds() * 1000))
    except Exception:
        return None


def chain_step_tool_refs(steps: List[Dict[str, Any]]) -> List[str]:
    """Ordered toolRef list for a chain's steps (verbatim-or-hashed per the
    toolRef rule; in-app filter steps resolve to their builtin tool id)."""
    refs: List[str] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("kind") == "filter":
            tool_id = f"builtin:{step.get('filter_id') or 'filter'}"
        else:
            tool_id = step.get("tool_id")
        identity = tool_identity_props(tool_id)
        if identity.get("toolRef"):
            refs.append(identity["toolRef"])
    return refs


def emit_pipeline_settled(
    job,
    status: str,
    *,
    completed_at=None,
    postprocess_step_count: int = 0,
    postprocess_duration_ms: Optional[int] = None,
    postprocess_tool_refs: Optional[List[str]] = None,
    failed_step_index: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Emit ``generation_pipeline_completed`` once per pipeline (per base job).

    ``status``: completed | failed | cancelled. Chain-step jobs never settle
    a pipeline of their own (they belong to the base job's pipeline).
    """
    try:
        from postprocessing.executor import CHAIN_INSTANCE_ID
        if job.generator_instance_id == CHAIN_INSTANCE_ID:
            return
        if job.id in _settled_job_ids:
            return
        _settled_job_ids.add(job.id)
        if len(_settled_job_ids) > _MAX_SETTLED:
            _settled_job_ids.clear()
            _settled_job_ids.add(job.id)

        from telemetry import get_telemetry_client
        from telemetry_props import classify_tool_error

        params = _job_params(job)
        end = completed_at or job.completed_at
        if end is None:
            from datetime import datetime
            end = datetime.utcnow()
        gen_end = job.completed_at or end
        gen_duration = _duration_ms(job.started_at, gen_end)
        queue_ms = _duration_ms(job.created_at, job.started_at)
        total = _duration_ms(job.created_at, end)

        props: Dict[str, Any] = {
            **tool_job_props(job),
            "isRetry": bool(params.get("_is_retry")),
            "source": job_source(job),
            "status": status,
            "durationMs": total if total is not None else 0,
            "queueMs": queue_ms if queue_ms is not None else 0,
            "genDurationMs": gen_duration if gen_duration is not None else 0,
            "postprocessDurationMs": postprocess_duration_ms or 0,
            "postprocessStepCount": postprocess_step_count,
            "postprocessToolRefs": postprocess_tool_refs or [],
        }
        if not props.get("runId"):
            props["runId"] = new_run_id()
        if job.preset_id:
            from object_hash import salted_hash
            props["presetHash"] = salted_hash(f"preset:{job.preset_id}")
        if failed_step_index is not None:
            props["failedStepIndex"] = failed_step_index
        if status == "failed":
            props["errorType"] = classify_tool_error(error_message or job.error)

        get_telemetry_client().track("generation_pipeline_completed", props, category="generation")
    except Exception:
        log.debug("pipeline telemetry emit failed", exc_info=True)
