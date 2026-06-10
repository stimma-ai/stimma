import os
import random
import re
import string
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings

import app_dirs

def generate_profile_id() -> str:
    """Generate a profile ID like 'profile-k3Rm9x'."""
    chars = string.ascii_letters + string.digits
    suffix = ''.join(random.choices(chars, k=6))
    return f'profile-{suffix}'


def expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values.

    Supports ${VAR_NAME} syntax. If the environment variable is not set,
    the placeholder is left as-is.
    """
    if isinstance(value, str):
        # Match ${VAR_NAME} pattern
        pattern = r'\$\{([^}]+)\}'
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(pattern, replace, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def _get_builtin_default_config() -> dict:
    """Return minimal default config structure for first-run initialization."""
    return {
        'profiles': [{
            'id': generate_profile_id(),
            'name': 'Default',
            # Note: database is not specified - it's always stimma_v1.db in the profile folder
            'folders': [{
                'path': '',  # Filled in by ensure_config_exists
                'allow_generate': True,
                'is_uploads_folder': True,
                'uploads_subfolder': 'uploads',
            }],
            'markers': [
                {
                    'name': 'favorite',
                    'icon_svg': 'heroicons:heart',
                    'color': '#ef4444'
                },
                {
                    'name': 'library',
                    'icon_svg': 'heroicons:bookmark',
                    'color': '#3b82f6'
                }
            ]
        }],
        'generators': [],  # Empty - user must configure
        'llms': {
            'agent': {'source': 'auto'},
            'agent-fast': {'source': 'auto'},
        },
        'clip': {
            'model': 'ViT-g-14',
            'pretrained': 'laion2b_s12b_b42k'
        },
        'face_detection': {
            'enabled': True,
            'min_confidence': 0.5,
            'max_faces': 10,
            'parallelism': 2
        },
        'server': {
            'host': '127.0.0.1',
            'port': 8000
        }
    }


def ensure_config_exists() -> Path:
    """
    Ensure config.yaml exists at the OS-specific data directory.
    If not, create directories and default config.

    Returns the path to config.yaml.
    """
    config_path = app_dirs.get_config_path()

    if config_path.exists():
        return config_path

    # Create directories
    data_dir = app_dirs.get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    docs_dir = app_dirs.get_documents_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = app_dirs.get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Generate a profile ID for new installs
    profile_id = generate_profile_id()

    default_profile_dir = app_dirs.get_profile_dir(profile_id)
    default_profile_dir.mkdir(parents=True, exist_ok=True)

    # Try to load from template (preserving comments), fall back to builtin
    template_path = Path(__file__).parent.parent / "config.default.yaml"
    if template_path.exists():
        # Read template as text to preserve comments
        config_text = template_path.read_text()
        # Substitute the empty path placeholder with the Documents folder
        # The template has: path: ""
        # We replace the first occurrence (default profile's folder path)
        config_text = config_text.replace('path: ""', f'path: "{docs_dir}"', 1)
        # Replace profile ID placeholder with generated profile ID.
        # Prefer explicit token, with backward-compatible fallback for older templates.
        config_text, replaced = re.subn(
            r'(^\s*-\s*id:\s*)(["\']?)__PROFILE_ID__\2(\s*$)',
            rf'\1{profile_id}\3',
            config_text,
            count=1,
            flags=re.MULTILINE,
        )

        if not replaced:
            id_patterns = [
                r'(^\s*-\s*id:\s*)(["\']?)default\2(\s*$)',
                r'(^\s*id:\s*)(["\']?)default\2(\s*$)',
            ]
            for pattern in id_patterns:
                config_text, count = re.subn(
                    pattern,
                    rf'\1{profile_id}\3',
                    config_text,
                    count=1,
                    flags=re.MULTILINE,
                )
                replaced += count
                if replaced:
                    break

        if replaced:
            config_path.write_text(config_text)
        else:
            # Template no longer has expected placeholder; guarantee unique profile ID
            # by falling back to builtin config generation.
            default_config = _get_builtin_default_config()
            default_config['profiles'][0]['id'] = profile_id
            if default_config.get('profiles') and default_config['profiles'][0].get('folders'):
                default_config['profiles'][0]['folders'][0]['path'] = str(docs_dir)
            config_path.write_text(yaml.dump(default_config, default_flow_style=False, sort_keys=False))
    else:
        # Fall back to builtin (no comments, but functional)
        default_config = _get_builtin_default_config()
        # Override with the same profile_id we used for the directory
        default_config['profiles'][0]['id'] = profile_id
        if default_config.get('profiles') and default_config['profiles'][0].get('folders'):
            default_config['profiles'][0]['folders'][0]['path'] = str(docs_dir)
        config_path.write_text(yaml.dump(default_config, default_flow_style=False, sort_keys=False))

    return config_path


class LLMEndpointConfig(BaseModel):
    """OpenAI-compatible endpoint configuration."""
    model_config = {"protected_namespaces": ()}

    url: str = ''
    model: str = ''
    api_key: Optional[str] = None
    # Advertised/configured context window for this endpoint. For cloud
    # configs this is stamped in by the resolver from the catalog (already
    # clamped to the client-side cap). For local endpoints it's user-
    # configured via Settings. Default targets a mid-range local setup.
    max_context_tokens: int = 128_000

    # --- Local-endpoint extras (ignored for Stimma Cloud configs) ---
    # Include Stimma's content policy in the system prompt. Helps aligned
    # off-the-shelf models stay within Stimma's actual ToS instead of their
    # stricter defaults; default on. Text is fetched live from the cloud.
    content_policy_enabled: bool = True
    # Extra system-prompt text appended for this endpoint.
    extra_system_prompt: str = ''
    # Fixed JSON merged into every request body (endpoint-specific quirks).
    extra_body: Optional[Dict[str, Any]] = None
    # How thinking is toggled per request on this model:
    # 'reasoning_effort' | 'enable_thinking' | 'think' | 'reasoning_budget' | 'none' | None
    reasoning_method: Optional[str] = None
    # 'auto' (set by the connection profiler) or 'manual' (user override — never
    # overwritten by a re-test).
    reasoning_method_source: str = 'auto'
    # Diagnostics from the last profile, for display only.
    detected_runtime: Optional[str] = None
    reasoning_mode: Optional[str] = None    # 'always' | 'toggleable' | 'none'
    reasoning_output: Optional[str] = None  # 'field' | 'tags' | 'both'
    # When the endpoint was last tested (ISO8601 UTC) and whether it passed —
    # so the UI can show "tested N days ago" without re-testing on every startup.
    last_tested_at: Optional[str] = None
    last_test_passed: Optional[bool] = None

    def get_model(self) -> str:
        return self.model

    def get_api_key(self) -> Optional[str]:
        return self.api_key or "dummy"

    def get_api_base(self) -> Optional[str]:
        return self.url


class LLMRoleConfig(BaseModel):
    """Per-role LLM configuration with two source options.

    Each source config is preserved independently for easy switching:
    - stimma_cloud: Uses Stimma Cloud LLM endpoint
    - endpoint: Uses an OpenAI-compatible custom endpoint
    """
    model_config = {"protected_namespaces": ()}

    source: str = 'auto'  # 'auto' | 'stimma_cloud' | 'endpoint'
    endpoint: Optional[LLMEndpointConfig] = None


# Type alias for LLM configs passed to llm_http
LLMConfig = LLMEndpointConfig


class CaptioningConfig(BaseModel):
    """Captioning task config (uses agent-fast from llms)."""
    enabled: bool = False
    parallelism: int = 20


class AgentLLMParams(BaseModel):
    """LLM invocation parameters for the agent.

    Thinking/reasoning is NOT configured here — each agent entry point decides
    at its call site (see ``agent.v2.llm_options.agent_llm_options``).
    """
    temperature: float = 0.4
    max_tokens: int = 2048
    suppress_thinking: bool = True  # Strip <think>...</think> from thinking models


class CLIPConfig(BaseModel):
    enabled: bool = True
    model: str = "ViT-g-14"
    pretrained: str = "laion2b_s12b_b42k"
    batch_size: int = 50


class FaceDetectionConfig(BaseModel):
    enabled: bool = True
    min_confidence: float = 0.5
    max_faces: int = 10
    parallelism: int = 2


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR


class TelemetryConfig(BaseModel):
    """Anonymous usage telemetry configuration.

    ``enabled`` is tri-state: None = consent undetermined (onboarding not
    completed yet — official builds buffer events locally and send nothing,
    see telemetry.py / D14), True = consented, False = declined.
    """
    enabled: Optional[bool] = None
    install_id: Optional[str] = None  # UUIDv4, auto-generated on first launch
    # Per-install random salt for telemetry object hashes (object_hash.py).
    # Never transmitted.
    hash_salt: Optional[str] = None


class FeedbackConfig(BaseModel):
    """Feedback / thumbs / crash-report consent state.

    ``thumbs_consent`` / ``crash_reports``: ``ask`` (prompt each time),
    ``always`` (send without prompting), ``never`` (suppress + discard).
    Thumbs and crash reports exist only in official builds; the menu
    Feedback item works in all builds (D13).
    """
    thumbs_consent: str = "ask"   # ask | always | never
    crash_reports: str = "ask"    # ask | always | never
    # One-time post-onboarding discovery: logo menu auto-opens with a
    # coachmark on the Feedback item.
    coachmark_shown: bool = False


class ComplianceConfig(BaseModel):
    """Cached compliance-region check (official builds only).

    Populated from GET {cloud}/api/compliance/region before onboarding
    renders; drives the consent toggle default (optin -> off, optout -> on).
    """
    country: Optional[str] = None
    regime: Optional[str] = None  # 'optin' | 'optout'
    checked_at: Optional[str] = None  # ISO8601 UTC


class CloudConfig(BaseModel):
    """Cloud service configuration (stimma.ai)."""
    base_url: str = "https://stimma.ai"


class AgentToolConfig(BaseModel):
    """Tool configuration for the agent."""
    allowed_tools: List[str] = []  # Tools explicitly allowed (no permission prompt)
    denied_tools: List[str] = []  # Tools hidden from agent
    v2_permissions: Dict[str, str] = {}  # V2 tool permissions: tool_name -> "allow" | "deny"


class ProfileAgentConfig(BaseModel):
    """Per-profile agent settings (instructions, tool config)."""
    additional_instructions: str = ""  # Custom instructions added to system prompt
    memory: str = ""  # Persistent cross-session memory (written by user or agent)
    tool_config: AgentToolConfig = AgentToolConfig()  # Per-profile tool allow/deny


class AgentConfig(BaseModel):
    """Agent configuration (LLM comes from settings.llms['agent'])."""
    llm_params: AgentLLMParams = AgentLLMParams()
    max_context_items: int = 50
    # Legacy global agent settings - now per-profile, kept for backward compatibility
    additional_instructions: str = ""  # Custom instructions added to system prompt
    tool_config: AgentToolConfig = AgentToolConfig()  # Global tool allow/deny


class WildcardEntry(BaseModel):
    """A named wildcard list for prompt expansion."""
    name: str
    values: List[str] = []


class PromptSegmentEntry(BaseModel):
    """A named prompt segment — a reusable text block for prompt expansion."""
    name: str
    content: str = ""


class MarkerConfig(BaseModel):
    name: str
    icon_svg: str
    color: str
    id: Optional[str] = None  # Stable config ID (UUID), auto-generated if missing


class FolderConfig(BaseModel):
    path: str
    readonly: bool = False
    allow_generate: bool = False
    is_uploads_folder: bool = False  # Mark as the destination for library uploads
    uploads_subfolder: str = "uploads"  # Subfolder within this folder for uploads
    refresh_interval_seconds: Optional[int] = 300
    markers: List[str] = []  # Auto-apply these markers to items in this folder


class ProfileConfig(BaseModel):
    """Configuration for a user profile with its own database and settings."""
    id: str
    name: str
    database: str  # Database filename (e.g., "stimma.db")
    folders: List[FolderConfig] = []
    markers: List[MarkerConfig] = []
    lora_allowlist: List[str] = []  # Glob patterns - if set, only these are allowed
    lora_denylist: List[str] = []   # Glob patterns - these are denied (allowlist can override)
    wildcards: List[WildcardEntry] = []  # Named wildcard lists for prompt expansion
    prompt_segments: List[PromptSegmentEntry] = []  # Named text blocks for prompt expansion
    pin_hash: Optional[str] = None  # bcrypt hash of profile PIN (None = no PIN required)
    pin_idle_timeout_minutes: int = 30  # Minutes of inactivity before PIN is required again
    agent: ProfileAgentConfig = ProfileAgentConfig()  # Per-profile agent settings


class FrameCountConfig(BaseModel):
    """Configuration for frame count range in video models."""
    min: int = 1
    max: int = 161
    default: int = 81


class TaskModelConfig(BaseModel):
    """Configuration for a model within a specific task."""
    model_config = {"protected_namespaces": ()}

    name: str
    family: str
    workflow: Optional[str] = None  # Maps to workflow class name in registry (ComfyUI)
    model_id: Optional[str] = None  # API model identifier (Gemini, etc.)
    path: Optional[str] = None  # For standard models (t2i, image-to-image)
    default_checkpoint: Optional[str] = None  # Default checkpoint for checkpoint-based models (SDXL)
    text_encoders: Optional[List[str]] = None
    vae: Optional[str] = None
    max_input_images: Optional[int] = None  # For image-to-image tasks
    # Video model specific fields
    unet_high_noise: Optional[str] = None
    unet_low_noise: Optional[str] = None
    clip: Optional[str] = None
    frame_count: Optional[FrameCountConfig] = None
    fps_options: Optional[List[int]] = None
    fps_default: Optional[int] = None
    # Upscale model specific fields
    dit: Optional[str] = None  # DiT model for SeedVR2 upscalers
    # Model-specific defaults (override task defaults)
    default_cfg: Optional[float] = None
    default_steps: Optional[int] = None
    # Feature flags per model
    supports_negative_prompt: Optional[bool] = None
    # Lightning mode LoRAs (statically configured, not user-selectable)
    lora_high_noise: Optional[str] = None
    lora_low_noise: Optional[str] = None


class TaskConfig(BaseModel):
    """Configuration for a task on a generator."""
    models: List[TaskModelConfig] = []


class LoraConfig(BaseModel):
    """Legacy LoRA config - kept for backward compatibility during migration."""
    model_config = {"protected_namespaces": ()}

    name: str
    path: str
    instructions: str = ""
    model_families: Optional[List[str]] = None
    profiles: Optional[List[str]] = None  # If set, only available in these profiles


class LoraFamilyFilterConfig(BaseModel):
    """Allowlist/denylist filters for a model family."""
    family: str
    lora_allowlist: List[str] = []  # Glob patterns - if set, only these are allowed for this family
    lora_denylist: List[str] = []   # Glob patterns - these are denied (allowlist can override)


class LoraDiscoveryConfig(BaseModel):
    """Configuration for auto-discovering LoRAs from ComfyUI."""
    # Global denylist applied to all families (e.g., ai-toolkit/**)
    global_denylist: List[str] = []
    # Per-family filters
    family_filters: List[LoraFamilyFilterConfig] = []


class CheckpointFamilyFilterConfig(BaseModel):
    """Allowlist/denylist filters for checkpoints per model family."""
    family: str
    checkpoint_allowlist: List[str] = []  # Glob patterns
    checkpoint_denylist: List[str] = []   # Glob patterns


class CheckpointDiscoveryConfig(BaseModel):
    """Configuration for auto-discovering checkpoints from ComfyUI."""
    global_denylist: List[str] = []
    family_filters: List[CheckpointFamilyFilterConfig] = []


class GenerationUploadConfig(BaseModel):
    """Configuration for generation-related uploads."""
    upload_directory: str = "/tmp/stimma_uploads"


class GeneratorConfig(BaseModel):
    type: str
    name: str
    address: Optional[str] = None  # For ComfyUI; not needed for API-based generators
    api_key: Optional[str] = None  # For API-based generators (Gemini, etc.)
    tasks: Dict[str, TaskConfig] = {}
    loras: Optional[List[LoraConfig]] = None  # Legacy - use lora_discovery instead
    lora_discovery: Optional[LoraDiscoveryConfig] = None  # Auto-discover LoRAs from ComfyUI
    checkpoint_discovery: Optional[CheckpointDiscoveryConfig] = None  # Auto-discover checkpoints from ComfyUI
    max_concurrent: int = 2  # Maximum concurrent jobs for this backend

    def get_tasks(self) -> Dict[str, TaskConfig]:
        """Get tasks configuration."""
        return self.tasks

    def get_models_for_task(self, task_type: str) -> List[TaskModelConfig]:
        """Get models available for a specific task type."""
        tasks = self.get_tasks()
        if task_type in tasks:
            return tasks[task_type].models
        return []

    def get_all_models(self) -> List[TaskModelConfig]:
        """Get all models across all tasks."""
        all_models = []
        for task_config in self.get_tasks().values():
            all_models.extend(task_config.models)
        return all_models

    def get_model_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get model configuration by name (searches all tasks)."""
        for task_config in self.get_tasks().values():
            for model in task_config.models:
                if model.name == name:
                    # Return as dict for backwards compatibility
                    return {
                        'name': model.name,
                        'family': model.family,
                        'workflow': model.workflow,
                        'model_id': model.model_id,
                        'max_input_images': model.max_input_images,
                    }
        return None


class ToolProviderConfig(BaseModel):
    """Configuration for a tool provider.

    Supports three types:
    - builtin: In-process providers (lightweight tools)
    - stdio: External JSON-RPC subprocess providers
    - websocket: External JSON-RPC websocket providers

    See https://github.com/stimma-ai/stimma-tools-protocol for protocol details.
    """
    id: str  # Unique provider ID
    name: Optional[str] = None  # Human-readable display name (defaults to id if not set)
    type: str  # "builtin", "stdio", or "websocket"
    enabled: bool = True  # Whether this provider is enabled

    # Builtin-specific options
    api_key: Optional[str] = None  # API key, supports ${ENV_VAR} syntax

    # Stdio-specific options
    command: Optional[str] = None
    args: List[str] = []
    working_dir: Optional[str] = None
    env: Dict[str, str] = {}

    # WebSocket-specific options
    url: Optional[str] = None
    auth_token: Optional[str] = None  # Bearer token, supports ${ENV_VAR} syntax
    reconnect_delay: float = 5.0  # Base delay in seconds for reconnection


class Settings(BaseSettings):
    # Profile-based configuration (new structure)
    profiles: List[ProfileConfig] = []

    # Legacy top-level folders/markers (for backward compatibility)
    folders: List[FolderConfig] = []
    media_paths: List[str] = []  # Deprecated, kept for backward compatibility
    markers: List[MarkerConfig] = []

    # Global settings (shared across all profiles)
    developer_mode: bool = False  # Show debug tools and developer options in the UI
    # Dev-only: when set, skills in this directory are the authority for built-in
    # skills — they shadow same-named skills installed in any profile. Lets us edit
    # the stimma-skills repo and pick up changes live, with no publish/install round
    # trip. Set/cleared via `stimma skills dev <path>` / `stimma skills dev --off`.
    dev_skills_dir: Optional[str] = None
    theme: str = "dark"  # UI theme preference: light, dark, system
    disable_update_check: bool = False  # Suppress the daily backend update check
    generators: List[GeneratorConfig] = []
    tool_providers: List[ToolProviderConfig] = []  # External tool providers (JSON-RPC)
    generation: Optional[GenerationUploadConfig] = None  # Upload config for reference images
    # Note: thumbnail_cache_dir removed - now computed via app_dirs.get_thumbnail_cache_dir()
    clip_similarity_count: int = 100
    clip_similarity_threshold: float = 0.75  # For image-to-image similarity
    clip_text_similarity_threshold: float = 0.225  # For text-to-image similarity (CLIP text embeddings have lower scores)

    # LLM configurations: agent (main), agent-fast (prompt enhancement, captioning, etc.)
    # Each role has a source selector (stimma_cloud or custom) and custom config
    llms: Dict[str, LLMRoleConfig] = {}
    default_model: str = 'agent-max'  # Global default model slug for new chats

    # Task-specific settings
    captioning: CaptioningConfig = CaptioningConfig()
    clip: CLIPConfig
    face_detection: FaceDetectionConfig
    server: ServerConfig
    agent: AgentConfig = AgentConfig()
    cloud: CloudConfig = CloudConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    compliance: ComplianceConfig = ComplianceConfig()
    feedback: FeedbackConfig = FeedbackConfig()

    def get_llm_role_config(self, role: str) -> LLMRoleConfig:
        """Get LLM role config by role (agent, agent-fast).

        Returns the full role config with source selection. For the effective
        LLM config (resolving Stimma Cloud), use llm_resolver.get_effective_llm_config().
        """
        if role not in self.llms:
            raise ValueError(f"Unknown LLM role: {role}. Available: {list(self.llms.keys())}")
        return self.llms[role]

    def get_llm(self, role: str) -> LLMEndpointConfig:
        """Get LLM config by role (agent, agent-fast).

        DEPRECATED: Use llm_resolver.get_effective_llm_config() for full support.
        This returns endpoint config based on source, ignoring stimma_cloud.
        """
        role_config = self.get_llm_role_config(role)
        if role_config.source == 'endpoint' and role_config.endpoint:
            return role_config.endpoint
        # Fallback to empty config
        return LLMEndpointConfig()

    @property
    def agent_llm(self) -> LLMEndpointConfig:
        """Get the main agent LLM config.

        DEPRECATED: Use llm_resolver.get_effective_llm_config('agent') instead.
        """
        return self.get_llm("agent")

    @property
    def agent_fast_llm(self) -> LLMEndpointConfig:
        """Get the fast agent LLM config (for prompt enhancement, lora matching, etc.).

        DEPRECATED: Use llm_resolver.get_effective_llm_config('agent-fast') instead.
        """
        return self.get_llm("agent-fast")

    def get_upload_directory(self) -> str:
        """Get the directory for temporary reference image uploads."""
        if self.generation and self.generation.upload_directory:
            return os.path.expanduser(self.generation.upload_directory)
        return str(app_dirs.get_uploads_dir())

    def get_thumbnail_cache_dir(self) -> Path:
        """Get thumbnail cache directory (computed from app dirs)."""
        return app_dirs.get_thumbnail_cache_dir()

    def get_profile(self, profile_id: str) -> Optional[ProfileConfig]:
        """Get a profile by ID."""
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def get_folders_for_profile(self, profile_id: str) -> List[FolderConfig]:
        """Get folders for a specific profile."""
        profile = self.get_profile(profile_id)
        if profile:
            return profile.folders
        return []

    def get_markers_for_profile(self, profile_id: str) -> List[MarkerConfig]:
        """Get markers for a specific profile."""
        profile = self.get_profile(profile_id)
        if profile:
            return profile.markers
        return []

    def get_wildcards_for_profile(self, profile_id: str) -> List['WildcardEntry']:
        """Get wildcards for a specific profile."""
        profile = self.get_profile(profile_id)
        if profile:
            return profile.wildcards
        return []

    def get_prompt_segments_for_profile(self, profile_id: str) -> List['PromptSegmentEntry']:
        """Get prompt segments for a specific profile."""
        profile = self.get_profile(profile_id)
        if profile:
            return profile.prompt_segments
        return []

    def get_agent_for_profile(self, profile_id: str) -> ProfileAgentConfig:
        """Get agent settings for a specific profile."""
        profile = self.get_profile(profile_id)
        if profile:
            return profile.agent
        # Fallback to legacy global agent settings (for backward compatibility)
        return ProfileAgentConfig(
            additional_instructions=self.agent.additional_instructions,
            tool_config=self.agent.tool_config,
        )

    def get_generation_folders_for_profile(self, profile_id: str) -> List[FolderConfig]:
        """Get folders that allow generation for a specific profile."""
        folders = self.get_folders_for_profile(profile_id)
        return [folder for folder in folders if folder.allow_generate]

    def get_generation_folder_for_profile(self, profile_id: str) -> FolderConfig:
        """Get the single generation folder for a profile.

        Each profile must have exactly one folder with allow_generate=true.
        Raises ValueError if zero or multiple folders are configured.
        """
        folders = self.get_generation_folders_for_profile(profile_id)
        if len(folders) == 0:
            raise ValueError(f"Profile '{profile_id}' has no folder with allow_generate=true configured")
        if len(folders) > 1:
            raise ValueError(f"Profile '{profile_id}' has {len(folders)} folders with allow_generate=true - only one is allowed")
        return folders[0]

    def get_uploads_folder_for_profile(self, profile_id: str) -> Optional[FolderConfig]:
        """Get the uploads folder for a profile, or None if not configured."""
        folders = self.get_folders_for_profile(profile_id)
        uploads_folders = [f for f in folders if f.is_uploads_folder]
        if len(uploads_folders) > 1:
            raise ValueError(f"Profile '{profile_id}' has multiple uploads folders configured - only one is allowed")
        return uploads_folders[0] if uploads_folders else None

    @classmethod
    def load_config(cls, config_path: Optional[str] = None) -> "Settings":
        """Load configuration from YAML file.

        If config_path is not specified, uses the OS-specific data directory.
        Creates default config and directories if they don't exist.
        """
        # Determine config path - use explicit path or OS-specific location
        if config_path:
            config_file = Path(config_path)
        else:
            config_file = ensure_config_exists()

        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        # Expand environment variables in all string values
        config_data = expand_env_vars(config_data)

        # Remove deprecated thumbnail_cache_dir (now computed via app_dirs)
        config_data.pop('thumbnail_cache_dir', None)
        # Remove deprecated posthog_session_recording (PostHog removed)
        config_data.pop('posthog_session_recording', None)
        # Remove deprecated tracing section (client-side Langfuse removed)
        config_data.pop('tracing', None)

        # Parse the llms config structure (supports old and new formats)
        if 'llms' in config_data:
            parsed_llms = {}
            for role, llm_data in config_data['llms'].items():
                # Detect format by checking for 'source' field
                if 'source' in llm_data:
                    # New format with source field
                    source = llm_data.get('source', 'stimma_cloud')

                    # Migrate litellm source -> endpoint (litellm no longer supported)
                    if source == 'litellm':
                        source = 'endpoint'

                    # Parse endpoint config if present
                    endpoint_config = None
                    endpoint_data = llm_data.get('endpoint')
                    if endpoint_data:
                        endpoint_config = LLMEndpointConfig(**endpoint_data)

                    # Migrate old litellm config to endpoint if no endpoint exists
                    litellm_data = llm_data.get('litellm')
                    if litellm_data and not endpoint_config:
                        # Best-effort migration: litellm had provider/model/api_key
                        endpoint_config = LLMEndpointConfig(
                            url='',  # User will need to set this
                            model=litellm_data.get('model', ''),
                            api_key=litellm_data.get('api_key')
                        )

                    # Handle migration from old 'custom' format
                    custom_data = llm_data.get('custom')
                    if custom_data and not endpoint_config:
                        if 'endpoint' in custom_data:
                            old_endpoint = custom_data.get('endpoint', {})
                            if isinstance(old_endpoint, dict):
                                endpoint_config = LLMEndpointConfig(
                                    url=old_endpoint.get('url', ''),
                                    model=custom_data.get('model', ''),
                                    api_key=old_endpoint.get('api_key')
                                )
                                if source == 'custom':
                                    source = 'endpoint'

                    parsed_llms[role] = LLMRoleConfig(
                        source=source,
                        endpoint=endpoint_config
                    )
                else:
                    # Old format: direct provider/model/api_key fields
                    if 'endpoint' in llm_data and isinstance(llm_data['endpoint'], dict):
                        # Has endpoint -> migrate to endpoint source
                        old_endpoint = llm_data['endpoint']
                        endpoint_config = LLMEndpointConfig(
                            url=old_endpoint.get('url', ''),
                            model=llm_data.get('model', ''),
                            api_key=old_endpoint.get('api_key')
                        )
                        parsed_llms[role] = LLMRoleConfig(
                            source='endpoint',
                            endpoint=endpoint_config
                        )
                    else:
                        # No endpoint -> migrate to endpoint source (was litellm)
                        endpoint_config = LLMEndpointConfig(
                            url='',  # User will need to set this
                            model=llm_data.get('model', ''),
                            api_key=llm_data.get('api_key')
                        )
                        parsed_llms[role] = LLMRoleConfig(
                            source='endpoint',
                            endpoint=endpoint_config
                        )
            config_data['llms'] = parsed_llms

        # Parse agent config (no longer has llm, just llm_params)
        if 'agent' in config_data:
            agent_data = config_data['agent']
            # Parse llm_params if present
            if 'llm_params' in agent_data:
                agent_data['llm_params'] = AgentLLMParams(**agent_data['llm_params'])
            config_data['agent'] = AgentConfig(**agent_data)

        # Parse captioning config (no longer has llm)
        if 'captioning' in config_data:
            config_data['captioning'] = CaptioningConfig(**config_data['captioning'])

        # Migrate tool_providers: rename legacy 'transport' field to 'type'
        if 'tool_providers' in config_data:
            for tp in config_data['tool_providers']:
                if 'type' not in tp and 'transport' in tp:
                    tp['type'] = tp.pop('transport')

        # Parse cloud config (optional, defaults to CloudConfig())
        if 'cloud' in config_data:
            config_data['cloud'] = CloudConfig(**config_data['cloud'])

        # Handle folders (new format) or media_paths (old format)
        if 'folders' in config_data:
            folders_list = []
            media_paths_list = []
            for folder in config_data['folders']:
                folder_obj = FolderConfig(
                    path=os.path.expanduser(folder['path']),
                    readonly=folder.get('readonly', False),
                    allow_generate=folder.get('allow_generate', False),
                    is_uploads_folder=folder.get('is_uploads_folder', False),
                    uploads_subfolder=folder.get('uploads_subfolder', 'uploads'),
                    refresh_interval_seconds=folder.get('refresh_interval_seconds', 300),
                    markers=folder.get('markers', [])
                )
                folders_list.append(folder_obj)
                media_paths_list.append(folder_obj.path)
            config_data['folders'] = folders_list
            # Derive media_paths from folders for backward compatibility
            config_data['media_paths'] = media_paths_list
        elif 'media_paths' in config_data:
            # Old format: convert to folders
            config_data['media_paths'] = [
                os.path.expanduser(path) for path in config_data['media_paths']
            ]
            config_data['folders'] = [
                FolderConfig(path=path, readonly=False, allow_generate=False, refresh_interval_seconds=300)
                for path in config_data['media_paths']
            ]

        # Handle generators (supports both legacy flat models and new task-based structure)
        if 'generators' in config_data:
            parsed_generators = []
            for gen in config_data['generators']:
                # Parse LoRAs
                loras = None
                if gen.get('loras'):
                    loras = [
                        LoraConfig(
                            name=lora['name'],
                            path=lora['path'],
                            instructions=lora.get('instructions', ''),
                            model_families=lora.get('model-families', []),
                            profiles=lora.get('profiles')
                        )
                        for lora in gen['loras']
                    ]

                # Check for new task-based structure
                tasks = None
                if 'tasks' in gen:
                    tasks = {}
                    for task_name, task_data in gen['tasks'].items():
                        task_models = [
                            TaskModelConfig(**m) for m in task_data.get('models', [])
                        ]
                        tasks[task_name] = TaskConfig(models=task_models)

                # Parse lora_discovery config
                lora_discovery = None
                if gen.get('lora_discovery'):
                    ld = gen['lora_discovery']
                    family_filters = [
                        LoraFamilyFilterConfig(
                            family=f['family'],
                            lora_allowlist=f.get('lora_allowlist', []),
                            lora_denylist=f.get('lora_denylist', [])
                        )
                        for f in ld.get('family_filters', [])
                    ]
                    lora_discovery = LoraDiscoveryConfig(
                        global_denylist=ld.get('global_denylist', []),
                        family_filters=family_filters
                    )

                # Parse checkpoint_discovery config
                checkpoint_discovery = None
                if gen.get('checkpoint_discovery'):
                    cd = gen['checkpoint_discovery']
                    family_filters = [
                        CheckpointFamilyFilterConfig(
                            family=f['family'],
                            checkpoint_allowlist=f.get('checkpoint_allowlist', []),
                            checkpoint_denylist=f.get('checkpoint_denylist', [])
                        )
                        for f in cd.get('family_filters', [])
                    ]
                    checkpoint_discovery = CheckpointDiscoveryConfig(
                        global_denylist=cd.get('global_denylist', []),
                        family_filters=family_filters
                    )

                parsed_generators.append(GeneratorConfig(
                    type=gen['type'],
                    name=gen['name'],
                    address=gen.get('address'),  # Optional for API-based generators
                    api_key=gen.get('api_key'),  # For API-based generators
                    max_concurrent=gen.get('max_concurrent', 2),
                    tasks=tasks or {},
                    loras=loras,
                    lora_discovery=lora_discovery,
                    checkpoint_discovery=checkpoint_discovery,
                ))

            config_data['generators'] = parsed_generators

        # Handle generation config (upload directory, etc.)
        if 'generation' in config_data:
            config_data['generation'] = GenerationUploadConfig(**config_data['generation'])

        # Handle markers (legacy top-level)
        if 'markers' in config_data and not isinstance(config_data['markers'][0] if config_data['markers'] else None, MarkerConfig):
            config_data['markers'] = [
                MarkerConfig(**marker)
                for marker in config_data['markers']
            ]

        # Handle profiles
        if 'profiles' in config_data:
            parsed_profiles = []
            for profile in config_data['profiles']:
                # Parse profile folders
                profile_folders = []
                for folder in profile.get('folders', []):
                    is_uploads = folder.get('is_uploads_folder', False)
                    # Uploads folder implies allow_generate (if not explicitly set)
                    allow_gen = folder.get('allow_generate', is_uploads)
                    profile_folders.append(FolderConfig(
                        path=os.path.expanduser(folder['path']),
                        readonly=folder.get('readonly', False),
                        allow_generate=allow_gen,
                        is_uploads_folder=is_uploads,
                        uploads_subfolder=folder.get('uploads_subfolder', 'uploads'),
                        refresh_interval_seconds=folder.get('refresh_interval_seconds', 300),
                        markers=folder.get('markers', [])
                    ))

                # Parse profile markers
                profile_markers = []
                for marker in profile.get('markers', []):
                    profile_markers.append(MarkerConfig(**marker))

                # Parse profile agent settings
                profile_agent = ProfileAgentConfig()
                if 'agent' in profile:
                    agent_data = profile['agent']
                    tool_config = AgentToolConfig()
                    if 'tool_config' in agent_data:
                        tc = agent_data['tool_config']
                        tool_config = AgentToolConfig(
                            allowed_tools=tc.get('allowed_tools', []),
                            denied_tools=tc.get('denied_tools', []),
                            v2_permissions=tc.get('v2_permissions', {}),
                        )
                    elif 'allowed_tools' in agent_data or 'denied_tools' in agent_data:
                        # Support flat structure (allowed_tools directly under agent)
                        tool_config = AgentToolConfig(
                            allowed_tools=agent_data.get('allowed_tools', []),
                            denied_tools=agent_data.get('denied_tools', []),
                        )
                    profile_agent = ProfileAgentConfig(
                        additional_instructions=agent_data.get('additional_instructions', ''),
                        memory=agent_data.get('memory', ''),
                        tool_config=tool_config,
                    )

                # Parse profile wildcards
                profile_wildcards = [
                    WildcardEntry(**w) for w in profile.get('wildcards', [])
                ]

                # Parse profile prompt segments
                profile_prompt_segments = [
                    PromptSegmentEntry(**s) for s in profile.get('prompt_segments', [])
                ]

                # Database is always stimma_v1.db in the profile folder
                profile_dir = app_dirs.get_profile_dir(profile['id'])
                profile_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(profile_dir / 'stimma_v1.db')

                parsed_profiles.append(ProfileConfig(
                    id=profile['id'],
                    name=profile['name'],
                    database=db_path,
                    folders=profile_folders,
                    markers=profile_markers,
                    wildcards=profile_wildcards,
                    prompt_segments=profile_prompt_segments,
                    lora_allowlist=profile.get('lora_allowlist', []),
                    lora_denylist=profile.get('lora_denylist', []),
                    pin_hash=profile.get('pin_hash'),
                    pin_idle_timeout_minutes=profile.get('pin_idle_timeout_minutes', 30),
                    agent=profile_agent,
                ))
            config_data['profiles'] = parsed_profiles
        else:
            # No profiles defined - create default profile from legacy config
            # This provides backward compatibility
            legacy_folders = config_data.get('folders', [])
            legacy_markers = config_data.get('markers', [])
            # Resolve database path - use nanoid for new profile
            legacy_profile_id = generate_profile_id()
            default_db_path = str(app_dirs.get_profile_dir(legacy_profile_id) / 'stimma_v1.db')
            app_dirs.get_profile_dir(legacy_profile_id).mkdir(parents=True, exist_ok=True)
            config_data['profiles'] = [
                ProfileConfig(
                    id=legacy_profile_id,
                    name='Default',
                    database=default_db_path,
                    folders=legacy_folders if isinstance(legacy_folders, list) and legacy_folders and isinstance(legacy_folders[0], FolderConfig) else [],
                    markers=legacy_markers if isinstance(legacy_markers, list) and legacy_markers and isinstance(legacy_markers[0], MarkerConfig) else [],
                )
            ]

        # Aggregate media_paths from all profiles for backward compatibility with ingestion
        all_media_paths = []
        for profile in config_data['profiles']:
            for folder in profile.folders:
                if folder.path not in all_media_paths:
                    all_media_paths.append(folder.path)
        config_data['media_paths'] = all_media_paths

        return cls(**config_data)

    def get_generation_folders(self) -> List[FolderConfig]:
        """Get folders that allow generation."""
        return [folder for folder in self.folders if folder.allow_generate]


# Global settings instance
settings: Settings = None


def _ensure_marker_ids_persisted() -> bool:
    """Ensure all markers have IDs, generating and persisting them if missing.

    This is called once at startup. If any marker is missing an ID, we:
    1. Generate a stable ID (slugified name + short UUID)
    2. Write it back to the config file so it persists

    Returns:
        True if any IDs were generated and persisted, False otherwise.
    """
    import uuid

    # Load config with ruamel.yaml to preserve comments
    from ruamel.yaml import YAML
    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    yaml_parser.width = 120

    config_path = app_dirs.get_config_path()
    if not config_path.exists():
        return False

    with open(config_path, 'r') as f:
        data = yaml_parser.load(f)

    # Track if we made any changes
    changes_made = False

    # Check each profile's markers
    profiles = data.get('profiles', [])
    for profile in profiles:
        markers = profile.get('markers', [])
        for marker in markers:
            if not marker.get('id'):
                # Generate stable ID from name
                name = marker.get('name', '')
                slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-'))
                marker['id'] = f"{slug}-{str(uuid.uuid4())[:8]}" if slug else str(uuid.uuid4())[:8]
                changes_made = True

    if changes_made:
        # Write back to config file
        import tempfile
        import os

        config_dir = config_path.parent
        fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_dir)
        try:
            with os.fdopen(fd, 'w') as f:
                yaml_parser.dump(data, f)

            # Backup existing config
            backup_path = config_path.with_suffix('.yaml.bak')
            if config_path.exists():
                import shutil
                shutil.copy2(config_path, backup_path)

            # Atomic rename
            os.replace(temp_path, config_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    return changes_made


def _migrate_default_profile_ids() -> bool:
    """Migrate profiles with id='default' to nanoid-based IDs.

    For existing installs, renames the profile directory and updates config.yaml.
    Returns True if any migration was performed.
    """
    from ruamel.yaml import YAML

    config_path = app_dirs.get_config_path()
    if not config_path.exists():
        return False

    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    yaml_parser.width = 120

    with open(config_path, 'r') as f:
        data = yaml_parser.load(f)

    profiles = data.get('profiles', [])
    changes_made = False
    existing_ids = {
        profile.get('id')
        for profile in profiles
        if profile.get('id')
    }

    for profile in profiles:
        if profile.get('id') == 'default':
            new_id = generate_profile_id()
            while new_id in existing_ids:
                new_id = generate_profile_id()
            old_dir = app_dirs.get_profile_dir('default')
            new_dir = app_dirs.get_profile_dir(new_id)

            # Rename the profile directory if it exists
            if old_dir.exists() and not new_dir.exists():
                old_dir.rename(new_dir)
            elif not new_dir.exists():
                new_dir.mkdir(parents=True, exist_ok=True)

            profile['id'] = new_id
            existing_ids.add(new_id)
            changes_made = True

    if changes_made:
        import tempfile
        import shutil

        config_dir = config_path.parent
        fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_dir)
        try:
            with os.fdopen(fd, 'w') as f:
                yaml_parser.dump(data, f)

            backup_path = config_path.with_suffix('.yaml.bak')
            if config_path.exists():
                shutil.copy2(config_path, backup_path)

            os.replace(temp_path, config_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    return changes_made


def get_settings() -> Settings:
    """Get or create settings singleton."""
    global settings
    if settings is None:
        # Migrate profiles with id='default' to nanoid-based IDs
        _migrate_default_profile_ids()
        # Ensure all marker IDs are generated and persisted
        _ensure_marker_ids_persisted()
        settings = Settings.load_config()
    return settings


def reload_settings() -> Settings:
    """Reload settings from config file."""
    global settings
    # Ensure any newly added markers get IDs
    _ensure_marker_ids_persisted()
    settings = Settings.load_config()
    return settings


def detect_config_changes(old: Settings, new: Settings) -> set[str]:
    """Detect which top-level config sections have changed.

    Compares old and new Settings instances and returns a set of section names
    that differ. Used for incremental config reloading.

    Returns:
        Set of changed section names (e.g., {'profiles', 'clip', 'generators'})
    """
    changed = set()

    # Compare each top-level section by serializing to dict and comparing
    # This handles nested structures correctly
    sections = [
        'profiles',
        'generators',
        'tool_providers',
        'llms',
        'clip',
        'face_detection',
        'server',
        'agent',
        'captioning',
        'cloud',
    ]

    for section in sections:
        old_val = getattr(old, section, None)
        new_val = getattr(new, section, None)

        # Convert to comparable form
        old_data = _serialize_for_comparison(old_val)
        new_data = _serialize_for_comparison(new_val)

        if old_data != new_data:
            changed.add(section)

    return changed


def _serialize_for_comparison(value) -> object:
    """Serialize a config value for comparison.

    Handles Pydantic models, lists, dicts, and primitives.
    """
    if value is None:
        return None
    elif hasattr(value, 'model_dump'):
        # Pydantic model
        return value.model_dump()
    elif isinstance(value, list):
        return [_serialize_for_comparison(item) for item in value]
    elif isinstance(value, dict):
        return {k: _serialize_for_comparison(v) for k, v in value.items()}
    else:
        return value
