"""Pydantic models for API requests and responses."""
from typing import Optional, List
from pydantic import BaseModel, Field


class MediaMarkerInfo(BaseModel):
    id: int
    name: str
    icon_svg: str
    color: str


class TagResponse(BaseModel):
    id: int
    tag: str
    created_at: str
    usage_count: Optional[int] = None

    class Config:
        from_attributes = True


class MediaItemResponse(BaseModel):
    id: int
    # Stable browser identity when this Media is a committed Asset Revision.
    asset_id: Optional[int] = None
    media_id: Optional[int] = None
    revision_id: Optional[int] = None
    file_hash: str
    file_path: str
    file_size: int
    file_format: str
    width: int
    height: int
    has_alpha: Optional[bool] = None
    megapixels: float
    duration: Optional[float]
    # Audio-specific metadata
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None
    audio_bit_depth: Optional[int] = None
    audio_bitrate: Optional[int] = None
    audio_codec: Optional[str] = None
    created_date: Optional[str]
    modified_date: Optional[str]
    indexed_date: str
    vlm_caption: Optional[str]
    raw_metadata: Optional[str]
    extracted_prompt: Optional[str]
    generation_metadata: Optional[str]
    has_editor_sidecar: bool = False
    keywords: List[str]
    has_clip_embedding: bool
    has_vlm_caption: bool
    vlm_error: Optional[str]
    similarity_score: Optional[float] = None
    auto_delete_at: Optional[str] = None
    deleted_at: Optional[str] = None
    markers: List[MediaMarkerInfo] = []
    tags: List[TagResponse] = []
    # Processing status fields for UI display
    metadata_status: Optional[str] = None
    clip_status: Optional[str] = None
    face_detection_status: Optional[str] = None
    vlm_caption_status: Optional[str] = None
    vlm_extract_status: Optional[str] = None
    llm_keywords_status: Optional[str] = None
    # Structured media (sets/grids) member count and title
    member_count: Optional[int] = None
    title: Optional[str] = None
    # Visibility fields
    superseded_by: Optional[int] = None
    is_hidden: Optional[bool] = None

    class Config:
        from_attributes = True


class MediaListResponse(BaseModel):
    items: List[MediaItemResponse]
    total: int
    page: int
    page_size: int
    reference_ids: Optional[List[int]] = None  # IDs used for similarity search


class MediaIndexResponse(BaseModel):
    media_id: int
    index: int
    total: int


class SimilaritySearchRequest(BaseModel):
    media_id: int
    top_k: Optional[int] = 100


class StatsResponse(BaseModel):
    total_items: int
    total_with_embeddings: int
    total_with_captions: int
    total_size_bytes: int


class LoraSelection(BaseModel):
    lora: str
    weight: float = 1.0
    enabled: bool = True


class LoraPairSelection(BaseModel):
    """Selection of a paired LoRA (high/low noise) for video generation."""
    name: str
    high_noise_path: str
    low_noise_path: str


class PromptMetadata(BaseModel):
    """
    Metadata about prompt enhancement settings.
    Stored with the generated image so it can be restored when using "generate more".
    """
    original_prompt: str
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    auto_improve_enabled: Optional[bool] = False
    auto_improve_instructions: Optional[str] = None
    translate_enabled: Optional[bool] = False
    translate_language: Optional[str] = None
    json_mode_enabled: Optional[bool] = False


class GenerationJobRequest(BaseModel):
    """Request to submit a generation job.

    All jobs require a tool_id. ``parameters`` is a single schema-driven dict
    matching the tool's ``parameter_schema`` — it holds everything: prompt,
    input_images, mask, width, height, seed, steps, cfg, loras, etc.
    """
    tool_id: str  # Required - full tool ID (provider:tool_id)
    folder_path: str
    task_type: str  # Task type from tool descriptor

    # Single schema-driven dict from tool's parameter_schema
    # (prompt, input_images, mask, width, height, seed, steps, cfg, loras, etc.)
    parameters: dict = {}

    # Job metadata
    auto_delete_duration: Optional[str] = "24h"
    generator_instance_id: Optional[str] = None
    preset_id: Optional[int] = None
    prompt_metadata: Optional[PromptMetadata] = None
    prompt_options: Optional[dict] = None
    prompt_preload: Optional[dict] = None
    prompt_preloads: Optional[List[dict]] = None
    auto_marker_ids: Optional[List[int]] = None
    project_id: Optional[int] = None  # Project to associate generated media with
    forever_work_reserved: Optional[bool] = None


class BatchSetInput(BaseModel):
    """Reference to a set for batch processing."""
    set_id: int  # Media ID of the set


class BatchJobRequest(BaseModel):
    """Request to submit a batch of generation jobs from a set.

    When a set is provided for an input, the system expands it and runs
    jobs for each item. Results are collected into an output set.
    """
    tool_id: str  # Required - full tool ID (provider:tool_id)
    folder_path: str
    task_type: str  # Task type from tool descriptor

    # Single schema-driven dict from tool's parameter_schema.
    # Values can be BatchSetInput for set-based inputs.
    parameters: dict = {}

    # Job metadata
    auto_delete_duration: Optional[str] = "24h"
    generator_instance_id: Optional[str] = None
    preset_id: Optional[int] = None
    prompt_metadata: Optional[PromptMetadata] = None
    prompt_options: Optional[dict] = None
    prompt_preload: Optional[dict] = None
    prompt_preloads: Optional[List[dict]] = None
    auto_marker_ids: Optional[List[int]] = None
    project_id: Optional[int] = None  # Project to associate generated media with
    forever_work_reserved: Optional[bool] = None

    # Batch-specific options
    output_set_title: Optional[str] = None  # Title for the output set


class BatchJobResponse(BaseModel):
    """Response when submitting a batch of jobs."""
    batch_id: str
    total_jobs: int
    job_ids: List[int]


class MediaBatchInput(BaseModel):
    """The batched media slot for a media-batch submission.

    ``field`` is the tool's media parameter name (e.g. ``input_images`` or
    ``input_videos``). ``media_ids`` is the flat list of library media items;
    the tool runs once per item.
    """
    field: str
    media_ids: List[int]


class MediaBatchJobRequest(BaseModel):
    """Request to submit a media-batch: run a tool once per item in one media slot.

    Unlike ``BatchJobRequest`` (which expands a ``.stimmaset.json``), this sources
    the batch directly from media IDs. Each run reuses ``parameters`` plus any
    ``constant_inputs`` (constant media slots), and applies uniform batch-safe
    ``prep`` to the batched item. Outputs stay as individual library assets and are
    grouped for presentation only (no output set is created).
    """
    tool_id: str  # Required - full tool ID (provider:tool_id)
    folder_path: str
    task_type: str

    # The batched media slot (one slot, N items → N runs).
    batch_input: MediaBatchInput

    # Constant media slots that are the same for every run, keyed by field name.
    # Values are media IDs (resolved to paths server-side).
    constant_inputs: dict = Field(default_factory=dict)

    # Non-media parameters shared by every run (prompt, steps, cfg, seed, loras, ...).
    parameters: dict = Field(default_factory=dict)

    # Uniform batch-safe prep applied to each batched item before submission.
    # Recognized keys: scale, flip, preprocessor, preprocessor_params,
    # extend_padding, extend_bg_color. (No paint/mask — those are per-item.)
    prep: Optional[dict] = None

    # Job metadata
    auto_delete_duration: Optional[str] = "24h"
    generator_instance_id: Optional[str] = None
    preset_id: Optional[int] = None
    prompt_metadata: Optional[PromptMetadata] = None
    prompt_options: Optional[dict] = None
    prompt_preload: Optional[dict] = None
    prompt_preloads: Optional[List[dict]] = None
    auto_marker_ids: Optional[List[int]] = None
    project_id: Optional[int] = None
    forever_work_reserved: Optional[bool] = None


class GenerationJobResponse(BaseModel):
    id: int
    status: str
    generator_type: str
    generator_name: str
    model_name: str
    parameters: str
    folder_path: str
    created_at: str
    assigned_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    result_media_id: Optional[int]
    error: Optional[str]


class MarkerResponse(BaseModel):
    id: int
    name: str
    icon_svg: str
    color: str
    created_at: str

    class Config:
        from_attributes = True


class TagCreateRequest(BaseModel):
    tags: List[str]  # Array of tag texts to add


class BoardSummaryResponse(BaseModel):
    id: int
    name: str
    project_id: Optional[int] = None
    created_at: str
    updated_at: str
    asset_count: Optional[int] = None

    class Config:
        from_attributes = True


class BoardSectionResponse(BaseModel):
    id: int
    board_id: int
    name: Optional[str] = None
    is_default: bool
    is_collapsed: bool
    display_order: int
    items: List[MediaItemResponse] = []
    item_count: Optional[int] = None
    created_at: str
    updated_at: str


class BoardResponse(BaseModel):
    id: int
    name: str
    project_id: Optional[int] = None
    created_at: str
    updated_at: str
    sections: List[BoardSectionResponse] = []
    asset_count: Optional[int] = None


class BoardCreateRequest(BaseModel):
    name: Optional[str] = ""
    project_id: Optional[int] = None


class BoardUpdateRequest(BaseModel):
    name: Optional[str] = None
    project_id: Optional[int] = None


class ProjectSummaryResponse(BaseModel):
    id: int
    name: str
    created_at: str
    updated_at: str
    chat_count: Optional[int] = None
    board_count: Optional[int] = None
    asset_count: Optional[int] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    root_path: Optional[str] = None
    additional_instructions: Optional[str] = None
    memory: Optional[str] = None
    agent_tool_config: Optional[dict] = None
    default_model_slug: Optional[str] = None
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    chat_count: Optional[int] = None
    board_count: Optional[int] = None
    asset_count: Optional[int] = None


class ProjectCreateRequest(BaseModel):
    name: Optional[str] = ""
    default_model_slug: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    additional_instructions: Optional[str] = None
    memory: Optional[str] = None
    agent_tool_config: Optional[dict] = None
    default_model_slug: Optional[str] = None


class BoardSectionCreateRequest(BaseModel):
    name: Optional[str] = None


class BoardSectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_collapsed: Optional[bool] = None


class BulkMarkerRequest(BaseModel):
    media_ids: List[int]
    marker_id: int
    add: bool = True  # True to add, False to remove


class BulkTagRequest(BaseModel):
    media_ids: List[int]
    tag_texts: List[str] = []  # Tag texts to add
    remove_tag_ids: List[int] = []  # Tag IDs to remove


class BoardAddItemsRequest(BaseModel):
    media_ids: List[int] = Field(default_factory=list)
    asset_ids: List[int] = Field(default_factory=list)
    section_id: Optional[int] = None


class BoardSectionReorderRequest(BaseModel):
    section_ids: List[int]


class BoardMoveItemRequest(BaseModel):
    media_id: Optional[int] = None
    asset_id: Optional[int] = None
    from_section_id: int
    to_section_id: int
    target_index: int


class BoardBulkRemoveRequest(BaseModel):
    media_ids: List[int] = Field(default_factory=list)
    asset_ids: List[int] = Field(default_factory=list)


class BoardBulkMoveRequest(BaseModel):
    media_ids: List[int] = Field(default_factory=list)
    asset_ids: List[int] = Field(default_factory=list)
    to_section_id: int


class BulkDeleteRequest(BaseModel):
    media_ids: List[int]


class RestoreRequest(BaseModel):
    media_id: int


class BulkTrashRequest(BaseModel):
    media_ids: List[int]


# Saved Views models
class SavedViewResponse(BaseModel):
    id: int
    name: str
    filters: dict
    sort_by: str
    display_order: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class SavedViewCreateRequest(BaseModel):
    name: str
    filters: dict
    sort_by: str = 'created_desc'


class SavedViewUpdateRequest(BaseModel):
    name: Optional[str] = None
    filters: Optional[dict] = None
    sort_by: Optional[str] = None


class SavedViewReorderRequest(BaseModel):
    direction: str  # "up" or "down"


# Generation Presets models
class GenerationPresetResponse(BaseModel):
    id: int
    task_type: str
    name: str
    parameters: dict
    last_used_at: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class GenerationPresetCreateRequest(BaseModel):
    task_type: str
    name: str
    parameters: dict


class GenerationPresetUpdateRequest(BaseModel):
    name: Optional[str] = None
    parameters: Optional[dict] = None


# Tools models
class ToolResponse(BaseModel):
    id: int
    name: str
    task_type: str
    category: str
    generator: str
    model: str
    state: dict  # Unified state blob containing all tool settings
    # Legacy fields for backward compatibility (deprecated)
    parameters: dict
    loras: List[dict]
    output_folder: Optional[str]
    pinned: bool
    pin_order: Optional[int]
    created_at: str
    updated_at: str
    last_used_at: Optional[str]
    usage_count: int
    source_media_id: Optional[int]
    is_draft: bool

    class Config:
        from_attributes = True


class ToolCreateRequest(BaseModel):
    name: str
    task_type: str
    generator: str
    model: str
    state: Optional[dict] = None  # Unified state blob (preferred)
    # Legacy fields for backward compatibility (deprecated)
    parameters: dict = {}
    loras: List[dict] = []
    output_folder: Optional[str] = None
    pinned: bool = True  # New tools are pinned by default
    is_draft: bool = False
    source_media_id: Optional[int] = None


class ToolUpdateRequest(BaseModel):
    name: Optional[str] = None
    state: Optional[dict] = None  # Unified state blob (preferred)
    # Legacy fields for backward compatibility (deprecated)
    parameters: Optional[dict] = None
    loras: Optional[List[dict]] = None
    output_folder: Optional[str] = None
    pinned: Optional[bool] = None


class ToolPinRequest(BaseModel):
    pinned: bool


class ToolReorderRequest(BaseModel):
    tool_ids: List[int]  # Ordered list of pinned tool IDs


class ToolDirectoryItem(BaseModel):
    """A template from the directory for creating a new tool."""
    id: str  # e.g., "comfyui:qwen-image:text-to-image"
    name: str  # Display name, e.g., "Qwen Image"
    task_type: str
    category: str
    generator: str
    model: str
    default_parameters: dict
    description: Optional[str] = None


class ToolFromDirectoryRequest(BaseModel):
    template_id: str  # ID from ToolDirectoryItem
    name: Optional[str] = None  # Custom name, or use template name
    pinned: Optional[bool] = True  # Whether to pin to sidebar (defaults to True)


class StructuredContentUpdateRequest(BaseModel):
    """Request to update structured content (sets, grids) metadata."""
    title: Optional[str] = None  # New title for the set/grid


class FlowResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    project_id: Optional[int] = None
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    inputs: Optional[dict] = None
    program_hash: Optional[str] = None
    execution_state: str
    pending_task_count: int = 0
    # Root phase status counts (pending / computing / awaiting_input / failed /
    # completed / skipped). Drives the Running / Done / Your Turn / Error pill
    # on surfaces that don't open the flow (sidebar, flows landing,
    # project overview) — kept live via the flow_equation_updated WS event.
    root_status_summary: dict[str, int] = {}
    # True when the flow's program failed to build (parse / dry-run preflight)
    # and is currently parked behind a load_error. Forces the status pill to
    # `Error` even when individual equations would otherwise read as
    # `Your Turn` / `Running` from a stale graph.
    has_load_error: bool = False
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None


class FlowCreateRequest(BaseModel):
    name: Optional[str] = ""
    description: Optional[str] = None
    project_id: Optional[int] = None
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    inputs: Optional[dict] = None


class FlowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[int] = None
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    inputs: Optional[dict] = None
    execution_state: Optional[str] = None


class FlowForkRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[int] = None
    inputs: Optional[dict] = None


# Phase 4 — HITL + error tasks

from typing import Any  # noqa: E402 — keep import local to the new block


class FlowTaskResponse(BaseModel):
    """Task row joined with its owning equation. Shared by per-flow and
    cross-flow (global) listing endpoints.

    `task_id` is the composite "{flow_id}:{task_id}" string so the API
    can identify tasks unambiguously across per-flow SQLite files (task
    ids aren't globally unique).
    """
    task_id: str
    task_type: str              # select | approve | error
    status: str                 # pending | resolved | cancelled
    instructions: Optional[str] = None
    payload: Optional[dict] = None
    resolution: Optional[Any] = None
    created_at: str
    resolved_at: Optional[str] = None

    equation_key: str
    equation_type: str
    equation_status: str
    phase_path: List[str] = []
    inputs_hash: Optional[str] = None
    attempt: int = 1
    error: Optional[str] = None
    dependencies: List[str] = []

    downstream_count: int = 0

    flow_id: Optional[int] = None
    flow_name: Optional[str] = None


class TaskResolveRequest(BaseModel):
    """Body for POST /api/tasks/:id/resolve.

    For HITL tasks (select/approve), set `resolution` to the user's
    decision (list of IDs / bool).

    For error tasks, set `action` to one of retry|skip|edit_flow.
    """
    resolution: Optional[Any] = None
    action: Optional[str] = None
    value: Optional[Any] = None


# Phase 5 — Execution control, phase tree, equations, invalidation


class FlowEquationResponse(BaseModel):
    """Single equation row enriched with in-memory state when available."""
    equation_key: str
    equation_type: str
    status: str
    # Human-readable label derived from the equation's type and definition.
    # Falls back to the equation_key when the live graph definition is
    # unavailable. Frontends should prefer this over the raw key for display.
    display_name: Optional[str] = None
    phase_path: List[str] = []
    inputs_hash: Optional[str] = None
    attempt: int = 1
    result: Optional[Any] = None
    result_media_ids: List[int] = []
    execution_duration_ms: Optional[int] = None
    # Pure compute time reported by the tool provider (generation_time from
    # media metadata), excluding tool-side queue wait. Populated only for
    # tool_call equations that produced media; the UI prefers this over
    # execution_duration_ms when displaying per-iteration durations so that
    # batched generations don't inflate later iterations' "how long did it
    # take" with their time spent waiting in the tool's queue.
    compute_duration_ms: Optional[int] = None
    error: Optional[str] = None
    dependencies: List[str] = []
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    invalidated_at: Optional[str] = None
    # Internal scaffolding equations (foreach wrappers, iteration containers,
    # flow_input declarations) are marked so the UI can hide them from the
    # user-facing step list.
    is_scaffolding: bool = False
    # For equation_type == "hitl": the subtype (select/approve)
    # and, for `select`, the pick count. Lets the UI render past-tense summaries
    # of completed human steps without having to string-match display_name.
    hitl_kind: Optional[str] = None
    hitl_count: Optional[int] = None
    # For equation_type == "tool_call": the full tool id (provider:model:task)
    # and the primary task type. The UI uses these to render the row with the
    # same icon + provider treatment as the tools grid and navigation sidebar.
    tool_id: Optional[str] = None
    task_type: Optional[str] = None
    # For equation_type == "control": the control_kind pulled from the
    # definition (foreach, foreach_iteration, zip_nodes,
    # literal_list, flow_input). The graph viz uses this to hide iteration
    # wrappers on the happy path — they'd otherwise duplicate their child
    # tool/code node.
    control_kind: Optional[str] = None
    # For foreach_iteration wrappers: the equation key of the inner NodeRef
    # whose result this wrapper mirrors. The graph viz uses this to redirect
    # edges through hidden iteration wrappers — a consumer that "depends on
    # Iteration 2" visually depends on Iteration 2's
    # result-producing child instead.
    result_from: Optional[str] = None
    # For equation_type == "code": the agent-authored short title for the
    # logic step (e.g. "Extract Vibe", "Build Prompt"). Rendered as the
    # node title in the graph view, replacing the generic "Code" label.
    # None for other types, or for code equations authored before the field
    # existed.
    description: Optional[str] = None
    # For equation_type == "code": optional secondary line of context the
    # agent can write under the title (e.g. a short sentence explaining
    # what the step's logic does). None when the agent didn't supply one.
    subtitle: Optional[str] = None
    # For helper-created code equations, identifies branchless routing
    # primitives such as switch/filter/partition/take/when/gate so clients can
    # present them as routing steps rather than generic logic.
    routing_kind: Optional[str] = None
    # True when this equation is surfaced by the flow's ``return`` — either
    # the bare returned NodeRef, or one entry in a returned tuple/dict of
    # NodeRefs. The graph viz uses this to draw a synthetic "Output" node on
    # the right, instead of the "any dangling equation is an output" heuristic
    # that used to flag side-effect-only calls (e.g. ``hitl.approve(x)`` whose
    # result isn't consumed) as spurious outputs. Defaults to False so the
    # field is safe to omit for clients / persisted rows that haven't been
    # re-evaluated since the current graph build.
    is_output: bool = False
    # Declared output name from @flow(outputs={...}) when this equation is
    # surfaced by the flow's return value. This lets the UI render named
    # outputs explicitly instead of guessing from the producing step label.
    output_name: Optional[str] = None
    # Declared output type from @flow(outputs={...}) for surfaced outputs.
    # Used by clients for type-specific rendering such as media thumbnails
    # and markdown-formatted text.
    output_type: Optional[str] = None
    # For equation_type == "flow_input": the schema field key
    # (definition.input_name). The Workflow inspect panel uses this to scope
    # its editable input form to the matching schema field, so selecting an
    # input node in the graph offers the same edit affordance the steps-view
    # input card already provides. None for non-flow_input equations.
    input_name: Optional[str] = None
    # For control_kind == "approve": the declared slot count and the
    # approval-instructions string. Surfaced explicitly (not via raw
    # `definition`) so the SlotGroup row can render the instructions strip
    # and "X of N approved" badge without spelunking definition JSON.
    slot_count: Optional[int] = None
    instructions: Optional[str] = None


class FlowPhaseNodeResponse(BaseModel):
    """A node in the phase tree. Recursive via `children`.

    `status_summary` counts equations by status within this phase and its
    descendants — drives the phase tree's roll-up indicators.
    """
    name: str
    path: List[str]
    children: List["FlowPhaseNodeResponse"] = []
    equation_keys: List[str] = []
    # Server-authored user-facing step timeline for this exact phase.
    # Items intentionally mirror the frontend's StepItem payload shape while
    # the graph/detail surfaces continue to use raw equations.
    steps: List[dict] = []
    status_summary: dict = {}
    pending_task_count: int = 0


FlowPhaseNodeResponse.model_rebuild()


class FlowPhaseTreeResponse(BaseModel):
    flow_id: int
    execution_state: str
    root: FlowPhaseNodeResponse
    load_error: Optional[dict] = None


class PhaseInvalidateRequest(BaseModel):
    phase_path: List[str]


class EquationReselectRequest(BaseModel):
    """New resolution for a completed HITL select — a media_id (count=1) or
    a list of media_ids (count>1). Accepting Any keeps the door open for
    non-image select candidates (strings, dicts)."""
    resolution: Any
